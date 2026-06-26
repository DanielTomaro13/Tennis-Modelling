"""Match engine — analytic hierarchical point -> game -> set -> match model.

From two players' surface profiles we derive per-point serve-win probabilities
(additive opponent-adjusted model) and roll them up exactly to every market:
match win prob, set-score distribution, total-games distribution / over-unders,
tie-break probability, and expected aces & double faults per player.

Everything is closed-form / dynamic-programming — no Monte-Carlo, so daily
runs are fast and deterministic. ``sim.js`` mirrors this for the live predictor.
"""
from __future__ import annotations

from functools import lru_cache


# --------------------------------------------------------------------------- #
# Point -> game
# --------------------------------------------------------------------------- #
def point_probs(prof_a: dict, prof_b: dict, league: dict) -> tuple[float, float]:
    """Return (p_a, p_b): prob the server wins a point, for A and B serving.

    Additive model: P(server wins) = spw_server - (rpw_returner - league_rpw).
    """
    lrpw = league["rpw"]
    p_a = prof_a["spw"] - (prof_b["rpw"] - lrpw)
    p_b = prof_b["spw"] - (prof_a["rpw"] - lrpw)
    return _clamp(p_a, 0.40, 0.93), _clamp(p_b, 0.40, 0.93)


def game_hold(p: float) -> float:
    """Probability the server holds, given per-point win prob p (exact)."""
    q = 1 - p
    pdeuce = 20 * p**3 * q**3
    win_from_deuce = p * p / (p * p + q * q)
    return p**4 + 4 * p**4 * q + 10 * p**4 * q**2 + pdeuce * win_from_deuce


def game_expected_points(p: float) -> float:
    """Expected number of points played in a service game (exact)."""
    q = 1 - p
    p4 = p**4 + q**4
    p5 = 4 * p * q * (p**3 + q**3)
    p6 = 10 * p**4 * q**2 + 10 * p**2 * q**4
    pdeuce = 20 * p**3 * q**3
    extra = 2.0 / (p * p + q * q)
    return 4 * p4 + 5 * p5 + 6 * p6 + (6 + extra) * pdeuce


# --------------------------------------------------------------------------- #
# Tie-break
# --------------------------------------------------------------------------- #
def tiebreak_win(p_a: float, p_b: float, first: str = "A") -> float:
    """Prob A wins a 7-point tie-break; A and B serve per standard rotation."""
    def server(n: int) -> str:
        g = (n + 1) // 2
        base = first
        return base if g % 2 == 0 else ("B" if base == "A" else "A")

    def win_point_a(n: int) -> float:
        return p_a if server(n) == "A" else (1 - p_b)

    @lru_cache(maxsize=None)
    def f(a: int, b: int) -> float:
        if a >= 7 and a - b >= 2:
            return 1.0
        if b >= 7 and b - a >= 2:
            return 0.0
        if a >= 6 and b >= 6 and a == b:
            # deuce zone: next two points (one per server pattern) -> +2 / split / -2
            n = a + b
            wa1 = win_point_a(n)
            wa2 = win_point_a(n + 1)
            both = wa1 * wa2
            split = wa1 * (1 - wa2) + (1 - wa1) * wa2
            return both / (1 - split) if split < 1 else 0.5
        n = a + b
        wa = win_point_a(n)
        return wa * f(a + 1, b) + (1 - wa) * f(a, b + 1)

    return f(0, 0)


# --------------------------------------------------------------------------- #
# Set
# --------------------------------------------------------------------------- #
def set_distribution(p_a: float, p_b: float, first: str = "A") -> list[tuple[float, int, int, bool]]:
    """Distribution of final set scores.

    Returns list of (prob, games_a, games_b, tiebreak?) terminal outcomes.
    Games alternate serve starting from ``first``.
    """
    from collections import defaultdict

    hold_a = game_hold(p_a)
    hold_b = game_hold(p_b)
    # tie-break server at 6-6 is whoever serves the 13th game (games played = 12).
    tb_first = first if (12 % 2 == 0) else ("B" if first == "A" else "A")
    tb_a = tiebreak_win(p_a, p_b, first=tb_first)

    def server_of(ga: int, gb: int) -> str:
        return first if (ga + gb) % 2 == 0 else ("B" if first == "A" else "A")

    def is_terminal(ga: int, gb: int) -> bool:
        return ((ga == 6 and gb <= 4) or (gb == 6 and ga <= 4)
                or (ga == 7 and gb == 5) or (gb == 7 and ga == 5))

    terminal: dict[tuple[int, int, bool], float] = defaultdict(float)
    # Layered DP over games played (0..13); guarantees all incoming mass arrives.
    layer = {(0, 0): 1.0}
    for _ in range(13):
        nxt: dict[tuple[int, int], float] = defaultdict(float)
        for (ga, gb), prob in layer.items():
            if is_terminal(ga, gb):
                terminal[(ga, gb, False)] += prob
                continue
            if ga == 6 and gb == 6:
                terminal[(7, 6, True)] += prob * tb_a
                terminal[(6, 7, True)] += prob * (1 - tb_a)
                continue
            srv = server_of(ga, gb)
            a_wins_game = hold_a if srv == "A" else (1 - hold_b)
            nxt[(ga + 1, gb)] += prob * a_wins_game
            nxt[(ga, gb + 1)] += prob * (1 - a_wins_game)
        layer = nxt
    # fold any residual mass (shouldn't remain after 13 games)
    for (ga, gb), prob in layer.items():
        terminal[(ga, gb, ga == 6 and gb == 6)] += prob

    return [(pr, ga, gb, tb) for (ga, gb, tb), pr in terminal.items()]


