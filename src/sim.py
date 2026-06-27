"""Match engine — analytic hierarchical point -> game -> set -> match model.

From two players' surface profiles we derive per-point serve-win probabilities
(additive opponent-adjusted model) and roll them up exactly to every market:
match win prob, set-score distribution, total-games distribution / over-unders,
tie-break probability, and expected aces & double faults per player.

Everything is closed-form / dynamic-programming — no Monte-Carlo, so daily
runs are fast and deterministic. ``sim.js`` mirrors this for the live predictor.
"""
from __future__ import annotations

import math
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
def game_hold_noad(p: float) -> float:
    """No-ad scoring: first to 4 points, single deciding point at 3-3."""
    q = 1 - p
    return p**4 + 4 * p**4 * q + 10 * p**4 * q**2 + 20 * p**4 * q**3


def tiebreak_win(p_a: float, p_b: float, first: str = "A", target: int = 7) -> float:
    """Prob A wins a tie-break to ``target`` points; standard serve rotation."""
    def server(n: int) -> str:
        g = (n + 1) // 2
        base = first
        return base if g % 2 == 0 else ("B" if base == "A" else "A")

    def win_point_a(n: int) -> float:
        return p_a if server(n) == "A" else (1 - p_b)

    @lru_cache(maxsize=None)
    def f(a: int, b: int) -> float:
        if a >= target and a - b >= 2:
            return 1.0
        if b >= target and b - a >= 2:
            return 0.0
        if a >= target - 1 and b >= target - 1 and a == b:
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
def set_distribution(p_a: float, p_b: float, first: str = "A",
                     no_ad: bool = False) -> list[tuple[float, int, int, bool]]:
    """Distribution of final set scores.

    Returns list of (prob, games_a, games_b, tiebreak?) terminal outcomes.
    Games alternate serve starting from ``first``. ``no_ad`` uses doubles scoring.
    """
    from collections import defaultdict

    hold_fn = game_hold_noad if no_ad else game_hold
    hold_a = hold_fn(p_a)
    hold_b = hold_fn(p_b)
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
    # Match DP tracking (sets_a, sets_b, games_a, games_b, any_tiebreak).
    state = defaultdict(float)
    state[(0, 0, 0, 0, False)] = 1.0
    final = defaultdict(float)
    for set_index in range(2 * sets_to_win - 1):
        nxt = defaultdict(float)
        base_set = set_dist_even if set_index % 2 == 0 else set_dist_odd
        for (sa, sb, ga, gb, anytb), prob in state.items():
            if sa == sets_to_win or sb == sets_to_win:
                final[(sa, sb, ga, gb, anytb)] += prob
                continue
            for spr, sga, sgb, tb in base_set:
                a_won = sga > sgb
                nsa = sa + (1 if a_won else 0)
                nsb = sb + (0 if a_won else 1)
                nxt[(nsa, nsb, ga + sga, gb + sgb, anytb or tb)] += prob * spr
        state = nxt
    for key, prob in state.items():
        final[key] += prob

    # ----- aggregate joint distribution into markets -----
    match_win_a = any_tb_prob = exp_total_games = exp_games_a = exp_games_b = 0.0
    setscore: dict[str, float] = defaultdict(float)
    games_dist: dict[int, float] = defaultdict(float)     # total games
    margin_dist: dict[int, float] = defaultdict(float)    # games_a - games_b
    a_games_dist: dict[int, float] = defaultdict(float)
    b_games_dist: dict[int, float] = defaultdict(float)
    for (sa, sb, ga, gb, anytb), pr in final.items():
        if sa > sb:
            match_win_a += pr
        setscore[f"{sa}-{sb}"] += pr
        tg = ga + gb
        games_dist[tg] += pr
        margin_dist[ga - gb] += pr
        a_games_dist[ga] += pr
        b_games_dist[gb] += pr
        exp_total_games += pr * tg
        exp_games_a += pr * ga
        exp_games_b += pr * gb
        if anytb:
            any_tb_prob += pr

    def over_under(dist, line):
        over = sum(pr for v, pr in dist.items() if v > line)
        return {"over": round(over, 4), "under": round(1 - over, 4)}

    totals_lines = totals_lines or [20.5, 21.5, 22.5, 23.5]
    totals = {str(l): over_under(games_dist, l) for l in totals_lines}

    # Games handicap from A's perspective. Label is A's line: "A -6.5" means A
    # must win by >6.5 games -> P(margin > 6.5). Listed ascending (-6.5 .. +6.5).
    handicap = {}
    for thr in [6.5, 4.5, 2.5, 1.5, -1.5, -2.5, -4.5, -6.5]:
        cover = sum(pr for m, pr in margin_dist.items() if m > thr)
        handicap[("%+.1f" % (-thr))] = round(cover, 4)

    # Per-set winner (marginal): set 1 server A, set 2 server B, set 3 server A.
    set1_a = sum(p for p, sga, sgb, _ in set_dist_even if sga > sgb)
    set2_a = sum(p for p, sga, sgb, _ in set_dist_odd if sga > sgb)

    a_set0 = sum(pr for k, pr in setscore.items() if k.startswith("0-"))
    b_set0 = sum(pr for k, pr in setscore.items() if k.endswith("-0"))
    straight = sum(pr for k, pr in setscore.items()
                   if min(int(k[0]), int(k[-1])) == 0 and max(int(k[0]), int(k[-1])) == sets_to_win)

    # Player game totals (a few lines around the mean).
    def player_game_ou(dist, mean):
        c = round(mean)
        return {("%.1f" % (c + d + 0.5)): over_under(dist, c + d + 0.5) for d in (-2, -1, 0, 1, 2)}

    # Expected serve points -> aces / double faults (+ Poisson over/unders).
    sp_a = (exp_games_a) * game_expected_points(p_a)
    sp_b = (exp_games_b) * game_expected_points(p_b)
    exp_aces_a = prof_a["ace_rate"] * sp_a
    exp_aces_b = prof_b["ace_rate"] * sp_b
    exp_df_a = prof_a["df_rate"] * sp_a
    exp_df_b = prof_b["df_rate"] * sp_b

    def poisson_ou(mean):
        c = max(0, round(mean))
        out = {}
        for d in (-2, -1, 0, 1, 2):
            line = c + d + 0.5
            if line <= 0:
                continue
            out["%.1f" % line] = round(1 - _poisson_cdf(int(line), mean), 4)  # P(X > line) = P(X >= line+0.5)
        return out

    most_aces = _most_compare(exp_aces_a, exp_aces_b)
    most_df = _most_compare(exp_df_a, exp_df_b)

    # Breaks of serve: a break = the returner wins a service game.
    serve_games_each = exp_total_games / 2.0
    breaks_a = serve_games_each * (1 - game_hold(p_b))   # A breaks B's serve
    breaks_b = serve_games_each * (1 - game_hold(p_a))   # B breaks A's serve
    exp_total_breaks = breaks_a + breaks_b

    return {
        "p_a_serve": round(p_a, 4),
        "p_b_serve": round(p_b, 4),
        "hold_a": round(game_hold(p_a), 4),
        "hold_b": round(game_hold(p_b), 4),
        "sr_win_a": round(match_win_a, 4),
        "set1_win_a": round(set1_a, 4),
        "set2_win_a": round(set2_a, 4),
        "straight_sets": round(straight, 4),
        "deciding_set": round(1 - straight, 4),
        "a_wins_set": round(1 - a_set0, 4),
        "b_wins_set": round(1 - b_set0, 4),
        "set_score": {k: round(v, 4) for k, v in sorted(setscore.items())},
        "exp_total_games": round(exp_total_games, 2),
        "exp_games_a": round(exp_games_a, 2),
        "exp_games_b": round(exp_games_b, 2),
        "totals": totals,
        "handicap": handicap,
        "player_games_a": player_game_ou(a_games_dist, exp_games_a),
        "player_games_b": player_game_ou(b_games_dist, exp_games_b),
        "tiebreak_prob": round(any_tb_prob, 4),
        "exp_aces_a": round(exp_aces_a, 2),
        "exp_aces_b": round(exp_aces_b, 2),
        "exp_df_a": round(exp_df_a, 2),
        "exp_df_b": round(exp_df_b, 2),
        "aces_ou_a": poisson_ou(exp_aces_a),
        "aces_ou_b": poisson_ou(exp_aces_b),
        "df_ou_a": poisson_ou(exp_df_a),
        "df_ou_b": poisson_ou(exp_df_b),
        "most_aces": most_aces,
        "most_df": most_df,
        "exp_breaks_a": round(breaks_a, 2),
        "exp_breaks_b": round(breaks_b, 2),
        "exp_total_breaks": round(exp_total_breaks, 2),
        "breaks_ou": poisson_ou(exp_total_breaks),
        "most_breaks": _most_compare(breaks_a, breaks_b),
        "break_at_least_a": round(1 - math.exp(-breaks_a), 4),   # A breaks >=1
        "break_at_least_b": round(1 - math.exp(-breaks_b), 4),
        "hold_all_a": round(math.exp(-breaks_b), 4),             # A never broken
        "hold_all_b": round(math.exp(-breaks_a), 4),
    }


