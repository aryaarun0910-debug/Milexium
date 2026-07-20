# TransitPulse project journal

Newest entries first. One entry per working session: what was added, the numbers produced, decisions made, and anything running or unfinished. This is the recollection file; docs/yc-plan-jul25.md is the forward-looking backlog.

## 2026-07-20 (evening): real data replaces guesswork

Directive shift from Arya this session: maximum scale ("a year of founder output per day"), real data over synthetic, transformer-scale training on Kaggle GPUs, retire the synthetic pipeline once real data fully covers it, keep the repo organized and journaled, website deliberately last. AI attribution on commits is now fine (rule reversed by Arya; no-emoji and no-em-dash rules stand).

### NTD: the entire US demand-response market, quantified (ntd/)

- Pulled FTA National Transit Database metrics and service tables (modes DR and DT, 2022-2024) from data.transportation.gov: 6,108 agency-mode-year rows, 3,075 agencies.
- Built agency_economics.csv: per-agency trips, opex, cost/trip, revenue hours, deadhead share, ADA share, and the dollar value of a 10 percent deadhead cut computed from each agency's own filing.
- Market sizing (2024 report year): 1,920 agencies, 139.7M annual trips, $7.06B operating expense, median $37.97 per trip, expense-weighted deadhead 17.3 percent of vehicle hours, $94M/year value in a 10 percent deadhead cut across the 413 full reporters.
- Sanity checks passed against known reality: LA Access Services 4.2M trips at $59, NYC AAR $96, WMATA $135 per trip.
- Generated outreach/targets_ntd.csv: 80 tiered targets (A: 50k-1M trips, B: 20k-50k, C: over 1M), each with a personalized hook sentence from its own NTD numbers.

### Real demand data and models (realdata/)

- NYC Access-A-Ride: 26.3M real paratransit bookings, hourly by borough and provider type, Jan 2024 to May 2026 (panels/aar_hourly_borough.csv.gz) plus the daily series from Mar 2020 (panels/aar_daily.csv). This is our exact target variable from the largest US paratransit operation.
- Weather: Open-Meteo daily history for Chicago and NYC since Nov 2018 (panels/weather_daily.csv).
- Trained the borough-hour AAR model, protocol identical to the synthetic pipeline: strict temporal split (last 90 days validation, prior 90 calibration), XGBoost count:poisson, seasonal-naive baseline, split-conformal intervals.
- Headline result on REAL paratransit demand: R2 0.987 vs 0.923 naive, MAE 19.7 vs 55.5 (64 percent error reduction), conformal coverage 98.1 percent at a 90 percent target (conservative; calibration window straddled winter). Full numbers in realdata/metrics_real.json.
- Honest finding kept on purpose: without demand-history lag features, calendar+weather ties the naive baseline (R2 0.919 vs 0.921). The lags (1/7/14-day and trailing 28-day mean, all available day-ahead) are what beat climatology.
- Chicago TNP: month-level server-side group-bys time out on the 200M-row 2018-2022 dataset, so the fetcher was rewritten to day-level chunks with per-month files and skip-if-exists resume (fetch_chicago_panel.py). It was running when this session ended.
- NYC TLC FHVHV bulk download (fetch_tlc_parquet.py): monthly parquet, about 40 GB total for 2019-2026, resumable; 19 files (7.9 GB) landed before this session ended. aggregate_tlc.py (DuckDB, out-of-core) turns whatever is on disk into a zone-hour panel.

### Kaggle GPU track (kaggle/)

- transitpulse_transformer.ipynb: complete notebook that downloads the TLC corpus inside Kaggle, aggregates with DuckDB, and trains a ~1M-parameter temporal transformer (336h context, 24h horizon, Poisson NLL, zone embeddings) with the same holdout-plus-naive-baseline protocol. TEST_MODE flag for a 20-minute smoke run. Arya runs this on Kaggle (GPU on, internet on).

### Plan and docs

- docs/yc-plan-jul25.md rewritten from day-by-day schedule to a living execution backlog (Arya: no dates, we outrun any schedule; add tasks as they appear).
- docs/HANDOFF.md attribution rule updated.
- READMEs added: ntd/, realdata/, kaggle/; root README structure updated.

### Running or interrupted (laptop travels, both fetchers are resumable)

Resume with exactly these two commands from the repo root; each skips everything already on disk:

```
py -3 realdata/fetch_chicago_panel.py   # day-chunked, writes panels/chicago_monthly/
py -3 realdata/fetch_tlc_parquet.py     # writes raw_tlc/*.parquet (gitignored)
```

Then, when panels exist:

```
py -3 realdata/train_real_models.py     # adds the Chicago model to metrics_real.json
py -3 realdata/aggregate_tlc.py         # TLC parquet -> zone-hour panel
```

### Decisions this session

- Scale tooling: DuckDB and PyArrow (C++/Rust engines) over a new language; Kaggle GPUs for anything needing CUDA. Revisit only if profiling shows a real bottleneck.
- "APC data" for paratransit does not exist publicly; the real equivalents chosen: AAR hourly (actual paratransit), Chicago TNP and NYC TLC (door-to-door demand at scale), MTA hourly station ridership (optional APC-style corpus, not yet pulled).
- Synthetic pipeline stays until (a) real-data demo assets exist and (b) the audit-trail scheduler has a real booking stream (Chicago TNP trip records are the candidate). Then it gets retired per Arya's directive.

## 2026-07-20 (daytime, prior session): foundation

Repo refocused on TransitPulse (paratransit positioning, two founders, YC 25 July plan, website brief for Chris). v1 synthetic pipeline built and committed: trip generator anchored to NTD norms (about 90k bookings, 245/day), zone-hour XGBoost demand model (R2 0.839 vs 0.817 naive, 90-day temporal holdout), audit-trail scheduler (229/253 placed, 77 percent pooled, deadhead 17 percent, every decision and denial logged with factors and rejected alternatives), five rendered demo PNGs in docs/demo-assets/. Handoff written to docs/HANDOFF.md.
