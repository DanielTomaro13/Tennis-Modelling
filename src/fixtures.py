"""Fixtures stage — merge scraped + manual fixtures and resolve player names.

Scraped/manual names are fuzzy-matched (accent-insensitive) to the names used
in the serve/return profiles so downstream prediction can look players up.
"""
from __future__ import annotations

import csv
import os
import sys
import unicodedata
from difflib import SequenceMatcher

from . import util


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _norm(s: str) -> str:
    return _strip_accents((s or "").lower()).replace(".", " ").replace("-", " ").strip()


def build_index(profiles_tour: dict) -> dict[str, str]:
    """normalized name -> canonical profile name."""
    return {_norm(name): name for name in profiles_tour["players"]}


def resolve_name(raw: str, index: dict[str, str], threshold: float) -> str | None:
    key = _norm(raw)
    if key in index:
        return index[key]
    parts = key.split()
    # Some feeds give Asian names surname-first ("Wu Yibing", "Zheng Qinwen")
    # while the profiles store them given-first ("Yibing Wu", "Qinwen Zheng").
    # Try the swapped two-token order as an exact match before fuzzy scoring.
    if len(parts) == 2 and f"{parts[1]} {parts[0]}" in index:
        return index[f"{parts[1]} {parts[0]}"]
    surname = parts[-1] if parts else key
    best, best_score = None, 0.0
    for nkey, canon in index.items():
        score = SequenceMatcher(None, key, nkey).ratio()
        nparts = nkey.split()
        nsurname = nparts[-1] if nparts else nkey
        # Boost ONLY when surnames are very close — sharing a common first name
        # (e.g. "Petra") must not validate a wrong surname match.
        if SequenceMatcher(None, surname, nsurname).ratio() >= 0.9:
            score = max(score, 0.85 + 0.15 * score)
        if score > best_score:
            best, best_score = canon, score
    return best if best_score >= threshold else None


def load_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_fixtures(cfg: dict, profiles: dict) -> list[dict]:
    """Return resolved fixtures with canonical player names + matched flags."""
    rows = load_csv(util.abspath("data/fixtures.csv")) + load_csv(util.abspath(cfg["fixtures"]["manual_file"]))
    threshold = float(cfg["fixtures"]["match_threshold"])
    indexes = {tour: build_index(profiles[tour]) for tour in profiles}

    resolved: list[dict] = []
    seen = set()
    skipped = 0
    for r in rows:
        tour = (r.get("tour") or "").lower()
        if tour not in profiles:
            continue
        idx = indexes[tour]
        common = {
            "tour": tour,
            "date": r.get("date", ""),
            "tournament": r.get("tournament", ""),
            "surface": (r.get("surface") or "Hard").capitalize(),
            "best_of": int(r.get("best_of") or 3),
            "round": r.get("round", ""),
            "source": r.get("source", ""),
        }
        if (r.get("format") or "singles") == "doubles":
            team = [resolve_name(r.get(k, ""), idx, threshold) for k in ("p1a", "p1b", "p2a", "p2b")]
            if not all(team) or len(set(team)) < 4:
                skipped += 1
                continue
            key = (tour, "doubles", tuple(sorted(team)))
            if key in seen:
                continue
            seen.add(key)
            resolved.append({**common, "format": "doubles",
                             "player1": f"{team[0]} / {team[1]}", "player2": f"{team[2]} / {team[3]}",
                             "team1": [team[0], team[1]], "team2": [team[2], team[3]]})
        else:
            p1 = resolve_name(r.get("player1", ""), idx, threshold)
            p2 = resolve_name(r.get("player2", ""), idx, threshold)
            if not p1 or not p2 or p1 == p2:
                skipped += 1
                continue
            key = (tour, "singles", tuple(sorted((p1, p2))))
            if key in seen:
                continue
            seen.add(key)
            resolved.append({**common, "format": "singles", "player1": p1, "player2": p2})
    util.log(f"fixtures: resolved {len(resolved)} fixtures ({skipped} unmatched/dropped)")
    return resolved


def main(argv: list[str]) -> int:
    cfg = util.load_config()
    profiles = util.read_json(util.abspath(os.path.join(cfg["paths"]["models_dir"], "profiles.json")))
    fixtures = load_fixtures(cfg, profiles)
    for f in fixtures[:20]:
        print(f"  {f['tour']} {f['surface']:5s} {f['player1']} vs {f['player2']}  ({f['tournament']} {f['round']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