# --------------------------------------------------------------------------- #
# Match
# --------------------------------------------------------------------------- #
def project_match(prof_a: dict, prof_b: dict, league: dict, best_of: int = 3,
                  totals_lines: list | None = None) -> dict:
    """Full market projection for A vs B. Returns a dict of probabilities."""
    p_a, p_b = point_probs(prof_a, prof_b, league)
    sets_to_win = 3 if best_of == 5 else 2

    from collections import defaultdict

    # Per-set outcome distributions, alternating who serves first each set.
    set_dist_even = set_distribution(p_a, p_b, first="A")  # sets 1,3,5
    set_dist_odd = set_distribution(p_a, p_b, first="B")   # sets 2,4

    # Layered DP over number of sets played: state (sa, sb, total_games, any_tb).
    state = defaultdict(float)
    state[(0, 0, 0, False)] = 1.0
    final = defaultdict(float)
    for set_index in range(2 * sets_to_win - 1):
        nxt = defaultdict(float)
        base_set = set_dist_even if set_index % 2 == 0 else set_dist_odd
        for (sa, sb, tg, anytb), prob in state.items():
            if sa == sets_to_win or sb == sets_to_win:
                final[(sa, sb, tg, anytb)] += prob
                continue
            for spr, ga, gb, tb in base_set:
                a_won = ga > gb
                nsa = sa + (1 if a_won else 0)
                nsb = sb + (0 if a_won else 1)
                nxt[(nsa, nsb, tg + ga + gb, anytb or tb)] += prob * spr
        state = nxt
    for key, prob in state.items():
        final[key] += prob

    # Aggregate markets from `final`
    match_win_a = 0.0
    setscore: dict[str, float] = defaultdict(float)
    games_dist: dict[int, float] = defaultdict(float)
    any_tb_prob = 0.0
    exp_total_games = 0.0
    for (sa, sb, tg, anytb), pr in final.items():
        a_won = sa > sb
        if a_won:
            match_win_a += pr
        setscore[f"{sa}-{sb}"] += pr
        games_dist[tg] += pr
        exp_total_games += pr * tg
        if anytb:
            any_tb_prob += pr

    totals_lines = totals_lines or [20.5, 21.5, 22.5, 23.5]
    totals = {}
    for line in totals_lines:
        over = sum(pr for g, pr in games_dist.items() if g > line)
        totals[str(line)] = {"over": round(over, 4), "under": round(1 - over, 4)}

    # Expected serve points per player -> aces / double faults.
    epg_a = game_expected_points(p_a)
    epg_b = game_expected_points(p_b)
    # each player serves ~half the games; split expected total games by hold-weighted share
    serve_games_a = exp_total_games / 2.0
    serve_games_b = exp_total_games / 2.0
    sp_a = serve_games_a * epg_a
    sp_b = serve_games_b * epg_b

    return {
        "p_a_serve": round(p_a, 4),
        "p_b_serve": round(p_b, 4),
        "hold_a": round(game_hold(p_a), 4),
        "hold_b": round(game_hold(p_b), 4),
        "sr_win_a": round(match_win_a, 4),
        "set_score": {k: round(v, 4) for k, v in sorted(setscore.items())},
        "exp_total_games": round(exp_total_games, 2),
        "totals": totals,
        "tiebreak_prob": round(any_tb_prob, 4),
        "exp_aces_a": round(prof_a["ace_rate"] * sp_a, 2),
        "exp_aces_b": round(prof_b["ace_rate"] * sp_b, 2),
        "exp_df_a": round(prof_a["df_rate"] * sp_a, 2),
        "exp_df_b": round(prof_b["df_rate"] * sp_b, 2),
    }


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


if __name__ == "__main__":
    # smoke test: a strong server vs an average player on hard court
    league = {"spw": 0.645, "rpw": 0.355}
    a = {"spw": 0.70, "rpw": 0.42, "ace_rate": 0.10, "df_rate": 0.04}
    b = {"spw": 0.64, "rpw": 0.36, "ace_rate": 0.06, "df_rate": 0.05}
    import json
    print(json.dumps(project_match(a, b, league, best_of=3), indent=2))
