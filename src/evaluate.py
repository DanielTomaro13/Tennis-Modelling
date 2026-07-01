"""Model assembly + leakage-safe backtest.

Headline win probability = logit blend of the serve/return sim with a results-based
surface Elo (independent signal, far better on skill gaps). The serve/return sim is
then anchored to that win prob so every derived market is consistent. The backtest
rebuilds Elo walk-forward (only past results) on a held-out season.
"""
from __future__ import annotations

import csv
import math
import os
import sys

from . import features, ingest, ratings, sim, util


def _scope(prof: dict, surface: str) -> dict:
    s = prof.get(surface) or prof.get("overall")
    return {**s, "name": prof["name"]}


def _logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def _sig(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def tour_elo_weight(cfg: dict, tour: str) -> float:
    return float(cfg["sim"].get(f"elo_weight_{tour}", 0.85))


def combine(sim_p: float, elo_p: float | None, w: float) -> float:
    """Logit blend of the sim win prob with the Elo win prob (w on Elo)."""
    if elo_p is None:
        return sim_p
    return _sig((1 - w) * _logit(sim_p) + w * _logit(elo_p))


def default_profile(name: str, league: dict) -> dict:
    """League-average serve profile for a player with Elo history but no charted
    serve data. The headline prob goes pure Elo for these; the profile only
    shapes the derived markets (totals, handicaps) around that anchor."""
    scope = {"spw": league["spw"], "rpw": league["rpw"], "ace_rate": 0.06,
             "df_rate": 0.04, "first_in": 0.60, "first_win": 0.72,
             "second_win": 0.50, "serve_pts": 0.0, "pr": 0.0}
    return {"name": name, "_default": True,
            "overall": scope, "Hard": scope, "Clay": scope, "Grass": scope}


def model_match(cfg: dict, pa: dict, pb: dict, league: dict, surface: str,
                best_of: int, elo, tour: str):
    """Return (win_a, anchored_markets) — headline win prob + all derived markets."""
    sa, sb = _scope(pa, surface), _scope(pb, surface)
    lines = cfg["sim"]["totals_lines"]
    sim_p = sim.project_match(sa, sb, league, best_of=best_of, totals_lines=lines)["sr_win_a"]
    elo_p = ratings.elo_win_prob(elo, pa["name"], pb["name"], surface, cfg["elo"]["surface_weight"]) if elo else None
    # a default (league-average) profile contributes nothing to the winner call —
    # lean fully on Elo for the headline prob when either side lacks serve data
    w = 1.0 if (pa.get("_default") or pb.get("_default")) else tour_elo_weight(cfg, tour)
    target = combine(sim_p, elo_p, w)
    markets = sim.anchor_to(sa, sb, league, best_of, target, lines)
    return target, markets


# back-compat shim (kept for any external callers)
def blended_win_prob(cfg, prof_a, prof_b, league, surface, best_of, elo=None, blend=None):
    return model_match(cfg, prof_a, prof_b, league, surface, best_of, elo,
                       prof_a.get("tour", "atp"))[0]


# --------------------------------------------------------------------------- #
# Backtest — walk-forward Elo on a held-out season
# --------------------------------------------------------------------------- #
def _ensure_results(cfg, tour):
    path = util.abspath(os.path.join(cfg["data"]["processed_dir"], f"results-{tour}.csv"))
    if not os.path.exists(path):
        util.log("evaluate: results missing -> deriving winners")
        ingest.derive_winners(cfg)
    return path


def _ece(probs: list[float], bins: int = 10) -> float:
    """Expected calibration error. Every prediction here is for the actual
    winner (outcome=1), so fold onto the favourite side: predicting p for the
    winner is one observation of outcome=1 at p."""
    tot = len(probs)
    if not tot:
        return 0.0
    bucket_p: dict[int, list[float]] = {}
    for p in probs:
        # reflect: a p<0.5 winner prediction is a (1-p) loser prediction at 1-p
        q, y = (p, 1.0) if p >= 0.5 else (1 - p, 0.0)
        bucket_p.setdefault(min(int(q * bins), bins - 1), []).append((q, y))
    err = 0.0
    for vals in bucket_p.values():
        if len(vals) < 30:
            continue
        qm = sum(v[0] for v in vals) / len(vals)
        ym = sum(v[1] for v in vals) / len(vals)
        err += (len(vals) / tot) * abs(qm - ym)
    return err


def evaluate_tour(cfg: dict, tour: str) -> dict:
    path = _ensure_results(cfg, tour)
    cutoff = int(cfg["backtest"]["holdout_start_year"]) * 10000
    profiles = features.build_profiles(cfg, tour, max_date=cutoff)
    league, players = profiles["league"], profiles["players"]
    w = tour_elo_weight(cfg, tour)
    e = cfg["elo"]; init = e["initial"]; surf_w = e["surface_weight"]
    regress = float(e.get("season_regression", 0.0))
    overall, surface, played, last_season = {}, {}, {}, {}

    rows = list(csv.DictReader(open(path, newline="")))
    rows.sort(key=lambda r: int(r.get("date") or 0))

    n = ll = brier = correct = 0
    ll_elo = ll_sim = 0.0
    ll_mkt = 0.0; n_mkt = 0; ll_blend_on_mkt = 0.0
    blend_probs: list[float] = []
    n_skipped = n_prof = 0
    for r in rows:
        a, b, surf = r["winner"], r["loser"], r.get("surface", "Hard")
        best_of = int(r.get("best_of") or 3)
        season = int(r.get("date") or 0) // 10000
        surface.setdefault(surf, {})
        for p_ in (a, b):
            prev = last_season.get(p_)
            if prev is not None and season > prev and regress > 0:
                overall[p_] = init + (1 - regress) * (overall.get(p_, init) - init)
                for sd in surface.values():
                    if p_ in sd:
                        sd[p_] = init + (1 - regress) * (sd[p_] - init)
            last_season[p_] = season
        if int(r.get("date") or 0) >= cutoff:
            ra = surf_w * surface[surf].get(a, init) + (1 - surf_w) * overall.get(a, init)
            rb = surf_w * surface[surf].get(b, init) + (1 - surf_w) * overall.get(b, init)
            elo_p = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
            profiled = a in players and b in players
            if profiled:
                sim_p = sim.project_match(_scope(players[a], surf), _scope(players[b], surf),
                                          league, best_of=best_of)["sr_win_a"]
                p = min(max(combine(sim_p, elo_p, w), 1e-6), 1 - 1e-6)
                ll_sim += -math.log(min(max(sim_p, 1e-6), 1 - 1e-6))
                n_prof += 1
            else:
                # Elo-only fallback — exactly what production does for these
                p = min(max(elo_p, 1e-6), 1 - 1e-6)
                n_skipped += 1
            n += 1
            ll += -math.log(p)
            ll_elo += -math.log(min(max(elo_p, 1e-6), 1 - 1e-6))
            brier += (1 - p) ** 2
            correct += 1 if p > 0.5 else 0
            blend_probs.append(p)
            # market baseline: de-vigged closing odds, same match
            try:
                ow, ol = float(r.get("odds_w") or 0), float(r.get("odds_l") or 0)
            except ValueError:
                ow = ol = 0.0
            if ow > 1.0 and ol > 1.0:
                p_mkt = (1 / ow) / (1 / ow + 1 / ol)
                ll_mkt += -math.log(min(max(p_mkt, 1e-6), 1 - 1e-6))
                ll_blend_on_mkt += -math.log(p)
                n_mkt += 1
        # update Elo (walk-forward, matches production compute_elo)
        ow, ol = overall.get(a, init), overall.get(b, init)
        sa_, sb_ = surface[surf].get(a, init), surface[surf].get(b, init)
        rwin, rlose = surf_w * sa_ + (1 - surf_w) * ow, surf_w * sb_ + (1 - surf_w) * ol
        exp = 1.0 / (1.0 + 10 ** ((rlose - rwin) / 400.0))
        kw = ratings._k_factor(cfg, played.get(a, 0), best_of)
        kl = ratings._k_factor(cfg, played.get(b, 0), best_of)
        overall[a], overall[b] = ow + kw * (1 - exp), ol - kl * (1 - exp)
        surface[surf][a], surface[surf][b] = sa_ + kw * (1 - exp), sb_ - kl * (1 - exp)
        played[a] = played.get(a, 0) + 1
        played[b] = played.get(b, 0) + 1

    if n == 0:
        return {"tour": tour, "n": 0}
    out = {"tour": tour, "n": n, "n_elo_only_fallback": n_skipped,
           "log_loss": round(ll / n, 4), "brier": round(brier / n, 4),
           "accuracy": round(correct / n, 4),
           "log_loss_elo_only": round(ll_elo / n, 4),
           "log_loss_sim_only_profiled": round(ll_sim / n_prof, 4) if n_prof else None,
           "calibration_error": round(_ece(blend_probs), 4)}
    if n_mkt:
        out["n_with_market"] = n_mkt
        out["log_loss_market"] = round(ll_mkt / n_mkt, 4)
        out["log_loss_model_on_market_rows"] = round(ll_blend_on_mkt / n_mkt, 4)
    return out


def main(argv):
    cfg = util.load_config()
    reports = util.ensure_dir(util.abspath(cfg["paths"]["reports_dir"]))
    results = []
    for tour in cfg["tours"]:
        res = evaluate_tour(cfg, tour)
        results.append(res)
        util.log(f"evaluate: {res}")
    util.write_json(util.abspath(f"{reports}/backtest.json"), results, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
