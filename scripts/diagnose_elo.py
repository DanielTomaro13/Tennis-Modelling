"""Does a results-based Elo (independent of the serve/return data) sharpen the
extreme mismatches? Walk-forward Elo + blend sweep (prob vs logit space).

  python -m scripts.diagnose_elo
"""
from __future__ import annotations

import csv
import math
import os

from src import features, ratings, sim, util


def _scope(prof, surface):
    s = prof.get(surface) or prof.get("overall")
    return {**s, "name": prof["name"]}


def collect(cfg, tour):
    cutoff = int(cfg["backtest"]["holdout_start_year"]) * 10000
    profiles = features.build_profiles(cfg, tour, max_date=cutoff)
    league, players = profiles["league"], profiles["players"]
    e = cfg["elo"]; init = e["initial"]; sw = e["surface_weight"]
    overall, surface, played = {}, {}, {}

    path = util.abspath(os.path.join(cfg["data"]["processed_dir"], f"results-{tour}.csv"))
    rows = list(csv.DictReader(open(path, newline="")))
    rows.sort(key=lambda r: int(r.get("date") or 0))

    preds = []  # (sim_p, elo_p, both_seen)
    for r in rows:
        w, l, surf = r["winner"], r["loser"], r.get("surface", "Hard")
        surface.setdefault(surf, {})
        if int(r.get("date") or 0) >= cutoff and w in players and l in players:
            ra = sw * surface[surf].get(w, init) + (1 - sw) * overall.get(w, init)
            rb = sw * surface[surf].get(l, init) + (1 - sw) * overall.get(l, init)
            elo_p = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
            sa, sb = _scope(players[w], surf), _scope(players[l], surf)
            sim_p = sim.project_match(sa, sb, league, best_of=3)["sr_win_a"]
            seen = min(played.get(w, 0), played.get(l, 0)) >= 10  # both have Elo history
            preds.append((sim_p, elo_p, seen))
        # update Elo
        ow, ol = overall.get(w, init), overall.get(l, init)
        sw_, sl_ = surface[surf].get(w, init), surface[surf].get(l, init)
        rw, rl = sw * sw_ + (1 - sw) * ow, sw * sl_ + (1 - sw) * ol
        exp = 1.0 / (1.0 + 10 ** ((rl - rw) / 400.0))
        kw, kl = ratings._k_factor(cfg, played.get(w, 0), 3), ratings._k_factor(cfg, played.get(l, 0), 3)
        overall[w], overall[l] = ow + kw * (1 - exp), ol - kl * (1 - exp)
        surface[surf][w], surface[surf][l] = sw_ + kw * (1 - exp), sl_ - kl * (1 - exp)
        played[w] = played.get(w, 0) + 1
        played[l] = played.get(l, 0) + 1
    return preds


def _logit(p): p = min(max(p, 1e-9), 1 - 1e-9); return math.log(p / (1 - p))
def _sig(z): return 1 / (1 + math.exp(-z))


def blend(sim_p, elo_p, w, space):
    if space == "prob":
        return (1 - w) * sim_p + w * elo_p
    return _sig((1 - w) * _logit(sim_p) + w * _logit(elo_p))


def metrics(preds, w, space):
    ll = br = acc = 0.0
    for sim_p, elo_p, _ in preds:
        p = min(max(blend(sim_p, elo_p, w, space), 1e-6), 1 - 1e-6)
        ll += -math.log(p); br += (1 - p) ** 2; acc += 1 if p > 0.5 else 0
    n = len(preds)
    return ll / n, br / n, acc / n


def calib(preds, w, space, bins=10):
    bk = [[0, 0.0, 0] for _ in range(bins)]
    for sim_p, elo_p, _ in preds:
        p = blend(sim_p, elo_p, w, space)
        for pred, out in ((p, 1), (1 - p, 0)):
            b = min(bins - 1, int(pred * bins))
            bk[b][0] += 1; bk[b][1] += pred; bk[b][2] += out
    tot = sum(b[0] for b in bk); ece = 0.0; rows = []
    for i, (c, sp, so) in enumerate(bk):
        if not c:
            continue
        ece += c / tot * abs(sp / c - so / c)
        rows.append((f"{i*10:>3}-{i*10+10}%", c, sp / c, so / c))
    return rows, ece


def main():
    cfg = util.load_config()
    for tour in cfg["tours"]:
        preds = collect(cfg, tour)
        print(f"\n{'='*64}\n{tour.upper()} — {len(preds)} holdout matches\n{'='*64}")
        for space in ("prob", "logit"):
            print(f"\n  {space}-space blend (w on Elo):  w   log-loss  brier   ECE")
            best = (0, 9)
            for w10 in range(0, 11):
                w = w10 / 10
                ll, br, _ = metrics(preds, w, space)
                _, ece = calib(preds, w, space)
                if ll < best[1]:
                    best = (w, ll)
                print(f"                                {w:.1f}  {ll:.4f}  {br:.4f}  {ece:.4f}")
            print(f"    -> best Elo weight ({space}): {best[0]}  (log-loss {best[1]:.4f})")
        # show calibration of the better option's extreme bins
        rows, ece = calib(preds, best[0], "logit")
        print(f"\n  calibration @ logit blend w={best[0]} (ECE={ece:.4f}):")
        for label, c, pred, actual in rows:
            print(f"    {label:8} n={c:4} pred {pred:.3f}  actual {actual:.3f}  gap {actual-pred:+.3f}")


if __name__ == "__main__":
    main()
