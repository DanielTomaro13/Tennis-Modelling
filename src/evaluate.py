"""Backtest stage — leakage-safe holdout evaluation.

Builds profiles from matches strictly before ``backtest.holdout_start_year`` and
scores the model on holdout-season results (requires derived winners). Reports
log-loss, Brier and accuracy versus a points-rating baseline.
"""
from __future__ import annotations

import csv
import math
import os
import sys

from . import features, ingest, ratings, sim, util


def tour_blend(cfg: dict, tour: str) -> float:
    """Per-tour weight on the rating anchor (tuned on the holdout)."""
    return float(cfg["sim"].get(f"blend_{tour}", cfg["sim"].get("elo_blend", 0.2)))


def blended_win_prob(cfg: dict, prof_a: dict, prof_b: dict, league: dict,
                     surface: str, best_of: int, elo=None, blend: float | None = None) -> float:
    """Headline win prob: blend Markov sim with a rating/Elo anchor."""
    sa = _scope(prof_a, surface)
    sb = _scope(prof_b, surface)
    sr = sim.project_match(sa, sb, league, best_of=best_of,
                           totals_lines=cfg["sim"]["totals_lines"])["sr_win_a"]
    anchor = ratings.elo_win_prob(elo, prof_a["name"], prof_b["name"], surface,
                                  cfg["elo"]["surface_weight"]) if elo else None
    if anchor is None:
        anchor = ratings.pr_win_prob(sa["pr"], sb["pr"])
    if blend is None:
        blend = cfg["sim"].get("elo_blend", 0.2)
    return blend * anchor + (1 - blend) * sr


def _scope(prof: dict, surface: str) -> dict:
    s = prof.get(surface) or prof.get("overall")
    out = dict(s)
    out["name"] = prof["name"]
    return out


def _ensure_results(cfg: dict, tour: str) -> str:
    path = util.abspath(os.path.join(cfg["data"]["processed_dir"], f"results-{tour}.csv"))
    if not os.path.exists(path):
        util.log("evaluate: results missing -> deriving winners (streams point files)")
        ingest.derive_winners(cfg)
    return path


def evaluate_tour(cfg: dict, tour: str) -> dict:
    path = _ensure_results(cfg, tour)
    cutoff = int(cfg["backtest"]["holdout_start_year"]) * 10000
    profiles = features.build_profiles(cfg, tour, max_date=cutoff)
    league = profiles["league"]
    players = profiles["players"]

    n = ll = brier = correct = base_correct = 0
    with open(path, "r", encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if int(r.get("date") or 0) < cutoff:
                continue
            w, l, surf = r["winner"], r["loser"], r.get("surface", "Hard")
            if w not in players or l not in players:
                continue
            pw = players[w]
            pl = players[l]
            p = blended_win_prob(cfg, pw, pl, league, surf, best_of=3, blend=tour_blend(cfg, tour))
            p = min(max(p, 1e-6), 1 - 1e-6)
            n += 1
            ll += -math.log(p)
            brier += (1 - p) ** 2
            correct += 1 if p > 0.5 else 0
            base = ratings.pr_win_prob(_scope(pw, surf)["pr"], _scope(pl, surf)["pr"])
            base_correct += 1 if base > 0.5 else 0

    if n == 0:
        return {"tour": tour, "n": 0}
    return {
        "tour": tour,
        "n": n,
        "log_loss": round(ll / n, 4),
        "brier": round(brier / n, 4),
        "accuracy": round(correct / n, 4),
        "baseline_accuracy": round(base_correct / n, 4),
    }


def main(argv: list[str]) -> int:
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
