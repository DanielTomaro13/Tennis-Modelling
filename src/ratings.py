"""Ratings stage — surface leaderboards and an optional Elo overlay.

Primary rating is the serve/return **Points Rating** (``pr``) from
``features.py``: points won above an average opponent, per 1000 points, per
surface. ``ratings.json`` holds sortable leaderboards for the site.

If win/loss results are available (``data.derive_winners``), a surface Elo is
also computed and blended into the headline win probability.
"""
from __future__ import annotations

import csv
import math
import os
import sys

from . import util

SCOPES = ("overall", "Hard", "Clay", "Grass")


def pr_win_prob(pr_a: float, pr_b: float, scale: float = 130.0) -> float:
    """Logistic win probability for A vs B from Points-Rating difference."""
    return 1.0 / (1.0 + math.exp(-(pr_a - pr_b) / scale))


def build_leaderboards(profiles: dict) -> dict:
    """profiles: combined {tour: {players: {...}}} -> {tour: {scope: [rows]}}."""
    out: dict[str, dict] = {}
    for tour, data in profiles.items():
        out[tour] = {}
        for scope in SCOPES:
            rows = []
            for name, prof in data["players"].items():
                s = prof.get(scope)
                if not s or s["serve_pts"] < 1:
                    continue
                rows.append({
                    "name": name,
                    "pr": s["pr"],
                    "spw": s["spw"],
                    "rpw": s["rpw"],
                    "ace_rate": s["ace_rate"],
                    "df_rate": s["df_rate"],
                    "serve_pts": s["serve_pts"],
                })
            rows.sort(key=lambda r: r["pr"], reverse=True)
            for i, r in enumerate(rows, 1):
                r["rank"] = i
            out[tour][scope] = rows
    return out


# --------------------------------------------------------------------------- #
# Optional Elo (requires derived results)
# --------------------------------------------------------------------------- #
def _k_factor(cfg: dict, n_played: int, best_of: int) -> float:
    e = cfg["elo"]
    k = e["k_base"] / ((n_played + e["k_offset"]) ** e["k_shape"])
    if best_of == 5:
        k *= e["k_best_of_5_mult"]
    return k


def compute_elo(cfg: dict, tour: str) -> dict | None:
    path = util.abspath(os.path.join(cfg["data"]["processed_dir"], f"results-{tour}.csv"))
    if not os.path.exists(path):
        return None
    e = cfg["elo"]
    init = e["initial"]
    surf_w = e["surface_weight"]
    regress = float(e.get("season_regression", 0.0))
    overall: dict[str, float] = {}
    surface: dict[str, dict[str, float]] = {s: {} for s in ("Hard", "Clay", "Grass", "Carpet")}
    played: dict[str, int] = {}
    last_season: dict[str, int] = {}

    rows = []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    rows.sort(key=lambda r: int(r.get("date") or 0))

    for r in rows:
        w, l = r["winner"], r["loser"]
        surf = r.get("surface", "Hard")
        best_of = int(r.get("best_of") or 3)
        season = int(r.get("date") or 0) // 10000
        if surf not in surface:
            surface[surf] = {}
        # start-of-season regression toward the mean (was configured but unused)
        for p in (w, l):
            prev = last_season.get(p)
            if prev is not None and season > prev and regress > 0:
                overall[p] = init + (1 - regress) * (overall.get(p, init) - init)
                for sd in surface.values():
                    if p in sd:
                        sd[p] = init + (1 - regress) * (sd[p] - init)
            last_season[p] = season
        ow, ol = overall.get(w, init), overall.get(l, init)
        sw_, sl_ = surface[surf].get(w, init), surface[surf].get(l, init)
        rw = surf_w * sw_ + (1 - surf_w) * ow
        rl = surf_w * sl_ + (1 - surf_w) * ol
        exp_w = 1.0 / (1.0 + 10 ** ((rl - rw) / 400.0))
        kw = _k_factor(cfg, played.get(w, 0), best_of)
        kl = _k_factor(cfg, played.get(l, 0), best_of)
        overall[w] = ow + kw * (1 - exp_w)
        overall[l] = ol - kl * (1 - exp_w)
        surface[surf][w] = sw_ + kw * (1 - exp_w)
        surface[surf][l] = sl_ - kl * (1 - exp_w)
        played[w] = played.get(w, 0) + 1
        played[l] = played.get(l, 0) + 1

    return {"overall": overall, "surface": surface, "played": played}


def elo_win_prob(elo: dict, a: str, b: str, surface: str, surf_w: float) -> float | None:
    if elo is None:
        return None
    init = 1500.0
    ra = surf_w * elo["surface"].get(surface, {}).get(a, init) + (1 - surf_w) * elo["overall"].get(a, init)
    rb = surf_w * elo["surface"].get(surface, {}).get(b, init) + (1 - surf_w) * elo["overall"].get(b, init)
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def main(argv: list[str]) -> int:
    cfg = util.load_config()
    models = util.abspath(cfg["paths"]["models_dir"])
    profiles = util.read_json(util.abspath(f"{models}/profiles.json"))
    boards = build_leaderboards(profiles)
    util.write_json(util.abspath(f"{models}/ratings.json"), boards)
    for tour in cfg["tours"]:
        n = len(boards.get(tour, {}).get("overall", []))
        util.log(f"ratings: {tour}: {n} ranked players")
        elo = compute_elo(cfg, tour)
        if elo is not None:
            util.write_json(util.abspath(f"{models}/elo-{tour}.json"), {
                "overall": elo["overall"], "surface": elo["surface"], "played": elo["played"],
            })
            util.log(f"ratings: {tour}: Elo computed for {len(elo['overall'])} players")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