def _most_compare(lam_a: float, lam_b: float) -> dict:
    """For X~Pois(lam_a), Y~Pois(lam_b): P(X>Y), P(tie), P(Y>X)."""
    import math
    k_max = max(30, int(max(lam_a, lam_b) * 2) + 25)

    def pmf_list(lam: float) -> list[float]:
        out = [math.exp(-lam)] if lam > 0 else [1.0]
        for k in range(1, k_max + 1):
            out.append(out[-1] * lam / k if lam > 0 else 0.0)
        return out

    pa, pb = pmf_list(lam_a), pmf_list(lam_b)
    p_a_gt = p_tie = cum_a = 0.0
    for y in range(k_max + 1):
        cum_a += pa[y]                    # P(X <= y)
        p_a_gt += pb[y] * (1 - cum_a)     # P(Y=y) * P(X > y)
        p_tie += pa[y] * pb[y]
    p_b_gt = max(0.0, 1 - p_a_gt - p_tie)
    return {"a": round(p_a_gt, 4), "tie": round(p_tie, 4), "b": round(p_b_gt, 4)}


def _poisson_cdf(k: int, mean: float) -> float:
    """P(X <= k) for X ~ Poisson(mean)."""
    import math
    if mean <= 0:
        return 1.0
    term = math.exp(-mean)
    cdf = term
    for i in range(1, k + 1):
        term *= mean / i
        cdf += term
    return min(1.0, cdf)


