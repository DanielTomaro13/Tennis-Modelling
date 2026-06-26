"""Predict stage — full market projection for every resolved fixture.

For each fixture, blend the Markov sim win prob with the rating/Elo anchor and
attach all derived markets. Writes ``reports/predictions.csv`` and
``docs/data/predictions.json`` for the site.
"""
from __future__ import annotations

import csv
import os
import sys

from . import evaluate, fixtures as fixmod, ratings, sim, util


def _scope(prof: dict, surface: str) -> dict:
    s = prof.get(surface) or prof.get("overall")
    out = dict(s)
    out["name"] = prof["name"]
    return out


def project_fixture(cfg: dict, fx: dict, profiles_tour: dict, elo=None) -> dict:
    league = profiles_tour["league"]
    pa = profiles_tour["players"][fx["player1"]]
    pb = profiles_tour["players"][fx["player2"]]
    sa, sb = _scope(pa, fx["surface"]), _scope(pb, fx["surface"])

    markets = sim.project_match(sa, sb, league, best_of=fx["best_of"],
                                totals_lines=cfg["sim"]["totals_lines"])
    win_a = evaluate.blended_win_prob(cfg, pa, pb, league, fx["surface"], fx["best_of"], elo=elo)
    win_b = 1 - win_a

    def fair(p): return round(1.0 / p, 2) if p > 1e-6 else None

    return {
        **{k: fx[k] for k in ("tour", "date", "tournament", "surface", "best_of", "round",
                              "player1", "player2", "source")},
        "win_prob_1": round(win_a, 4),
        "win_prob_2": round(win_b, 4),
        "fair_odds_1": fair(win_a),
        "fair_odds_2": fair(win_b),
        "pr_1": sa["pr"],
        "pr_2": sb["pr"],
        "hold_1": markets["hold_a"],
        "hold_2": markets["hold_b"],
        "exp_total_games": markets["exp_total_games"],
        "tiebreak_prob": markets["tiebreak_prob"],
        "set_score": markets["set_score"],
        "totals": markets["totals"],
        "exp_aces_1": markets["exp_aces_a"],
        "exp_aces_2": markets["exp_aces_b"],
        "exp_df_1": markets["exp_df_a"],
        "exp_df_2": markets["exp_df_b"],
        # full market detail for the click-through view (a->player1, b->player2)
        "markets": markets,
    }


def run(cfg: dict) -> list[dict]:
    models = cfg["paths"]["models_dir"]
    profiles = util.read_json(util.abspath(os.path.join(models, "profiles.json")))
    fixtures = fixmod.load_fixtures(cfg, profiles)
    elos = {}
    for tour in cfg["tours"]:
        path = util.abspath(os.path.join(models, f"elo-{tour}.json"))
        elos[tour] = util.read_json(path) if os.path.exists(path) else None

    preds = []
    for fx in fixtures:
        try:
            preds.append(project_fixture(cfg, fx, profiles[fx["tour"]], elo=elos.get(fx["tour"])))
        except KeyError as exc:  # player missing from profiles
            util.log(f"predict: skipping {fx['player1']} vs {fx['player2']} ({exc})")
    preds.sort(key=lambda p: (p["date"], p["tour"], -max(p["win_prob_1"], p["win_prob_2"])))
    return preds


def main(argv: list[str]) -> int:
    cfg = util.load_config()
    preds = run(cfg)
    # CSV (flat) for reports
    reports = util.ensure_dir(util.abspath(cfg["paths"]["reports_dir"]))
    flat_cols = ["tour", "date", "tournament", "surface", "round", "player1", "player2",
                 "win_prob_1", "win_prob_2", "fair_odds_1", "fair_odds_2",
                 "exp_total_games", "tiebreak_prob", "exp_aces_1", "exp_aces_2",
                 "exp_df_1", "exp_df_2", "source"]
    with open(util.abspath(f"{reports}/predictions.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=flat_cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(preds)
    util.write_json(util.abspath(os.path.join(cfg["paths"]["docs_data_dir"], "predictions.json")),
                    {"generated": _today(), "count": len(preds), "fixtures": preds})
    util.log(f"predict: wrote {len(preds)} predictions")
    for p in preds[:12]:
        util.log(f"  {p['tour']} {p['surface'][:4]:4s} {p['player1']} {p['win_prob_1']:.0%} v "
                 f"{p['win_prob_2']:.0%} {p['player2']}  ETG {p['exp_total_games']}")
    return 0


def _today() -> str:
    import datetime
    return datetime.date.today().isoformat()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
