"""Schedule scraper — upcoming singles fixtures from tennis.com.

tennis.com embeds its scoreboard as JSON inside Next.js RSC stream chunks.
We pull the homepage, unescape it, and regex out each scheduled singles match.
Surface isn't in the feed, so it's inferred from the tournament. Output:
``data/fixtures.csv``. This is best-effort; ``data/manual_fixtures.csv`` is the
guaranteed fallback merged downstream by ``fixtures.py``.
"""
from __future__ import annotations

import csv
import re
import sys

from . import util

# Tournament-name keyword -> surface. Default Hard.
SURFACE_HINTS = [
    ("wimbledon", "Grass"), ("eastbourne", "Grass"), ("mallorca", "Grass"),
    ("halle", "Grass"), ("queen", "Grass"), ("'s-hertogenbosch", "Grass"),
    ("bad homburg", "Grass"), ("newport", "Grass"), ("stuttgart", "Grass"),
    ("roland garros", "Clay"), ("french open", "Clay"), ("monte", "Clay"),
    ("madrid", "Clay"), ("rome", "Clay"), ("hamburg", "Clay"), ("kitzbuhel", "Clay"),
    ("bastad", "Clay"), ("gstaad", "Clay"), ("umag", "Clay"), ("piracicaba", "Clay"),
    ("brasil", "Clay"), ("plovdiv", "Clay"), ("targu", "Clay"), ("mure", "Clay"),
]


def infer_surface(tournament: str) -> str:
    t = (tournament or "").lower()
    for kw, surf in SURFACE_HINTS:
        if kw in t:
            return surf
    return "Hard"


def lastfirst_to_first_last(name: str) -> str:
    """'Soto, Matías' -> 'Matías Soto'. Pass through if no comma."""
    name = (name or "").strip()
    if "," in name:
        last, first = name.split(",", 1)
        return f"{first.strip()} {last.strip()}".strip()
    return name


def scrape(cfg: dict) -> list[dict]:
    url = cfg["fixtures"]["schedule_url"]
    util.log(f"scrape: fetching {url}")
    try:
        html = util.http_get(url, timeout=60).decode("utf-8", "replace").replace('\\"', '"')
    except Exception as exc:  # noqa: BLE001
        util.log(f"scrape: failed ({exc}); relying on manual fixtures")
        return []

    fixtures: list[dict] = []
    seen = set()
    for chunk in html.split('"id":"sr:sport_event:')[1:]:
        c = chunk[:2200]
        status = _grab(c, r'"status":"([^"]+)"')
        category = _grab(c, r'"eventCategory":"([^"]+)"')
        if status != "scheduled" or "Singles" not in (category or ""):
            continue
        home = lastfirst_to_first_last(_grab(c, r'"homeCompetitor":\{.*?"name":"([^"]+)"'))
        away = lastfirst_to_first_last(_grab(c, r'"awayCompetitor":\{.*?"name":"([^"]+)"'))
        if not home or not away or home == "TBD" or away == "TBD":
            continue
        gender = (_grab(c, r'"competitionGender":"([^"]+)"') or "").lower()
        tour = "atp" if gender == "men" else "wta" if gender == "women" else None
        if tour not in cfg["tours"]:
            continue
        tournament = _grab(c, r'"tournamentName":"([^"]+)"') or ""
        start = _grab(c, r'"startTime":"([^"T]+)"') or ""
        date = start.replace("-", "")
        level = _grab(c, r'"tournamentLevel":"([^"]+)"') or ""
        rnd = _grab(c, r'"round":"([^"]+)"') or ""
        best_of = 5 if level == "Grand Slam" and tour == "atp" else 3
        key = (tour, home, away, date)
        if key in seen:
            continue
        seen.add(key)
        fixtures.append({
            "tour": tour, "date": date, "tournament": tournament,
            "surface": infer_surface(tournament), "best_of": best_of,
            "round": rnd, "player1": home, "player2": away, "source": "tennis.com",
        })
    util.log(f"scrape: parsed {len(fixtures)} scheduled singles fixtures")
    return fixtures


def _grab(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1) if m else None


def main(argv: list[str]) -> int:
    cfg = util.load_config()
    fixtures = scrape(cfg)
    out = util.abspath("data/fixtures.csv")
    cols = ["tour", "date", "tournament", "surface", "best_of", "round", "player1", "player2", "source"]
    util.ensure_dir(util.abspath("data"))
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(fixtures)
    util.log(f"scrape: wrote {out} ({len(fixtures)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