def distributions(prof_a: dict, prof_b: dict, league: dict, best_of: int = 3) -> dict:
    """Raw model distributions so odds.py can price ANY book line exactly."""
    from collections import defaultdict

    p_a, p_b = point_probs(prof_a, prof_b, league)
    sets_to_win = 3 if best_of == 5 else 2
    set_even = set_distribution(p_a, p_b, first="A")
    set_odd = set_distribution(p_a, p_b, first="B")

    state = defaultdict(float)
    state[(0, 0, 0, 0)] = 1.0
    final = defaultdict(float)
    for si in range(2 * sets_to_win - 1):
        nxt = defaultdict(float)
        base = set_even if si % 2 == 0 else set_odd
        for (sa, sb, ga, gb), prob in state.items():
            if sa == sets_to_win or sb == sets_to_win:
                final[(sa, sb, ga, gb)] += prob
                continue
            for spr, sga, sgb, _ in base:
                a_won = sga > sgb
                nxt[(sa + (1 if a_won else 0), sb + (0 if a_won else 1), ga + sga, gb + sgb)] += prob * spr
        state = nxt
    for k, prob in state.items():
        final[k] += prob

    set_score = defaultdict(float)
    games_dist = defaultdict(float)
    margin_dist = defaultdict(float)
    ega = egb = 0.0
    for (sa, sb, ga, gb), pr in final.items():
        set_score[f"{sa}-{sb}"] += pr
        games_dist[ga + gb] += pr
        margin_dist[ga - gb] += pr
        ega += pr * ga
        egb += pr * gb

    set1 = sum(p for p, sga, sgb, _ in set_even if sga > sgb)
    set2 = sum(p for p, sga, sgb, _ in set_odd if sga > sgb)
    epg_a, epg_b = game_expected_points(p_a), game_expected_points(p_b)
    return {
        "set_score": dict(set_score),
        "set1_win_a": set1, "set2_win_a": set2,
        "games_dist": dict(games_dist), "margin_dist": dict(margin_dist),
        "exp_games_a": ega, "exp_games_b": egb,
        "ace_mean_a": prof_a["ace_rate"] * ega * epg_a, "ace_mean_b": prof_b["ace_rate"] * egb * epg_b,
        "df_mean_a": prof_a["df_rate"] * ega * epg_a, "df_mean_b": prof_b["df_rate"] * egb * epg_b,
    }


def team_profile(p1: dict, p2: dict) -> dict:
    """Average two players' singles profiles into one doubles-team profile."""
    keys = ("spw", "rpw", "ace_rate", "df_rate", "pr")
    return {k: (p1[k] + p2[k]) / 2.0 for k in keys}


def project_doubles(team_a: dict, team_b: dict, league: dict) -> dict:
    """Doubles projection: no-ad games, 7-pt set TB, 10-pt match TB decider."""
    p_a, p_b = point_probs(team_a, team_b, league)
    set_even = set_distribution(p_a, p_b, first="A", no_ad=True)
    set_odd = set_distribution(p_a, p_b, first="B", no_ad=True)

    def set_win(dist):
        return sum(p for p, ga, gb, _ in dist if ga > gb)

    def tb_in(dist):
        return sum(p for p, _, _, tb in dist if tb)

    def games(dist):
        return sum(p * (ga + gb) for p, ga, gb, _ in dist)

    s1a, s2a = set_win(set_even), set_win(set_odd)
    super_a = tiebreak_win(p_a, p_b, first="A", target=10)
    p20 = s1a * s2a
    p02 = (1 - s1a) * (1 - s2a)
    split = s1a * (1 - s2a) + (1 - s1a) * s2a
    p21, p12 = split * super_a, split * (1 - super_a)
    win_a = p20 + p21
    return {
        "sr_win_a": round(win_a, 4),
        "set_score": {k: round(v, 4) for k, v in
                      {"2-0": p20, "2-1": p21, "1-2": p12, "0-2": p02}.items()},
        "straight_sets": round(p20 + p02, 4),
        "deciding_set": round(split, 4),
        "a_wins_set": round(1 - p02, 4),
        "b_wins_set": round(1 - p20, 4),
        "set1_win_a": round(s1a, 4),
        "set2_win_a": round(s2a, 4),
        "super_tb_a": round(super_a, 4),
        "exp_total_games": round(games(set_even) + games(set_odd), 2),
        "tiebreak_prob": round(1 - (1 - tb_in(set_even)) * (1 - tb_in(set_odd)), 4),
        "hold_a": round(game_hold_noad(p_a), 4),
        "hold_b": round(game_hold_noad(p_b), 4),
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
