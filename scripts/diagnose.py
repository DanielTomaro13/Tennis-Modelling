"""Model accuracy diagnostic — calibration + blend sweep on the holdout.

Not part of the pipeline; run ad hoc:  python -m scripts.diagnose
"""
from __future__ import annotations

import csv
import math
import os

from src import features, ratings, sim, util


def holdout_preds(cfg, tour):
    """Return list of (p_winner, sr, anchor, surf) for each holdout match."""
    cutoff = int(cfg["backtest"]["holdout_start_year"]) * 10000
    profiles = features.build_profiles(cfg, tour, max_date=cutoff)
    league, players = profiles["league"], profiles["players"]
    path = util.abspath(os.path.join(cfg["data"]["processed_dir"], f"results-{tour}.csv"))
    out = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            if int(r.get("date") or 0) < cutoff:
                continue
            w, l, surf = r["winner"], r["loser"], r.get("surface", "Hard")
            if w not in players or l not in players:
                continue
            sa = _scope(players[w], surf)
            sb = _scope(players[l], surf)
            sr = sim.project_match(sa, sb, league, best_of=3)["sr_win_a"]
            anchor = ratings.pr_win_prob(sa["pr"], sb["pr"])
            out.append((sr, anchor, surf))
    return out


def _scope(prof, surface):
    s = prof.get(surface) or prof.get("overall")
    return {**s, "name": prof["name"]}


def _sharpen(p, k):
    p = min(max(p, 1e-9), 1 - 1e-9)
    z = math.log(p / (1 - p)) * k
    return 1 / (1 + math.exp(-z))


def metrics(preds, blend, k=1.0):
    """preds = [(sr, anchor, surf)] for winner. Return log-loss, brier, acc."""
    ll = br = acc = 0.0
    n = len(preds)
    for sr, anchor, _ in preds:
        p = min(max(_sharpen(blend * anchor + (1 - blend) * sr, k), 1e-6), 1 - 1e-6)
        ll += -math.log(p)
        br += (1 - p) ** 2
        acc += 1 if p > 0.5 else 0
    return ll / n, br / n, acc / n


def calibration(preds, blend, k=1.0, bins=10):
    """Symmetric calibration: each match -> (p_win,1) and (p_lose,0)."""
    buckets = [[0, 0.0, 0] for _ in range(bins)]  # [count, sum_pred, sum_outcome]
    for sr, anchor, _ in preds:
        p = _sharpen(blend * anchor + (1 - blend) * sr, k)
        for pred, outcome in ((p, 1), (1 - p, 0)):
            b = min(bins - 1, int(pred * bins))
            buckets[b][0] += 1
            buckets[b][1] += pred
            buckets[b][2] += outcome
    rows = []
    ece = 0.0
    total = sum(b[0] for b in buckets)
    for i, (c, sp, so) in enumerate(buckets):
        if c == 0:
            continue
        avg_pred, actual = sp / c, so / c
        ece += c / total * abs(avg_pred - actual)
        rows.append((f"{i*10:>3}-{i*10+10}%", c, avg_pred, actual))
    return rows, ece


def main():
    cfg = util.load_config()
    for tour in cfg["tours"]:
        preds = holdout_preds(cfg, tour)
        print(f"\n{'='*60}\n{tour.upper()} — {len(preds)} holdout matches\n{'='*60}")

        # blend sweep
        print("blend  log-loss  brier   acc")
        best = (None, 9)
        for b10 in range(0, 11):
            b = b10 / 10
            ll, br, ac = metrics(preds, b)
            mark = ""
            if ll < best[1]:
                best = (b, ll)
            print(f" {b:.1f}   {ll:.4f}   {br:.4f}  {ac:.3f}")
        print(f"  -> best blend by log-loss: {best[0]} (current config: {cfg['sim'].get(f'blend_{tour}', 0.2)})")

        # at best blend, sweep sharpening k
        bb = best[0]
        print(f"\nsharpen sweep @ blend={bb}:  k   log-loss  ECE")
        bestk = (1.0, 9)
        for k10 in range(8, 23, 2):
            k = k10 / 10
            ll, _, _ = metrics(preds, bb, k)
            _, ece = calibration(preds, bb, k)
            if ll < bestk[1]:
                bestk = (k, ll)
            print(f"            {k:.1f}  {ll:.4f}  {ece:.4f}")
        print(f"  -> best (blend={bb}, k={bestk[0]})")

        # calibration at best blend + k
        rows, ece = calibration(preds, bb, bestk[0])
        print(f"\ncalibration @ blend={bb}, k={bestk[0]}  (ECE={ece:.4f})")
        print("  bin        n   pred   actual  gap")
        for label, c, pred, actual in rows:
            print(f"  {label:8} {c:4}  {pred:.3f}  {actual:.3f}  {actual-pred:+.3f}")


if __name__ == "__main__":
    main()
