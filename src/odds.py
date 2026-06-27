"""Odds stage — model price vs the bookmakers, across as many markets as possible.

For every upcoming singles match we pull each book's full market board, map each
book's market/selection naming to a canonical model market, and price it with the
sim engine (so any book line — Over 19.5, +3.5 handicap, etc. — is priced exactly).

Markets covered: match winner, set betting, 1st/2nd set winner, total games O/U,
games handicap, set handicap. Dabble's Pick'em (a multiplier player-prop game) is
captured separately for the Pick'em page.

Books: Sportsbet + Ladbrokes (urllib, no auth); PointsBet + TAB + Dabble
(curl_cffi; TAB OAuth creds, Dabble bearer token). Each wrapped so one failing
never breaks the rest. Australian books geo-restrict to AU IPs — run from a local
AU cron (scripts/odds-cron.sh). Output: docs/data/odds.json (+ pickem-lines.json).
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

from . import sim, util

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
NUM = re.compile(r"([+-]?\d+(?:\.\d+)?)")
SCORE = re.compile(r"(\d)\s*-\s*(\d)")


# --------------------------------------------------------------------------- #
# HTTP + helpers
# --------------------------------------------------------------------------- #
def _get(url, headers=UA, retries=2, timeout=30):
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.5 * (i + 1))
    return None


def _cffi():
    try:
        from curl_cffi import requests as creq
        return creq
    except Exception:  # noqa: BLE001
        return None


def _cget(url, headers, impersonate="chrome", timeout=25):
    creq = _cffi()
    if creq is None:
        return None
    try:
        r = creq.get(url, headers=headers, impersonate=impersonate, timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None


def norm(s):
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def surname(s):
    p = (s or "").strip().split()
    return norm(p[-1]) if p else ""


def players_match(fp1, fp2, b1, b2):
    f1, f2, s1, s2 = norm(fp1), norm(fp2), surname(fp1), surname(fp2)
    n1, n2, sn1, sn2 = norm(b1), norm(b2), surname(b1), surname(b2)
    same = lambda fa, sa, na, sna: fa == na or (len(sa) >= 4 and sa == sna)
    if same(f1, s1, n1, sn1) and same(f2, s2, n2, sn2):
        return 1
    if same(f1, s1, n2, sn2) and same(f2, s2, n1, sn1):
        return -1
    return None


def _which(sel, fp1, fp2):
    n = norm(sel)
    s1, s2 = surname(fp1), surname(fp2)
    a, b = (len(s1) >= 3 and s1 in n), (len(s2) >= 3 and s2 in n)
    return 1 if (a and not b) else 2 if (b and not a) else None


# --------------------------------------------------------------------------- #
# Canonical market parsing — book market name + selections -> (sel_id, label)
# --------------------------------------------------------------------------- #
MARKET_LABEL = {"mw": "Match winner", "sb": "Set betting", "s1": "1st set winner",
                "s2": "2nd set winner", "tg": "Total games", "gh": "Games handicap",
                "sh": "Set handicap"}
MARKET_ORDER = ["mw", "sb", "s1", "s2", "tg", "gh", "sh"]


def parse_market(name, selections, fp1, fp2):
    """Yield (sel_id, sel_label) per priced selection. selections = [(name, price)]."""
    low = (name or "").lower()
    out = []

    def emit(sid, label, price):
        if price:
            out.append((sid, label, float(price)))

    if any(k in low for k in ("match result", "match betting", "head to head", "moneyline", "match winner")) \
            and "set" not in low:
        for sn, pr in selections:
            w = _which(sn, fp1, fp2)
            if w:
                emit(f"mw|{w}", fp1 if w == 1 else fp2, pr)
    elif "set betting" in low:
        for sn, pr in selections:
            w, m = _which(sn, fp1, fp2), SCORE.search(sn)
            if w and m:
                hi, lo = m.group(1), m.group(2)
                score = f"{hi}-{lo}" if w == 1 else f"{lo}-{hi}"
                emit(f"sb|{score}", f"{fp1 if w == 1 else fp2} {hi}-{lo}", pr)
    elif "1st set winner" in low or "first set winner" in low:
        for sn, pr in selections:
            w = _which(sn, fp1, fp2)
            if w:
                emit(f"s1|{w}", fp1 if w == 1 else fp2, pr)
    elif "2nd set winner" in low or "second set winner" in low:
        for sn, pr in selections:
            w = _which(sn, fp1, fp2)
            if w:
                emit(f"s2|{w}", fp1 if w == 1 else fp2, pr)
    elif low.startswith("total games") or low.split("(")[0].strip() == "total games":
        for sn, pr in selections:
            m = NUM.search(sn)
            side = "O" if "over" in sn.lower() else "U" if "under" in sn.lower() else None
            if side and m:
                line = abs(float(m.group(1)))
                emit(f"tg|{side}|{line}", f"{'Over' if side == 'O' else 'Under'} {line}", pr)
    elif "games handicap" in low:
        for sn, pr in selections:
            w, m = _which(sn, fp1, fp2), NUM.search(sn)
            if w and m:
                line = float(m.group(1))
                emit(f"gh|{w}|{line}", f"{fp1 if w == 1 else fp2} {line:+g}", pr)
    elif "set handicap" in low:
        for sn, pr in selections:
            w, m = _which(sn, fp1, fp2), NUM.search(sn)
            if w and m:
                line = float(m.group(1))
                emit(f"sh|{w}|{line}", f"{fp1 if w == 1 else fp2} {line:+g} sets", pr)
    return out


def model_price(sel_id, win1, win2, dist):
    """Model probability for a canonical selection id."""
    parts = sel_id.split("|")
    k = parts[0]
    if k == "mw":
        return win1 if parts[1] == "1" else win2
    if k == "sb":
        return dist["set_score"].get(parts[1], 0.0)
    if k == "s1":
        return dist["set1_win_a"] if parts[1] == "1" else 1 - dist["set1_win_a"]
    if k == "s2":
        return dist["set2_win_a"] if parts[1] == "1" else 1 - dist["set2_win_a"]
    if k == "tg":
        side, line = parts[1], float(parts[2])
        over = sum(p for g, p in dist["games_dist"].items() if g > line)
        return over if side == "O" else 1 - over
    if k == "gh":
        w, line = parts[1], float(parts[2])
        md = dist["margin_dist"]
        if w == "1":
            return sum(p for m, p in md.items() if m > -line)
        return sum(p for m, p in md.items() if m < line)
    if k == "sh":
        w, line = parts[1], float(parts[2])
        def smargin(key):
            a, b = key.split("-")
            return int(a) - int(b)
        ss = dist["set_score"]
        if w == "1":
            return sum(p for key, p in ss.items() if smargin(key) > -line)
        return sum(p for key, p in ss.items() if smargin(key) < line)
    return None


# --------------------------------------------------------------------------- #
# Books — each: list_events() -> [{id,p1,p2,(raw_markets)}]; markets(ev) -> [(name,[(sel,price)])]
# --------------------------------------------------------------------------- #
SB = "https://www.sportsbet.com.au/apigw"


def sb_events():
    comps = _get(f"{SB}/sportsbook-sports/Sportsbook/Sports/13/Competitions") or []
    out = []
    for c in comps:
        d = _get(f"{SB}/sportsbook-sports/Sportsbook/Sports/Competitions/{c.get('id')}?displayType=default&eventFilter=matches")
        for e in (d or {}).get("events", []):
            if e.get("participant1") and e.get("participant2"):
                out.append({"id": e["id"], "p1": e["participant1"], "p2": e["participant2"]})
    return out


def sb_markets(ev):
    d = _get(f"{SB}/sportsbook-sports/Sportsbook/Sports/Events/{ev['id']}/Markets")
    out = []
    for m in (d if isinstance(d, list) else []):
        out.append((m.get("name", ""), [(s.get("name", ""), (s.get("price") or {}).get("winPrice")) for s in m.get("selections", [])]))
    return out


LAD = "https://api.ladbrokes.com.au"
LAD_HDR = {"User-Agent": "Mozilla/5.0", "Origin": "https://www.ladbrokes.com.au", "Referer": "https://www.ladbrokes.com.au/"}
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


def lad_markets(ev):
    d = _get(f"{LAD}/v2/sport/event-card?id={ev['id']}", LAD_HDR)
    if not d:
        return []
    prices = d.get("prices", {})

    def price(ent_id):
        for kk, v in prices.items():
            if kk.startswith(ent_id + ":"):
                o = (v or {}).get("odds") or {}
                if "decimal" in o:
                    return round(float(o["decimal"]), 2)
                try:
                    return round(1 + float(o["numerator"]) / float(o["denominator"]), 2)
                except Exception:  # noqa: BLE001
                    return None
        return None

    by_market = {}
    for ent in d.get("entrants", {}).values():
        by_market.setdefault(ent.get("market_id"), []).append(ent)
    out = []
    for mid, ents in by_market.items():
        mname = (d.get("markets", {}).get(mid) or {}).get("name", "")
        out.append((mname, [(e.get("name", ""), price(e["id"])) for e in ents]))
    return out


PB = "https://api.au.pointsbet.com/api/mes/v3"
PB_V2 = "https://api.au.pointsbet.com/api/v2"
PB_HDR = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Origin": "https://pointsbet.com.au"}


def pb_events():
    d = _cget(f"{PB_V2}/sports/list/", PB_HDR)
    if not d:
        return []
    sports = d.get("sports", d) if isinstance(d, dict) else d
    keys = [c.get("key") for s in sports if str(s.get("name", "")).strip().lower() == "tennis"
            for c in s.get("competitions", []) if c.get("key")]
    out = []
    for key in keys:
        feat = _cget(f"{PB}/events/featured/competition/{key}", PB_HDR)
        for ev in (feat.get("events", []) if isinstance(feat, dict) else feat) or []:
            if ev.get("homeTeam") and ev.get("awayTeam"):
                out.append({"id": ev.get("key") or ev.get("eventId") or ev.get("id"), "p1": ev["homeTeam"], "p2": ev["awayTeam"]})
    return out


def pb_markets(ev):
    det = _cget(f"{PB}/events/{ev['id']}", PB_HDR)
    if not det:
        return []
    return [(m.get("name", ""), [(o.get("name", ""), o.get("price")) for o in (m.get("outcomes") or [])])
            for m in (det.get("fixedOddsMarkets") or det.get("markets") or [])]


TAB = "https://api.beta.tab.com.au/v1/tab-info-service"


def _tab_token():
    cid, csec = os.environ.get("TAB_CLIENT_ID", "").strip(), os.environ.get("TAB_CLIENT_SECRET", "").strip()
    creq = _cffi()
    if cid and csec and creq:
        try:
            r = creq.post("https://api.beta.tab.com.au/oauth/token",
                          data={"grant_type": "client_credentials", "client_id": cid, "client_secret": csec},
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
    out = []
    for comp in [c.get("name") for c in (lst or {}).get("competitions", []) if c.get("name")]:
        d = _cget(f"{TAB}/sports/Tennis/competitions/{urllib.parse.quote(comp)}?jurisdiction=VIC&homeState=VIC", hdr)
        for m in (d or {}).get("matches", []):
            cons = m.get("contestants") or []
            if len(cons) != 2:
                continue
            raw = [(mk.get("betOption", ""), [(pp.get("name", ""), pp.get("returnWin")) for pp in mk.get("propositions", [])])
                   for mk in m.get("markets", [])]
            out.append({"id": m.get("id"), "p1": cons[0].get("name"), "p2": cons[1].get("name"), "raw": raw})
    return out


DAB = "https://api.dabble.com.au"
_PICKEM = []


def _dab_headers():
    h = {"accept": "application/json",
         "x-device-id": os.environ.get("DABBLE_DEVICE_ID", "00000000-0000-0000-0000-000000000000"),
         "user-agent": os.environ.get("DABBLE_UA", "Dabble/1000041710 CFNetwork/3826.600.41.2.1 Darwin/24.6.0"),
         "x-app-version": os.environ.get("DABBLE_APP_VERSION", "4.17.10+019ededb"), "accept-language": "en-AU,en;q=0.9"}
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


def dab_events():
    d = _dab_get("/competitions")
    comps = [c for c in ((d.get("data", d) if isinstance(d, dict) else d) or []) if "tennis" in str(c.get("sportName", "")).lower()]
    out = []
    for comp in comps:
        fx = _dab_get(f"/frontend-api/competitions/{comp['id']}/sport-fixtures?includeInPlay=false&exclude%5B%5D=none")
        for f in (fx.get("data", fx) if isinstance(fx, dict) else fx) or []:
            fid = f.get("id")
            if not fid:
                continue
            detail = _dab_get(f"/frontend-api/sport-fixtures/details/{fid}")
            sfd = (detail or {}).get("sportFixtureDetail") or (detail or {}).get("data", {}).get("sportFixtureDetail") or {}
            name = f.get("name", sfd.get("name", ""))
            if " v " not in name:
                continue
            p1, p2 = [x.strip() for x in name.split(" v ", 1)]
            sel_name = {s["id"]: s.get("name", "") for s in sfd.get("selections", [])}
            by_mkt = {}
            for p in sfd.get("prices", []):
                by_mkt.setdefault(p.get("marketId"), []).append((sel_name.get(p.get("selectionId")), p.get("price")))
            raw = [(m.get("name", ""), by_mkt.get(m.get("id"), [])) for m in sfd.get("markets", [])]
            out.append({"id": fid, "p1": p1, "p2": p2, "raw": raw})
            for pp in sfd.get("playerProps", []):
                if pp.get("value") is not None and pp.get("playerName"):
                    _PICKEM.append({"event": name, "player": pp.get("playerName"),
                                    "stat": " ".join(str(s) for s in (pp.get("stats") or [])),
                                    "line": float(pp["value"]), "type": pp.get("lineType")})
    return out


BOOKS = {
    "sportsbet": (sb_events, sb_markets),
    "ladbrokes": (lad_events, lad_markets),
    "pointsbet": (pb_events, pb_markets),
    "tab": (tab_events, lambda ev: ev.get("raw", [])),
    "dabble": (dab_events, lambda ev: ev.get("raw", [])),
}


# --------------------------------------------------------------------------- #
def run(cfg):
    dd = cfg["paths"]["docs_data_dir"]
    preds = util.read_json(util.abspath(os.path.join(dd, "predictions.json")))
    profiles = util.read_json(util.abspath(os.path.join(cfg["paths"]["models_dir"], "profiles.json")))
    fixtures = [f for f in preds.get("fixtures", []) if f.get("format") != "doubles"]

    book_events = {}
    for name, (lister, _) in BOOKS.items():
        evs = _safe(lister) or []
        book_events[name] = evs
        util.log(f"  [{name}] {len(evs)} events")

    books_present, out_matches = set(), []
    for f in fixtures:
        prof = profiles.get(f["tour"], {}).get("players", {})
        if f["player1"] not in prof or f["player2"] not in prof:
            continue
        dist = sim.distributions(_scope(prof[f["player1"]], f["surface"]),
                                 _scope(prof[f["player2"]], f["surface"]),
                                 profiles[f["tour"]]["league"], best_of=f.get("best_of", 3))
        win1, win2 = f["win_prob_1"], f["win_prob_2"]

        # collect book prices per canonical selection
        sel_books, sel_label = {}, {}
        for book, (_, get_markets) in BOOKS.items():
            ev = _find(book_events[book], f)
            if not ev:
                continue
            for mname, sels in _safe(get_markets, ev) or []:
                for sid, label, price in parse_market(mname, sels, f["player1"], f["player2"]):
                    sel_books.setdefault(sid, {})[book] = round(price, 2)
                    sel_label[sid] = label
                    books_present.add(book)
        if not sel_books:
            continue

        # group by market, price with model, compute best + EV
        markets = {}
        for sid, books in sel_books.items():
            mp = model_price(sid, win1, win2, dist)
            if mp is None or mp <= 0:
                continue
            best_price = max(books.values())
            best_book = max(books, key=books.get)
            mk = sid.split("|")[0]
            markets.setdefault(mk, {"key": mk, "label": MARKET_LABEL[mk], "selections": []})
            markets[mk]["selections"].append({
                "id": sid, "label": sel_label[sid], "model": round(mp, 4), "fair": round(1 / mp, 2),
                "books": books, "best": {"price": best_price, "book": best_book},
                "ev": round(mp * best_price - 1, 4), "edge": round(mp - 1 / best_price, 4),
            })
        ordered = [markets[k] for k in MARKET_ORDER if k in markets]
        for m in ordered:
            m["selections"].sort(key=lambda s: s["id"])
        out_matches.append({**{k: f[k] for k in ("tour", "date", "tournament", "round", "surface", "player1", "player2")},
                            "markets": ordered})

    util.write_json(util.abspath(os.path.join(dd, "odds.json")),
                    {"generated": _now(), "books": sorted(books_present), "count": len(out_matches), "matches": out_matches})
    util.log(f"odds: {len(out_matches)} matches priced across {sorted(books_present)}")

    if _PICKEM:
        util.write_json(util.abspath(os.path.join(dd, "pickem-lines.json")), {"generated": _now(), "lines": _PICKEM})
        util.log(f"odds: {len(_PICKEM)} Dabble pick'em lines")


def _scope(prof, surface):
    s = prof.get(surface) or prof.get("overall")
    return {**s, "name": prof.get("name", "")}


def _find(events, fix):
    for e in events:
        if players_match(fix["player1"], fix["player2"], e["p1"], e["p2"]) is not None:
            return e
    return None


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
