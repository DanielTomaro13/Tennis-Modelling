"""Feature stage — per-player, per-surface serve/return profiles.

From the Match Charting Project ``Overview`` aggregates we estimate, for each
player and surface, an additive serve/return model:

    P(server wins a point) = league_spw + serve_adv[server] - return_adv[returner]

``serve_adv`` / ``return_adv`` are found by iterative opponent adjustment,
recency-weighted (exponential decay) and shrunk toward zero for small samples.
Ace / double-fault / serve-split rates are recency-weighted, shrunk means.

Output: ``models/profiles.json`` consumed by ratings / sim / the site.
"""
from __future__ import annotations

import sys

from . import ingest, util

SURFACES = ("Hard", "Clay", "Grass")


def _f(row: dict, key: str) -> float:
    try:
        return float(row.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _recency_weight(date: int, ref: int, half_life_days: float) -> float:
    """0.5 ** (age_in_days / half_life). Dates are YYYYMMDD ints."""
    age = max(0.0, _days_between(date, ref))
    return 0.5 ** (age / half_life_days)


def _days_between(d0: int, d1: int) -> float:
    import datetime as _dt

    def to_date(d: int):
        d = int(d)
        try:
            return _dt.date(d // 10000, (d // 100) % 100, d % 100)
        except ValueError:
            return _dt.date(d // 10000, 1, 1)

    return (to_date(d1) - to_date(d0)).days


def build_performances(cfg: dict, tour: str, max_date: int | None = None) -> tuple[list[dict], int]:
    """One record per (player, match) with serve counts + opponent identity.

    ``max_date`` (YYYYMMDD) excludes matches on/after the cutoff — used for
    leakage-safe backtesting.
    """
    matches = ingest.load_matches(cfg, tour)
    if max_date is not None:
        matches = {k: v for k, v in matches.items() if v["date"] and v["date"] < max_date}
    # group overview Total rows by match
    by_match: dict[str, list[dict]] = {}
    for row in ingest.iter_overview(cfg, tour):
        mid = (row.get("match_id") or "").strip()
        if mid in matches:
            by_match.setdefault(mid, []).append(row)

    ref = max((m["date"] for m in matches.values() if m["date"]), default=20260101)
    half = float(cfg["features"]["half_life_days"])
    recs: list[dict] = []
    for mid, rows in by_match.items():
        if len(rows) != 2:
            continue
        meta = matches[mid]
        w = _recency_weight(meta["date"] or ref, ref, half)
        a, b = rows
        for me, opp in ((a, b), (b, a)):
            sp = _f(me, "serve_pts")
            rp = _f(me, "return_pts")
            if sp < 1 or rp < 1:
                continue
            recs.append({
                "player": (me.get("player") or "").strip(),
                "opp": (opp.get("player") or "").strip(),
                "surface": meta["surface"],
                "date": meta["date"],
                "w": w,
                "serve_pts": sp,
                "return_pts": rp,
                "spw_obs": (_f(me, "first_won") + _f(me, "second_won")) / sp,
                "rpw_obs": _f(me, "return_pts_won") / rp,
                "ace_rate": _f(me, "aces") / sp,
                "df_rate": _f(me, "dfs") / sp,
                "first_in": _f(me, "first_in") / sp,
                "first_win": _f(me, "first_won") / max(1.0, _f(me, "first_in")),
                "second_win": _f(me, "second_won") / max(1.0, sp - _f(me, "first_in")),
            })
    return recs, ref


def _weighted_mean(pairs: list[tuple[float, float]], prior_mean: float, prior_w: float) -> float:
    """pairs = [(weight, value)]; shrink toward prior_mean with prior_w."""
    num = prior_mean * prior_w
    den = prior_w
    for w, v in pairs:
        num += w * v
        den += w
    return num / den if den else prior_mean


def adjust(records: list[dict], spw_avg: float, prior_pts: float, iterations: int) -> tuple[dict, dict]:
    """Iterative additive opponent adjustment -> serve_adv, return_adv per player."""
    rpw_avg = 1.0 - spw_avg
    players = {r["player"] for r in records} | {r["opp"] for r in records}
    serve_adv = {p: 0.0 for p in players}
    return_adv = {p: 0.0 for p in players}
    # weight per record blends recency weight and sample size
    for r in records:
        r["_ws"] = r["w"] * r["serve_pts"]
        r["_wr"] = r["w"] * r["return_pts"]

    for _ in range(iterations):
        s_pairs: dict[str, list] = {}
        r_pairs: dict[str, list] = {}
        for r in records:
            # server residual, crediting opponent's return strength
            exp_spw = spw_avg - return_adv.get(r["opp"], 0.0)
            s_pairs.setdefault(r["player"], []).append((r["_ws"], r["spw_obs"] - exp_spw))
            # returner residual, crediting opponent's serve strength
            exp_rpw = rpw_avg - serve_adv.get(r["opp"], 0.0)
            r_pairs.setdefault(r["player"], []).append((r["_wr"], r["rpw_obs"] - exp_rpw))
        serve_adv = {p: _weighted_mean(s_pairs.get(p, []), 0.0, prior_pts) for p in players}
        return_adv = {p: _weighted_mean(r_pairs.get(p, []), 0.0, prior_pts) for p in players}
    return serve_adv, return_adv


def _rate_means(records: list[dict], keys: tuple[str, ...], prior_pts: float) -> dict[str, dict]:
    """Recency+sample weighted, shrunk-to-league rate per player for each key."""
    league = {}
    for k in keys:
        num = sum(r["w"] * r["serve_pts"] * r[k] for r in records)
        den = sum(r["w"] * r["serve_pts"] for r in records)
        league[k] = num / den if den else 0.0
    by_player: dict[str, dict] = {}
    grouped: dict[str, list] = {}
    for r in records:
        grouped.setdefault(r["player"], []).append(r)
    for p, rs in grouped.items():
        out = {}
        for k in keys:
            out[k] = _weighted_mean([(r["w"] * r["serve_pts"], r[k]) for r in rs], league[k], prior_pts)
        by_player[p] = out
    return by_player, league


def build_profiles(cfg: dict, tour: str, max_date: int | None = None) -> dict:
    recs, ref = build_performances(cfg, tour, max_date=max_date)
    prior = float(cfg["features"]["prior_svpt"])
    iters = int(cfg["features"]["adjust_iterations"])
    min_sp = float(cfg["features"]["min_svpt"])
    rate_keys = ("ace_rate", "df_rate", "first_in", "first_win", "second_win")

    spw_avg = (sum(r["w"] * r["serve_pts"] * r["spw_obs"] for r in recs)
               / max(1e-9, sum(r["w"] * r["serve_pts"] for r in recs)))

    scopes = {"overall": recs}
    for surf in SURFACES:
        scopes[surf] = [r for r in recs if r["surface"] == surf]

    # adjustments + rate means per scope
    adv = {}
    rates = {}
    for name, rs in scopes.items():
        adv[name] = adjust([dict(r) for r in rs], spw_avg, prior, iters) if rs else ({}, {})
        rates[name] = _rate_means(rs, rate_keys, prior) if rs else ({}, {})

    # serve-point totals per player per scope (for sample reporting + surface shrink)
    sp_total = {name: {} for name in scopes}
    for name, rs in scopes.items():
        for r in rs:
            sp_total[name][r["player"]] = sp_total[name].get(r["player"], 0.0) + r["w"] * r["serve_pts"]

    players = sorted({r["player"] for r in recs})
    rpw_avg = 1.0 - spw_avg
    profiles: dict[str, dict] = {}
    for p in players:
        if sp_total["overall"].get(p, 0.0) < min_sp:
            continue
        prof = {"name": p}
        for name in ("overall",) + SURFACES:
            sadv = adv[name][0].get(p)
            if name != "overall" and (sadv is None or sp_total[name].get(p, 0) < min_sp):
                # too little surface data -> lean on overall via shrink toward overall adv
                base_s = adv["overall"][0].get(p, 0.0)
                base_r = adv["overall"][1].get(p, 0.0)
                sw = sp_total[name].get(p, 0.0)
                surf_s = adv[name][0].get(p, 0.0)
                surf_r = adv[name][1].get(p, 0.0)
                k = sw / (sw + prior)
                s_adv = k * surf_s + (1 - k) * base_s
                r_adv = k * surf_r + (1 - k) * base_r
                pr = rates[name][0].get(p) or rates["overall"][0].get(p, {})
            else:
                s_adv = adv[name][0].get(p, 0.0)
                r_adv = adv[name][1].get(p, 0.0)
                pr = rates[name][0].get(p) or rates["overall"][0].get(p, {})

            spw = _clamp(spw_avg + s_adv, 0.40, 0.90)
            rpw = _clamp(rpw_avg + r_adv, 0.10, 0.60)
            prof[name] = {
                "spw": round(spw, 4),
                "rpw": round(rpw, 4),
                "ace_rate": round(pr.get("ace_rate", 0.06), 4),
                "df_rate": round(pr.get("df_rate", 0.04), 4),
                "first_in": round(pr.get("first_in", 0.60), 4),
                "first_win": round(pr.get("first_win", 0.72), 4),
                "second_win": round(pr.get("second_win", 0.50), 4),
                "serve_pts": round(sp_total[name].get(p, 0.0), 1),
                # dominance rating: points won above an average opponent, per point
                "pr": round((spw + rpw - 1.0) * 1000.0, 1),
            }
        profiles[p] = prof

    return {
        "tour": tour,
        "league": {"spw": round(spw_avg, 4), "rpw": round(rpw_avg, 4)},
        "n_players": len(profiles),
        "players": profiles,
    }


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def main(argv: list[str]) -> int:
    cfg = util.load_config()
    out_dir = util.abspath(cfg["paths"]["models_dir"])
    combined = {}
    for tour in cfg["tours"]:
        util.log(f"features: building {tour} profiles")
        data = build_profiles(cfg, tour)
        util.write_json(util.abspath(f"{out_dir}/profiles-{tour}.json"), data)
        combined[tour] = data
        util.log(f"features: {tour}: {data['n_players']} players, league spw={data['league']['spw']}")
    util.write_json(util.abspath(f"{out_dir}/profiles.json"), combined)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
