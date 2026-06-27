"""Odds stage — fetch bookmaker match-winner prices and value vs the model.

Pulls head-to-head (match-winner) prices for upcoming singles matches and lines
them up against the model's fair price. Two books work with no credentials:

  * Sportsbet  — public apigw (tennis class 13)
  * Ladbrokes  — public Entain REST (tennis category)

PointsBet, Dabble and TAB need extra creds (curl_cffi / captured token / OAuth)
and are added opportunistically when env vars are present; each book is wrapped
so one failing never breaks the others. Australian books geo-restrict to AU IPs,
so this may return nothing from a non-AU CI runner — the site degrades to model
prices only. Output: ``docs/data/odds.json``.

Run:  python -m src.odds
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

from . import util

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _get(url: str, headers: dict, retries: int = 3, timeout: int = 40):
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.8 * (i + 1))
    util.log(f"  [odds] give up {url[:70]} ({last})")
    return None


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


def surname(s: str) -> str:
    parts = (s or "").strip().split()
    return norm(parts[-1]) if parts else ""


def _decimal(num, den):
    try:
        return round(1 + float(num) / float(den), 2)
    except Exception:  # noqa: BLE001
        return None


def players_match(fix_p1: str, fix_p2: str, b1: str, b2: str) -> int | None:
    """Return +1 if book order matches fixture (b1~p1), -1 if swapped, else None."""
    f1, f2 = norm(fix_p1), norm(fix_p2)
    s1, s2 = surname(fix_p1), surname(fix_p2)
    n1, n2 = norm(b1), norm(b2)
    sn1, sn2 = surname(b1), surname(b2)

    def same(fa, sa, na, sna):
        return fa == na or (sa and sa == sna and len(sa) >= 4)

    if same(f1, s1, n1, sn1) and same(f2, s2, n2, sn2):
        return 1
    if same(f1, s1, n2, sn2) and same(f2, s2, n1, sn1):
        return -1
    return None


# --------------------------------------------------------------------------- #
# Sportsbet
# --------------------------------------------------------------------------- #
SB = "https://www.sportsbet.com.au/apigw"
SB_TENNIS_CLASS = 13


def sportsbet_events() -> list[dict]:
    comps = _get(f"{SB}/sportsbook-sports/Sportsbook/Sports/{SB_TENNIS_CLASS}/Competitions", UA) or []
    out = []
    for c in comps:
        cid, cname = c.get("id"), c.get("name", "")
        d = _get(f"{SB}/sportsbook-sports/Sportsbook/Sports/Competitions/{cid}"
                 "?displayType=default&eventFilter=matches", UA)
        for e in (d or {}).get("events", []):
            p1, p2 = e.get("participant1"), e.get("participant2")
            if p1 and p2:
                out.append({"eventId": e["id"], "p1": p1, "p2": p2, "competition": cname})
    util.log(f"  [sportsbet] {len(out)} singles/doubles events across {len(comps)} comps")
    return out


def sportsbet_h2h(event_id: int) -> dict | None:
    d = _get(f"{SB}/sportsbook-sports/Sportsbook/Sports/Events/{event_id}/Markets", UA)
    if not isinstance(d, list):
        return None
    for m in d:
        if (m.get("name") or "").lower() in ("match betting", "head to head", "moneyline"):
            sels = m.get("selections", [])
            if len(sels) == 2:
                return {sels[0]["name"]: (sels[0].get("price") or {}).get("winPrice"),
                        sels[1]["name"]: (sels[1].get("price") or {}).get("winPrice")}
    return None


# --------------------------------------------------------------------------- #
# Ladbrokes (Entain)
# --------------------------------------------------------------------------- #
LAD = "https://api.ladbrokes.com.au"
LAD_HDR = {"User-Agent": "Mozilla/5.0", "Origin": "https://www.ladbrokes.com.au",
           "Referer": "https://www.ladbrokes.com.au/"}
LAD_TENNIS_CAT = "a0b910b8-85f0-4f6e-821d-c9fd9e3bdf93"


def ladbrokes_events() -> list[dict]:
    q = urllib.parse.quote(json.dumps([LAD_TENNIS_CAT]))
    d = _get(f"{LAD}/v2/sport/event-request?category_ids={q}", LAD_HDR)
    out = []
    for eid, e in ((d or {}).get("events", {}) or {}).items():
        nm = e.get("name", "")
        for sep in (" vs ", " v "):
            if sep in nm:
                p1, p2 = nm.split(sep, 1)
                out.append({"eventId": eid, "p1": p1.strip(), "p2": p2.strip()})
                break
    util.log(f"  [ladbrokes] {len(out)} tennis h2h events")
    return out


def ladbrokes_h2h(event_id: str, p1: str, p2: str) -> dict | None:
    d = _get(f"{LAD}/v2/sport/event-card?id={event_id}", LAD_HDR)
    if not d:
        return None
    entrants = d.get("entrants", {})
    prices = d.get("prices", {})

    def price_for(ent_id):
        for k, v in prices.items():
            if k.startswith(ent_id + ":"):
                odds = (v or {}).get("odds") or {}
                return round(float(odds["decimal"]), 2) if "decimal" in odds else _decimal(
                    odds.get("numerator"), odds.get("denominator"))
        return None

    # the match-winner market is the 2-entrant market matching the two players
    by_market = {}
    for ent in entrants.values():
        by_market.setdefault(ent.get("market_id"), []).append(ent)
    for ents in by_market.values():
        if len(ents) != 2:
            continue
        names = [e.get("name", "") for e in ents]
        if players_match(p1, p2, names[0], names[1]) is not None:
            return {names[0]: price_for(ents[0]["id"]), names[1]: price_for(ents[1]["id"])}
    return None


# --------------------------------------------------------------------------- #
# Assemble
# --------------------------------------------------------------------------- #
def _book_price(h2h: dict, fix_p1: str, fix_p2: str):
    """Map a {name:price} h2h to (price_for_p1, price_for_p2)."""
    if not h2h:
        return None, None
    names = list(h2h.keys())
    if len(names) != 2:
        return None, None
    o = players_match(fix_p1, fix_p2, names[0], names[1])
    if o == 1:
        return h2h[names[0]], h2h[names[1]]
    if o == -1:
        return h2h[names[1]], h2h[names[0]]
    return None, None


def run(cfg: dict) -> None:
    preds = util.read_json(util.abspath(os.path.join(cfg["paths"]["docs_data_dir"], "predictions.json")))
    fixtures = [f for f in preds.get("fixtures", []) if f.get("format") != "doubles"]

    # gather book events (each wrapped so a failure is non-fatal)
    sb_events = _safe(sportsbet_events)
    lad_events = _safe(ladbrokes_events)

    books_present = set()
    out_matches = []
    for f in fixtures:
        entry = {k: f[k] for k in ("tour", "date", "tournament", "round", "surface",
                                   "player1", "player2", "win_prob_1", "win_prob_2",
                                   "fair_odds_1", "fair_odds_2")}
        entry["books"] = {}

        # Sportsbet
        sb = _find_event(sb_events, f)
        if sb:
            p1, p2 = _book_price(_safe(sportsbet_h2h, sb["eventId"]) or {}, f["player1"], f["player2"])
            if p1 or p2:
                entry["books"]["sportsbet"] = {"p1": p1, "p2": p2}
                books_present.add("sportsbet")

        # Ladbrokes
        lad = _find_event(lad_events, f)
        if lad:
            p1, p2 = _book_price(_safe(ladbrokes_h2h, lad["eventId"], lad["p1"], lad["p2"]) or {},
                                 f["player1"], f["player2"])
            if p1 or p2:
                entry["books"]["ladbrokes"] = {"p1": p1, "p2": p2}
                books_present.add("ladbrokes")

        if not entry["books"]:
            continue
        _attach_value(entry)
        out_matches.append(entry)

    out = {
        "generated": _now(),
        "books": sorted(books_present),
        "count": len(out_matches),
        "matches": out_matches,
    }
    util.write_json(util.abspath(os.path.join(cfg["paths"]["docs_data_dir"], "odds.json")), out)
    util.log(f"odds: {len(out_matches)} matches priced across {sorted(books_present)}")


def _find_event(events: list[dict], fix: dict):
    for e in events:
        if players_match(fix["player1"], fix["player2"], e["p1"], e["p2"]) is not None:
            return e
    return None


def _attach_value(entry: dict) -> None:
    """Best price per side + model EV (model_prob * best_price - 1)."""
    for side, prob in (("p1", entry["win_prob_1"]), ("p2", entry["win_prob_2"])):
        best_price, best_book = None, None
        for book, px in entry["books"].items():
            pr = px.get(side)
            if pr and (best_price is None or pr > best_price):
                best_price, best_book = pr, book
        entry.setdefault("best", {})[side] = {"price": best_price, "book": best_book}
        ev = round(prob * best_price - 1, 4) if best_price else None
        entry.setdefault("ev", {})[side] = ev


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001
        util.log(f"  [odds] {getattr(fn, '__name__', fn)} failed: {exc}")
        return None


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main(argv: list[str]) -> int:
    run(util.load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
