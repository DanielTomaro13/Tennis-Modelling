# Grand Slam Tennis

Statistical modelling of professional tennis matches (ATP + WTA, singles **and** doubles),
published as a static [GitHub Pages site](https://danieltomaro13.github.io/Tennis-Modelling/)
and rebuilt automatically every 3 hours.

The site mirrors the AFL/NRL modelling dashboards — **Matches**, **Rankings**, **Analysis**,
**Backtest**, **Model Lab** and (soon) **Compare odds**. Every match is priced across a full
market book: win probability and fair odds, set betting, per-set winners, total games and
handicaps, tie-breaks, breaks of serve, aces and double faults, plus most-aces / most-DF props.

## How it works

A reproducible Python pipeline built entirely from public data:

| Stage | Module | Output |
|-------|--------|--------|
| Ingest | `src/ingest.py` | Cache ATP + WTA match histories, players, rankings |
| Profiles | `src/features.py` | Per-player surface serve/return profiles (recency-weighted, opponent-adjusted, shrunk) |
| Ratings | `src/ratings.py` | Surface-weighted Elo (overall + hard / clay / grass) |
| Engine | `src/sim.py` | Hierarchical point→game→set→match Markov + Monte-Carlo simulator |
| Fixtures | `src/scrape_schedule.py`, `src/fixtures.py` | Upcoming matches mapped to player ids |
| Predict | `src/predict.py` | Full projection per fixture |
| Backtest | `src/evaluate.py` | Log-loss / Brier / calibration vs baselines |
| Site | `src/build_site.py` | Render `docs/` (HTML + JSON) |

`src/run_daily.py` chains these; `.github/workflows/daily.yml` runs it on a daily cron.

### Model summary

1. **Serve/return profiles.** From each player's serve statistics we estimate, per surface,
   their service- and return-points-won rates, ace rate, double-fault rate and serve splits —
   recency-weighted (exponential decay), opponent-adjusted, and shrunk toward the tour mean
   for small samples.
2. **Surface-weighted Elo.** Chronological Elo (overall and per-surface) gives a calibrated
   baseline win probability.
3. **Match engine.** The two players' serve/return rates yield per-point serve-win
   probabilities, which roll up analytically (and via Monte-Carlo for derived markets) to
   game / set / match outcomes — anchored to the Elo blend so the headline number stays
   calibrated.

## Data sources

- [Jeff Sackmann — `tennis_atp`](https://github.com/JeffSackmann/tennis_atp) and
  [`tennis_wta`](https://github.com/JeffSackmann/tennis_wta) — match histories, players, rankings.
- [tennis.com](https://www.tennis.com/) — upcoming order of play / schedule.
- Methodology inspired by [Tennis Abstract](https://www.tennisabstract.com/).

## Local run

```bash
pip install -r requirements.txt
python -m src.run_daily          # full pipeline -> docs/
python -m http.server -d docs    # preview at http://localhost:8000
```

## Disclaimer

For research and entertainment only. Model projections are not betting advice.
