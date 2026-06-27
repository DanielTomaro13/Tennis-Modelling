"""Odds stage — bookmaker match-winner prices vs the model's fair price.

Five books, each wrapped so one failing never breaks the rest:

  * Sportsbet, Ladbrokes — public, plain urllib (no auth)
  * PointsBet, TAB, Dabble — Cloudflare-fronted, need curl_cffi; TAB uses OAuth
    client creds, Dabble a captured bearer token (env / ~/sports-bots/secrets.env)

Australian books geo-restrict to AU IPs, so this is meant to run from a local
(AU) cron — see scripts/odds-cron.sh. From a non-AU CI runner it simply returns
nothing and the site degrades to model prices. Each fixture is matched to a book
event by player name (orientation-aware). Output: ``docs/data/odds.json`` and,
when Dabble auth is present, ``docs/data/pickem-lines.json``.
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


# --------------------------------------------------------------------------- #
# HTTP + matching helpers
# --------------------------------------------------------------------------- #
def _get(url: str, headers: dict = UA, retries: int = 2, timeout: int = 30):
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.6 * (i + 1))
    return None


def _cffi():
    try:
        from curl_cffi import requests as creq
        return creq
    except Exception:  # noqa: BLE001
        return None


def _cget(url: str, headers: dict, impersonate: str = "chrome", timeout: int = 25):
    creq = _cffi()
    if creq is None:
        return None
    try:
        r = creq.get(url, headers=headers, impersonate=impersonate, timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
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


def players_match(fp1: str, fp2: str, b1: str, b2: str) -> int | None:
    """+1 if book order matches fixture (b1~p1), -1 if swapped, else None."""
    f1, f2, s1, s2 = norm(fp1), norm(fp2), surname(fp1), surname(fp2)
    n1, n2, sn1, sn2 = norm(b1), norm(b2), surname(b1), surname(b2)

    def same(fa, sa, na, sna):
        return fa == na or (len(sa) >= 4 and sa == sna)

    if same(f1, s1, n1, sn1) and same(f2, s2, n2, sn2):
        return 1
    if same(f1, s1, n2, sn2) and same(f2, s2, n1, sn1):
        return -1
    return None


def _two_way(h2h: dict, fp1: str, fp2: str):
    """Map a {name: price} pair to (price_p1, price_p2) for the fixture order."""
    if not h2h or len(h2h) != 2:
        return None, None
    names = list(h2h)
    o = players_match(fp1, fp2, names[0], names[1])
    if o == 1:
        return h2h[names[0]], h2h[names[1]]
    if o == -1:
        return h2h[names[1]], h2h[names[0]]
    return None, None


# --------------------------------------------------------------------------- #
# Sportsbet (urllib)
# --------------------------------------------------------------------------- #
SB = "https://www.sportsbet.com.au/apigw"


def sb_events():
    comps = _get(f"{SB}/sportsbook-sports/Sportsbook/Sports/13/Competitions") or []
    out = []
    for c in comps:
        d = _get(f"{SB}/sportsbook-sports/Sportsbook/Sports/Competitions/{c.get('id')}"
                 "?displayType=default&eventFilter=matches")
        for e in (d or {}).get("events", []):
            if e.get("participant1") and e.get("participant2"):
                out.append({"id": e["id"], "p1": e["participant1"], "p2": e["participant2"]})
    return out


def sb_h2h(ev):
    d = _get(f"{SB}/sportsbook-sports/Sportsbook/Sports/Events/{ev['id']}/Markets")
    if not isinstance(d, list):
        return None
    for m in d:
        if (m.get("name") or "").lower() in ("match betting", "head to head", "moneyline"):
            sels = m.get("selections", [])
            if len(sels) == 2:
                return {s["name"]: (s.get("price") or {}).get("winPrice") for s in sels}
    return None


# --------------------------------------------------------------------------- #
# Ladbrokes / Entain (urllib)
# --------------------------------------------------------------------------- #
LAD = "https://api.ladbrokes.com.au"
LAD_HDR = {"User-Agent": "Mozilla/5.0", "Origin": "https://www.ladbrokes.com.au",
           "Referer": "https://www.ladbrokes.com.au/"}
LAD_TENNIS = "a0b910b8-85f0-4f6e-821d-c9fd9e3bdf93"


def lad_events():
    q = urllib.parse.quote(json.dumps([LAD_TENNIS]))
    d = _get(f"{LAD}/v2/sport/event-request?category_ids={q}", LAD_HDR)
    out = []
    for eid, e in ((d or {}).get("events", {}) or {}).items():
        nm = e.get("name", "")
        for sep in (" vs ", " v "):
            if sep in nm:
                a, b = nm.split(sep, 1)
                out.append({"id": eid, "p1": a.strip(), "p2": b.strip()})
                break
    return out


def lad_h2h(ev):
    d = _get(f"{LAD}/v2/sport/event-card?id={ev['id']}", LAD_HDR)
    if not d:
        return None
    prices = d.get("prices", {})

    def price(ent_id):
        for k, v in prices.items():
            if k.startswith(ent_id + ":"):
                odds = (v or {}).get("odds") or {}
                return round(float(odds["decimal"]), 2) if "decimal" in odds else _decimal(
                    odds.get("numerator"), odds.get("denominator"))
        return None

    by_market = {}
    for ent in d.get("entrants", {}).values():
        by_market.setdefault(ent.get("market_id"), []).append(ent)
    for ents in by_market.values():
        if len(ents) == 2 and players_match(ev["p1"], ev["p2"], ents[0].get("name", ""), ents[1].get("name", "")) is not None:
            return {ents[0].get("name", ""): price(ents[0]["id"]), ents[1].get("name", ""): price(ents[1]["id"])}
    return None


# --------------------------------------------------------------------------- #
# PointsBet (curl_cffi, no auth)
# --------------------------------------------------------------------------- #
PB = "https://api.au.pointsbet.com/api/mes/v3"
PB_V2 = "https://api.au.pointsbet.com/api/v2"
PB_HDR = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Origin": "https://pointsbet.com.au"}


def pb_events():
    d = _cget(f"{PB_V2}/sports/list/", PB_HDR)
    if not d:
        return []
    sports = d.get("sports", d) if isinstance(d, dict) else d
    keys = []
    for s in sports:
        if str(s.get("name", "")).strip().lower() == "tennis":
            keys += [c.get("key") for c in s.get("competitions", []) if c.get("key")]
    out = []
    for key in keys:
        feat = _cget(f"{PB}/events/featured/competition/{key}", PB_HDR)
        for ev in (feat.get("events", []) if isinstance(feat, dict) else feat) or []:
            eid = ev.get("key") or ev.get("eventId") or ev.get("id")
            if ev.get("homeTeam") and ev.get("awayTeam"):
                out.append({"id": eid, "p1": ev["homeTeam"], "p2": ev["awayTeam"]})
    return out


def pb_h2h(ev):
    det = _cget(f"{PB}/events/{ev['id']}", PB_HDR)
    if not det:
        return None
    for m in (det.get("fixedOddsMarkets") or det.get("markets") or []):
        if (m.get("name") or "").lower().startswith("match result") or (m.get("name") or "").lower().startswith("head to head"):
            outs = m.get("outcomes") or []
            if len(outs) == 2:
                return {o.get("name", ""): o.get("price") for o in outs}
    return None


# --------------------------------------------------------------------------- #
# TAB (curl_cffi, OAuth client creds)
# --------------------------------------------------------------------------- #
TAB = "https://api.beta.tab.com.au/v1/tab-info-service"
TAB_TOKEN_URL = "https://api.beta.tab.com.au/oauth/token"


def _tab_token():
    cid, csec = os.environ.get("TAB_CLIENT_ID", "").strip(), os.environ.get("TAB_CLIENT_SECRET", "").strip()
    creq = _cffi()
    if cid and csec and creq:
        try:
            r = creq.post(TAB_TOKEN_URL, data={"grant_type": "client_credentials", "client_id": cid, "client_secret": csec},
                          headers={"Accept": "application/json"}, impersonate="chrome", timeout=15)
            if r.status_code == 200 and r.json().get("access_token"):
                return r.json()["access_token"]
        except Exception:  # noqa: BLE001
            pass
    return os.environ.get("TAB_ACCESS_TOKEN", "").strip() or None


def tab_events():
    tok = _tab_token()
    if not tok:
        return []
    hdr = {"Authorization": f"Bearer {tok}", "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    lst = _cget(f"{TAB}/sports/Tennis/competitions?jurisdiction=VIC&homeState=VIC", hdr)
    comps = [c.get("name") for c in (lst or {}).get("competitions", []) if c.get("name")]
    out = []
    for comp in comps:
        d = _cget(f"{TAB}/sports/Tennis/competitions/{urllib.parse.quote(comp)}?jurisdiction=VIC&homeState=VIC", hdr)
        for m in (d or {}).get("matches", []):
            cons = m.get("contestants") or []
            if len(cons) != 2:
                continue
            p1, p2 = cons[0].get("name"), cons[1].get("name")
            h2h = None
            for mk in m.get("markets", []):
                if (mk.get("betOption") or "").strip().lower() in ("head to head", "match betting", "h2h"):
                    props = mk.get("propositions", [])
                    if len(props) == 2:
                        h2h = {pp.get("name", ""): pp.get("returnWin") for pp in props}
            if p1 and p2 and h2h:
                out.append({"id": m.get("id"), "p1": p1, "p2": p2, "h2h": h2h})
    return out


# --------------------------------------------------------------------------- #
# Dabble (curl_cffi + captured bearer; also supplies Pick'em lines)
# --------------------------------------------------------------------------- #
DAB = "https://api.dabble.com.au"


def _dab_headers():
    h = {"accept": "application/json",
         "x-device-id": os.environ.get("DABBLE_DEVICE_ID", "00000000-0000-0000-0000-000000000000"),
         "user-agent": os.environ.get("DABBLE_UA", "Dabble/1000041710 CFNetwork/3826.600.41.2.1 Darwin/24.6.0"),
         "x-app-version": os.environ.get("DABBLE_APP_VERSION", "4.17.10+019ededb"),
         "accept-language": "en-AU,en;q=0.9"}
    auth = os.environ.get("DABBLE_AUTH", "").strip()
    if auth:
        h["authorization"] = auth if auth.lower().startswith("bearer ") else "Bearer " + auth
    if os.environ.get("DABBLE_COOKIE", "").strip():
        h["cookie"] = os.environ["DABBLE_COOKIE"].strip()
    return h


def _dab_get(path):
    creq = _cffi()
    if creq is None:
        return None
    try:
        r = creq.get(DAB + path, headers=_dab_headers(), impersonate="safari_ios", timeout=25)
        return r.json() if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None


def _dab_tennis_comps():
    d = _dab_get("/competitions")
    comps = (d.get("data", d) if isinstance(d, dict) else d) or []
    return [c for c in comps if "tennis" in str(c.get("sportName", "")).lower()]


# pickem lines captured for the Pick'em page (model vs Dabble line)
_PICKEM_LINES = []


def dab_events():
    comps = _dab_tennis_comps()
    out = []
    for comp in comps:
        fx = _dab_get(f"/frontend-api/competitions/{comp['id']}/sport-fixtures?includeInPlay=false&exclude%5B%5D=none")
        for f in (fx.get("data", fx) if isinstance(fx, dict) else fx) or []:
            fid = f.get("id")
            if not fid:
                continue
            detail = _dab_get(f"/frontend-api/sport-fixtures/details/{fid}")
            if not detail:
                continue
            sfd = detail.get("sportFixtureDetail") or detail.get("data", {}).get("sportFixtureDetail") or {}
            name = f.get("name", sfd.get("name", ""))
            p1 = p2 = None
            if " v " in name:
                p1, p2 = [x.strip() for x in name.split(" v ", 1)]
            if not p1:
                continue
            # head-to-head market
            sel_name = {s["id"]: s.get("name", "") for s in sfd.get("selections", [])}
            price_by_mkt = {}
            for p in sfd.get("prices", []):
                price_by_mkt.setdefault(p.get("marketId"), []).append((sel_name.get(p.get("selectionId")), p.get("price")))
            h2h = None
            for m in sfd.get("markets", []):
                if (m.get("name") or "").strip().lower() in ("head to head", "match", "match winner", "moneyline"):
                    outs = [(nm, pr) for nm, pr in price_by_mkt.get(m.get("id"), []) if nm and pr]
                    if len(outs) == 2:
                        h2h = {nm: pr for nm, pr in outs}
            if h2h:
                out.append({"id": fid, "p1": p1, "p2": p2, "h2h": h2h})
            # Pick'em player-prop lines (over/under value), for the Pick'em page
            for pp in sfd.get("playerProps", []):
                if pp.get("value") is None or not pp.get("playerName"):
                    continue
                _PICKEM_LINES.append({
                    "event": name, "player": pp.get("playerName"),
                    "stat": " ".join(str(s) for s in (pp.get("stats") or [])),
                    "line": float(pp["value"]), "type": pp.get("lineType")})
    return out


# --------------------------------------------------------------------------- #
# Assemble
# --------------------------------------------------------------------------- #
BOOKS = {
    "sportsbet": (sb_events, sb_h2h),
    "ladbrokes": (lad_events, lad_h2h),
    "pointsbet": (pb_events, pb_h2h),
    "tab": (tab_events, lambda ev: ev.get("h2h")),
    "dabble": (dab_events, lambda ev: ev.get("h2h")),
}


def run(cfg: dict) -> None:
    preds = util.read_json(util.abspath(os.path.join(cfg["paths"]["docs_data_dir"], "predictions.json")))
    fixtures = [f for f in preds.get("fixtures", []) if f.get("format") != "doubles"]

    # enumerate each book's events (best-effort)
    book_events = {}
    for name, (lister, _) in BOOKS.items():
        evs = _safe(lister) or []
        book_events[name] = evs
        util.log(f"  [{name}] {len(evs)} events")

    books_present, out_matches = set(), []
    for f in fixtures:
        entry = {k: f[k] for k in ("tour", "date", "tournament", "round", "surface", "player1",
                                   "player2", "win_prob_1", "win_prob_2", "fair_odds_1", "fair_odds_2")}
        entry["books"] = {}
        for name, (_, h2h_fn) in BOOKS.items():
            ev = _find(book_events[name], f)
            if not ev:
                continue
            p1, p2 = _two_way(_safe(h2h_fn, ev) or {}, f["player1"], f["player2"])
            if p1 or p2:
                entry["books"][name] = {"p1": p1, "p2": p2}
                books_present.add(name)
        if not entry["books"]:
            continue
        _attach_value(entry)
        out_matches.append(entry)

    util.write_json(util.abspath(os.path.join(cfg["paths"]["docs_data_dir"], "odds.json")), {
        "generated": _now(), "books": sorted(books_present), "count": len(out_matches), "matches": out_matches,
    })
    util.log(f"odds: {len(out_matches)} matches priced across {sorted(books_present)}")

    if _PICKEM_LINES:
        util.write_json(util.abspath(os.path.join(cfg["paths"]["docs_data_dir"], "pickem-lines.json")),
                        {"generated": _now(), "lines": _PICKEM_LINES})
        util.log(f"odds: {len(_PICKEM_LINES)} Dabble pick'em lines captured")


def _find(events, fix):
    for e in events:
        if players_match(fix["player1"], fix["player2"], e["p1"], e["p2"]) is not None:
            return e
    return None


def _attach_value(entry):
    for side, prob in (("p1", entry["win_prob_1"]), ("p2", entry["win_prob_2"])):
        best_price, best_book = None, None
        for book, px in entry["books"].items():
            pr = px.get(side)
            if pr and (best_price is None or pr > best_price):
                best_price, best_book = pr, book
        entry.setdefault("best", {})[side] = {"price": best_price, "book": best_book}
        entry.setdefault("ev", {})[side] = round(prob * best_price - 1, 4) if best_price else None


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as exc:  # noqa: BLE001
        util.log(f"  [odds] {getattr(fn, '__name__', fn)} failed: {exc}")
        return None


def _now():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main(argv):
    run(util.load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
