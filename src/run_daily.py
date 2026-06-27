"""Orchestrator — run the full pipeline end to end.

    python -m src.run_daily          # full daily build (winners + Elo + backtest)
    python -m src.run_daily --quick  # skip winner derivation + backtest (faster)

Stages: ingest -> features -> ratings -> (evaluate) -> scrape -> predict -> build_site.
"""
from __future__ import annotations

import sys
import time

from . import build_site, evaluate, features, ingest, players, predict, ratings, scrape_schedule, util


def run(quick: bool = False) -> int:
    cfg = util.load_config()
    t0 = time.time()

    util.log("=== 1/7 ingest ===")
    ingest.download_core(cfg)
    if not quick:
        ingest.derive_winners(cfg)

    util.log("=== 2/7 features ===")
    features.main([])  # build profiles
    util.log("=== 3/7 ratings ===")
    ratings.main([])

    if not quick:
        util.log("=== 4/7 evaluate (backtest) ===")
        try:
            evaluate.main([])
        except Exception as exc:  # noqa: BLE001
            util.log(f"run_daily: backtest skipped ({exc})")

    util.log("=== 5/7 scrape schedule ===")
    try:
        scrape_schedule.main([])
    except Exception as exc:  # noqa: BLE001
        util.log(f"run_daily: scrape failed, using manual fixtures ({exc})")

    util.log("=== 6/7 predict ===")
    predict.main([])

    util.log("=== 7/8 player stats ===")
    try:
        players.run(cfg)
    except Exception as exc:  # noqa: BLE001
        util.log(f"run_daily: player stats skipped ({exc})")

    util.log("=== 8/8 build site ===")
    build_site.main([])

    util.log(f"run_daily: done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(quick="--quick" in sys.argv[1:]))
