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
    n_singles = n_doubles = 0
    for event in data.get("events", []):
        tournament = event.get("name", "")
        surface = infer_surface(tournament)
        for grouping in event.get("groupings", []):
            disc = (grouping.get("grouping") or {}).get("displayName", "")
            is_singles, is_doubles = "Singles" in disc, "Doubles" in disc
            if (not is_singles and not is_doubles) or "Mixed" in disc:
                continue
            tour = "atp" if disc.startswith("Men") else "wta" if disc.startswith("Women") else None
            if tour not in cfg["tours"]:
                continue
            for comp in grouping.get("competitions", []):
                status = (comp.get("status") or {}).get("type", {}).get("name", "")
                if status not in ("STATUS_SCHEDULED", "STATUS_PRE"):
                    continue
                date = (comp.get("date") or "")[:10].replace("-", "")
                if cutoff and date and date > cutoff:
                    continue
                rnd = comp.get("round") or {}
                rnd = rnd.get("displayName", "") if isinstance(rnd, dict) else str(rnd)
                base = {
                    "tour": tour, "date": date, "tournament": tournament, "surface": surface,
                    "round": rnd, "source": "espn",
                    "best_of": 5 if is_grand_slam(tournament) and tour == "atp" and is_singles else 3,
                }
                competitors = comp.get("competitors", [])
                if is_singles:
                    names = [(c.get("athlete") or {}).get("displayName", "") for c in competitors]
                    names = [n for n in names if n]
                    if len(names) != 2 or "TBD" in names or any("/" in n for n in names):
                        continue
                    fixtures.append({**base, "format": "singles",
                                     "player1": names[0], "player2": names[1]})
                    n_singles += 1
                else:
                    teams = [[a.get("displayName", "") for a in (c.get("roster") or {}).get("athletes", [])]
                             for c in competitors]
                    if len(teams) != 2 or any(len(t) != 2 or not all(t) or "TBD" in t for t in teams):
                        continue
                    fixtures.append({**base, "format": "doubles",
                                     "player1": " / ".join(teams[0]), "player2": " / ".join(teams[1]),
                                     "p1a": teams[0][0], "p1b": teams[0][1],
                                     "p2a": teams[1][0], "p2b": teams[1][1]})
                    n_doubles += 1
    util.log(f"scrape: ESPN parsed {n_singles} singles + {n_doubles} doubles fixtures")
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
            "surface": infer_surface(tournament), "best_of": best_of, "format": "singles",
            "round": rnd, "player1": home, "player2": away, "source": "tennis.com",
        })
    util.log(f"scrape: tennis.com parsed {len(fixtures)} scheduled singles fixtures")
    return fixtures


def _grab(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1) if m else None


def _dedup_key(f: dict) -> tuple:
    # Same players within the short scheduling window == same match, even if the
    # two sources disagree on exact date/tournament label or player order.
    if f.get("format") == "doubles":
        names = tuple(sorted(x.lower() for x in (f["p1a"], f["p1b"], f["p2a"], f["p2b"])))
    else:
        names = tuple(sorted((f["player1"].lower(), f["player2"].lower())))
    return (f["tour"], f.get("format", "singles"), names)


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
    cols = ["tour", "date", "tournament", "surface", "best_of", "format", "round",
            "player1", "player2", "p1a", "p1b", "p2a", "p2b", "source"]
    util.ensure_dir(util.abspath("data"))
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, restval="", extrasaction="ignore")
        w.writeheader()
        w.writerows(fixtures)
    util.log(f"scrape: wrote {out} ({len(fixtures)} unique fixtures)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
