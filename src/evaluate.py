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


def model_match(cfg: dict, pa: dict, pb: dict, league: dict, surface: str,
                best_of: int, elo, tour: str):
    """Return (win_a, anchored_markets) — headline win prob + all derived markets."""
    sa, sb = _scope(pa, surface), _scope(pb, surface)
    lines = cfg["sim"]["totals_lines"]
    sim_p = sim.project_match(sa, sb, league, best_of=best_of, totals_lines=lines)["sr_win_a"]
    elo_p = ratings.elo_win_prob(elo, pa["name"], pb["name"], surface, cfg["elo"]["surface_weight"]) if elo else None
    target = combine(sim_p, elo_p, tour_elo_weight(cfg, tour))
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


def evaluate_tour(cfg: dict, tour: str) -> dict:
    path = _ensure_results(cfg, tour)
    cutoff = int(cfg["backtest"]["holdout_start_year"]) * 10000
    profiles = features.build_profiles(cfg, tour, max_date=cutoff)
    league, players = profiles["league"], profiles["players"]
    w = tour_elo_weight(cfg, tour)
    e = cfg["elo"]; init = e["initial"]; surf_w = e["surface_weight"]
    overall, surface, played = {}, {}, {}

    rows = list(csv.DictReader(open(path, newline="")))
    rows.sort(key=lambda r: int(r.get("date") or 0))

    n = ll = brier = correct = base_correct = 0
    for r in rows:
        a, b, surf = r["winner"], r["loser"], r.get("surface", "Hard")
        surface.setdefault(surf, {})
        if int(r.get("date") or 0) >= cutoff and a in players and b in players:
            ra = surf_w * surface[surf].get(a, init) + (1 - surf_w) * overall.get(a, init)
            rb = surf_w * surface[surf].get(b, init) + (1 - surf_w) * overall.get(b, init)
            elo_p = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
            sim_p = sim.project_match(_scope(players[a], surf), _scope(players[b], surf), league, best_of=3)["sr_win_a"]
            p = min(max(combine(sim_p, elo_p, w), 1e-6), 1 - 1e-6)
            n += 1
            ll += -math.log(p)
            brier += (1 - p) ** 2
            correct += 1 if p > 0.5 else 0
            base_correct += 1 if elo_p > 0.5 else 0
        # update Elo
        ow, ol = overall.get(a, init), overall.get(b, init)
        sa_, sb_ = surface[surf].get(a, init), surface[surf].get(b, init)
        rwin, rlose = surf_w * sa_ + (1 - surf_w) * ow, surf_w * sb_ + (1 - surf_w) * ol
        exp = 1.0 / (1.0 + 10 ** ((rlose - rwin) / 400.0))
        kw, kl = ratings._k_factor(cfg, played.get(a, 0), 3), ratings._k_factor(cfg, played.get(b, 0), 3)
        overall[a], overall[b] = ow + kw * (1 - exp), ol - kl * (1 - exp)
        surface[surf][a], surface[surf][b] = sa_ + kw * (1 - exp), sb_ - kl * (1 - exp)
        played[a] = played.get(a, 0) + 1
        played[b] = played.get(b, 0) + 1

    if n == 0:
        return {"tour": tour, "n": 0}
    return {"tour": tour, "n": n, "log_loss": round(ll / n, 4), "brier": round(brier / n, 4),
            "accuracy": round(correct / n, 4), "baseline_accuracy": round(base_correct / n, 4)}


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
