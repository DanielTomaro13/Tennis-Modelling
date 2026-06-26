"""Schedule scraper — upcoming singles fixtures from ESPN + tennis.com.

ESPN's hidden JSON API (`site.api.espn.com`) is the primary source: one endpoint
lists both tours' draws with clean player names and round/date. tennis.com (whose
scoreboard is embedded as Next.js RSC JSON) is merged in as a secondary source.
Surface isn't in either feed, so it's inferred from the tournament name. Output:
``data/fixtures.csv``. ``data/manual_fixtures.csv`` is the guaranteed fallback.
"""
from __future__ import annotations

import csv
import datetime
import json
import re
import sys

from . import util

GRAND_SLAMS = ("wimbledon", "roland garros", "french open", "us open", "australian open")


def is_grand_slam(name: str) -> bool:
    n = (name or "").lower()
    return any(g in n for g in GRAND_SLAMS)

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


def scrape_espn(cfg: dict) -> list[dict]:
    """Primary source: ESPN tennis scoreboard JSON (both tours, full draws)."""
    url = cfg["fixtures"].get("espn_url")
    if not url:
        return []
    util.log(f"scrape: fetching ESPN {url}")
    try:
        data = json.loads(util.http_get(url, timeout=60))
    except Exception as exc:  # noqa: BLE001
        util.log(f"scrape: ESPN failed ({exc})")
        return []

    cutoff = _date_cutoff(cfg)
    fixtures: list[dict] = []
    for event in data.get("events", []):
        tournament = event.get("name", "")
        for grouping in event.get("groupings", []):
            disc = (grouping.get("grouping") or {}).get("displayName", "")
            if "Singles" not in disc:
                continue
            tour = "atp" if disc.startswith("Men") else "wta" if disc.startswith("Women") else None
            if tour not in cfg["tours"]:
                continue
            for comp in grouping.get("competitions", []):
                status = (comp.get("status") or {}).get("type", {}).get("name", "")
                if status not in ("STATUS_SCHEDULED", "STATUS_PRE"):
                    continue
                names = [(c.get("athlete") or {}).get("displayName", "") for c in comp.get("competitors", [])]
                names = [n for n in names if n]
                if len(names) != 2 or "TBD" in names or any("/" in n for n in names):
                    continue
                date = (comp.get("date") or "")[:10].replace("-", "")
                if cutoff and date and date > cutoff:
                    continue
                rnd = comp.get("round") or {}
                rnd = rnd.get("displayName", "") if isinstance(rnd, dict) else str(rnd)
                fixtures.append({
                    "tour": tour, "date": date, "tournament": tournament,
                    "surface": infer_surface(tournament),
                    "best_of": 5 if is_grand_slam(tournament) and tour == "atp" else 3,
                    "round": rnd, "player1": names[0], "player2": names[1], "source": "espn",
                })
    util.log(f"scrape: ESPN parsed {len(fixtures)} scheduled singles fixtures")
    return fixtures


def _date_cutoff(cfg: dict) -> str | None:
    days = cfg["fixtures"].get("days_ahead")
    if not days:
        return None
    return (datetime.date.today() + datetime.timedelta(days=int(days))).strftime("%Y%m%d")


def scrape_tenniscom(cfg: dict) -> list[dict]:
    url = cfg["fixtures"]["schedule_url"]
    util.log(f"scrape: fetching tennis.com {url}")
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
    util.log(f"scrape: tennis.com parsed {len(fixtures)} scheduled singles fixtures")
    return fixtures


def _grab(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1) if m else None


def _dedup_key(f: dict) -> tuple:
    # Same two players within the short scheduling window == same match, even if
    # the two sources disagree on exact date/tournament label or player order.
    pair = tuple(sorted((f["player1"].lower(), f["player2"].lower())))
    return (f["tour"], pair)


def scrape_all(cfg: dict) -> list[dict]:
    """Union of ESPN (primary) + tennis.com, de-duplicated."""
    fixtures, seen = [], set()
    for source in (scrape_espn(cfg), scrape_tenniscom(cfg)):
        for f in source:
            k = _dedup_key(f)
            if k in seen:
                continue
            seen.add(k)
            fixtures.append(f)
    return fixtures


def main(argv: list[str]) -> int:
    cfg = util.load_config()
    fixtures = scrape_all(cfg)
    out = util.abspath("data/fixtures.csv")
    cols = ["tour", "date", "tournament", "surface", "best_of", "round", "player1", "player2", "source"]
    util.ensure_dir(util.abspath("data"))
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(fixtures)
    util.log(f"scrape: wrote {out} ({len(fixtures)} unique fixtures)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
