"""Site stage — refresh the JSON artifacts the static ``docs/`` site reads.

The HTML/CSS/JS in ``docs/`` are committed static files. This stage copies the
latest model outputs into ``docs/data/`` and writes a small ``meta.json``
(generated date + backtest summary) so the site can show freshness + accuracy.
"""
from __future__ import annotations

import datetime
import os
import sys

from . import util


def _slim_profiles(profiles: dict) -> dict:
    """Trim profiles to what the in-browser predictor needs (keeps JSON small)."""
    out = {}
    for tour, data in profiles.items():
        players = {}
        for name, prof in data["players"].items():
            players[name] = {
                scope: {k: prof[scope][k] for k in
                        ("spw", "rpw", "ace_rate", "df_rate", "pr", "serve_pts")}
                for scope in ("overall", "Hard", "Clay", "Grass") if scope in prof
            }
        out[tour] = {"league": data["league"], "players": players}
    return out


def run(cfg: dict) -> None:
    models = cfg["paths"]["models_dir"]
    docs_data = util.ensure_dir(util.abspath(cfg["paths"]["docs_data_dir"]))

    profiles = util.read_json(util.abspath(os.path.join(models, "profiles.json")))
    util.write_json(util.abspath(os.path.join(docs_data, "profiles.json")), _slim_profiles(profiles))

    ratings_path = util.abspath(os.path.join(models, "ratings.json"))
    if os.path.exists(ratings_path):
        util.write_json(util.abspath(os.path.join(docs_data, "ratings.json")),
                        util.read_json(ratings_path))

    for tour in cfg["tours"]:
        elo = util.abspath(os.path.join(models, f"elo-{tour}.json"))
        if os.path.exists(elo):
            util.write_json(util.abspath(os.path.join(docs_data, f"elo-{tour}.json")),
                            util.read_json(elo))

    backtest = None
    bpath = util.abspath(os.path.join(cfg["paths"]["reports_dir"], "backtest.json"))
    if os.path.exists(bpath):
        backtest = util.read_json(bpath)

    meta = {
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "tours": cfg["tours"],
        "surfaces": cfg["surfaces"],
        "backtest": backtest,
        "n_players": {t: profiles[t]["n_players"] for t in cfg["tours"]},
    }
    util.write_json(util.abspath(os.path.join(docs_data, "meta.json")), meta)
    util.log(f"build_site: refreshed docs/data ({meta['generated']})")


def main(argv: list[str]) -> int:
    run(util.load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
