"""Ingest stage — download and cache the Match Charting Project data.

Pulls, per tour, the small ``matches`` metadata file and the per-match
``Overview`` serve/return aggregates. Optionally derives win/loss results by
streaming the (large) point-by-point files — opt-in, used for Elo + backtest.

Run:  python -m src.ingest            # matches + overview
      python -m src.ingest --winners  # also derive results.csv
"""
from __future__ import annotations

import csv
import io
import os
import sys

from . import util


def _raw_path(cfg: dict, name: str) -> str:
    return util.abspath(os.path.join(cfg["data"]["raw_dir"], name))


def download_core(cfg: dict) -> None:
    """Download matches + Overview CSVs for every configured tour."""
    util.ensure_dir(util.abspath(cfg["data"]["raw_dir"]))
    base = cfg["data"]["base_url"]
    for tour in cfg["tours"]:
        files = cfg["data"]["files"][tour]
        for key in ("matches", "overview"):
            name = files[key]
            dest = _raw_path(cfg, name)
            util.log(f"ingest: downloading {tour}/{key} -> {name}")
            data = util.http_get(f"{base}/{name}")
            with open(dest, "wb") as fh:
                fh.write(data)
            util.log(f"ingest: wrote {dest} ({len(data):,} bytes)")


def load_matches(cfg: dict, tour: str) -> dict[str, dict]:
    """Return {match_id: {players, surface, date, best_of, tournament, round}}."""
    path = _raw_path(cfg, cfg["data"]["files"][tour]["matches"])
    start = int(cfg["data"]["start_date"])
    out: dict[str, dict] = {}
    with open(path, "r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            mid = row.get("match_id", "").strip()
            if not mid:
                continue
            try:
                date = int((row.get("Date") or "0").strip() or 0)
            except ValueError:
                date = 0
            if date and date < start:
                continue
            out[mid] = {
                "match_id": mid,
                "tour": tour,
                "p1": (row.get("Player 1") or "").strip(),
                "p2": (row.get("Player 2") or "").strip(),
                "surface": normalize_surface(row.get("Surface")),
                "date": date,
                "best_of": _to_int(row.get("Best of"), 3),
                "tournament": (row.get("Tournament") or "").strip(),
                "round": (row.get("Round") or "").strip(),
            }
    return out


def iter_overview(cfg: dict, tour: str):
    """Yield per-player Total rows from the Overview stats file."""
    path = _raw_path(cfg, cfg["data"]["files"][tour]["overview"])
    with open(path, "r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if (row.get("set") or "").strip() != "Total":
                continue
            yield row


def derive_winners(cfg: dict) -> None:
    """Stream point-by-point files; cache {match_id -> winning player name}.

    The winner is the player holding more sets at the final point. The points
    schema names columns Set1/Set2 (sets won by Player1/Player2) and PtWinner.
    Player1 == the metadata file's "Player 1".
    """
    base = cfg["data"]["base_url"]
    proc = util.ensure_dir(util.abspath(cfg["data"]["processed_dir"]))
    for tour in cfg["tours"]:
        matches = load_matches(cfg, tour)
        # final (set1, set2) seen per match id
        final: dict[str, tuple[int, int]] = {}
        for fname in cfg["data"]["files"][tour]["points"]:
            url = f"{base}/{fname}"
            util.log(f"ingest: streaming {tour} points {fname}")
            header = None
            for line in util.http_stream_lines(url):
                if header is None:
                    header = next(csv.reader([line]))
                    idx = {h: i for i, h in enumerate(header)}
                    continue
                if not line:
                    continue
                try:
                    rec = next(csv.reader([line]))
                    mid = rec[idx["match_id"]]
                    if mid not in matches:
                        continue
                    s1 = int(rec[idx["Set1"]] or 0)
                    s2 = int(rec[idx["Set2"]] or 0)
                except (KeyError, IndexError, ValueError):
                    continue
                final[mid] = (s1, s2)
        out = util.abspath(os.path.join(proc, f"results-{tour}.csv"))
        n = 0
        with open(out, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["match_id", "winner", "loser", "surface", "date"])
            for mid, (s1, s2) in final.items():
                if s1 == s2:
                    continue
                m = matches[mid]
                winner, loser = (m["p1"], m["p2"]) if s1 > s2 else (m["p2"], m["p1"])
                w.writerow([mid, winner, loser, m["surface"], m["date"]])
                n += 1
        util.log(f"ingest: wrote {out} ({n} results)")


# --------------------------------------------------------------------------- #
def normalize_surface(value) -> str:
    s = (value or "").strip().lower()
    if s.startswith("hard"):
        return "Hard"
    if s.startswith("clay"):
        return "Clay"
    if s.startswith("grass"):
        return "Grass"
    if s.startswith("carpet"):
        return "Carpet"
    return "Hard"  # sensible default for the rare blank


def _to_int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def main(argv: list[str]) -> int:
    cfg = util.load_config()
    download_core(cfg)
    if "--winners" in argv or cfg["data"].get("derive_winners"):
        derive_winners(cfg)
    # quick sanity summary
    for tour in cfg["tours"]:
        matches = load_matches(cfg, tour)
        n_over = sum(1 for _ in iter_overview(cfg, tour))
        util.log(f"ingest: {tour}: {len(matches):,} matches (>= start_date), {n_over:,} overview rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
