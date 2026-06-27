"""Player stats stage — build per-player profiles, records and match history.

Joins derived results (``results-{tour}.csv``) with match metadata and the
serve/return profiles to produce ``docs/data/players.json`` for the player
pages: surface splits, win/loss record, and recent results.
"""
from __future__ import annotations

import collections
import csv
import os
import sys

from . import ingest, util


def _read_results(cfg: dict, tour: str) -> list[dict]:
    path = util.abspath(os.path.join(cfg["data"]["processed_dir"], f"results-{tour}.csv"))
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def build_tour(cfg: dict, tour: str, profiles_tour: dict, ranks: dict) -> dict:
    matches = ingest.load_matches(cfg, tour)
    results = _read_results(cfg, tour)

    history = collections.defaultdict(list)
    record = collections.defaultdict(collections.Counter)  # (player, scope) -> {W,L}
    for r in results:
        try:
            date = int(r.get("date") or 0)
        except ValueError:
            date = 0
        w, l, surf = r["winner"], r["loser"], r.get("surface", "Hard")
        meta = matches.get(r["match_id"], {})
        tournament, rnd = meta.get("tournament", ""), meta.get("round", "")
        history[w].append({"date": date, "opp": l, "result": "W", "surface": surf, "tournament": tournament, "round": rnd})
        history[l].append({"date": date, "opp": w, "result": "L", "surface": surf, "tournament": tournament, "round": rnd})
        for who, res in ((w, "W"), (l, "L")):
            record[(who, "overall")][res] += 1
            if surf in ("Hard", "Clay", "Grass"):
                record[(who, surf)][res] += 1

    out = {}
    for name, prof in profiles_tour["players"].items():
        recent = sorted(history.get(name, []), key=lambda x: -x["date"])[:25]
        rec = {scope: [record[(name, scope)]["W"], record[(name, scope)]["L"]]
               for scope in ("overall", "Hard", "Clay", "Grass")}
        out[name] = {
            "name": name,
            "tour": tour,
            "rank": ranks.get(name),
            "profile": {k: prof[k] for k in ("overall", "Hard", "Clay", "Grass") if k in prof},
            "record": rec,
            "recent": recent,
        }
    return out


def run(cfg: dict) -> None:
    models = cfg["paths"]["models_dir"]
    profiles = util.read_json(util.abspath(os.path.join(models, "profiles.json")))
    ratings_path = util.abspath(os.path.join(models, "ratings.json"))
    boards = util.read_json(ratings_path) if os.path.exists(ratings_path) else {}

    docs_data = cfg["paths"]["docs_data_dir"]
    index = {}
    for tour in cfg["tours"]:
        ranks = {row["name"]: row["rank"] for row in boards.get(tour, {}).get("overall", [])}
        data = build_tour(cfg, tour, profiles[tour], ranks)
        util.write_json(util.abspath(os.path.join(docs_data, f"players-{tour}.json")), data)
        # lightweight index for search/links: name -> rank
        index[tour] = sorted(({"name": n, "rank": p["rank"]} for n, p in data.items()),
                             key=lambda x: (x["rank"] is None, x["rank"]))
        util.log(f"players: {tour}: {len(data)} player profiles")
    util.write_json(util.abspath(os.path.join(docs_data, "players-index.json")), index)


def main(argv: list[str]) -> int:
    run(util.load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
