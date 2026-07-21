# TransitPulse project journal

Newest entries first. One entry per working session: what was added, the numbers produced, decisions made, and anything running or unfinished. This is the recollection file; docs/yc-plan-jul25.md is the forward-looking backlog.

## 2026-07-21: rigor pass, real APC data, monolith transformer redesign, knowledge graph

Directive this session: outreach deferred to later today, full focus on model/data/technical sophistication. Arya confirmed all four positioning ideas from yesterday's discussion (audit-trail-as-product, self-serve calculator, regulatory tailwind, technical depth as credibility signal) and asked for the repo to be structured like a lab notebook. Also: AI attribution is fine going forward (see [[arya-style-rules]]), travel meant the laptop closed mid-session; both long downloads are written to resume cleanly (see below).

### Hygiene: killed a data-corruption bug before it mattered

Two background fetches from the prior session survived the laptop shutdown as orphaned OS processes (Windows does not reliably kill children when the harness's tracking says "stopped"). They raced the freshly-resumed fetchers on identical output filenames, producing `WinError 32` file-lock errors and at least two possibly-corrupted `.part` files. Found via `Get-CimInstance Win32_Process -Filter "Name='python.exe'"` cross-referenced against command lines, killed the stale PIDs, deleted the two suspect partials, let the live processes redownload them clean. Lesson: after any laptop sleep/close during a background fetch, check for duplicate processes before trusting "resumed" output.

### Real APC-sourced ridership: MTA bus and subway (realdata/fetch_mta_apc.py)

Added the two datasets that are the actual public analog to bus/rail automatic-passenger-counter data: MTA Bus Hourly Ridership (447M+ raw rows, 2020-present) and MTA Subway Hourly Ridership (121M+ raw rows, 2020-present), both real fare-tap-derived ridership by route/station and hour. This is the phase-2 (fixed-route/campus/hub) evidence base and, combined with Chicago TNP and NYC TLC, the pretraining corpus for the transformer. Chicago's day-chunked fetcher (from the 20 July session) was found to be dangerously slow on the older 2018-2022 dataset (~50s/day sequential, projecting 20+ hours) and was rewritten to fetch days concurrently (ThreadPoolExecutor, 4 workers) with soft-fail-and-gap-log instead of a hard crash on a bad day.

### Rigor: walk-forward backtest and SHAP explainability on the real AAR model (realdata/backtest_and_explain.py)

Replaced the single 90-day holdout with a 4-fold rolling-origin backtest (expanding training window, non-overlapping 90-day folds walking back to mid-2025). Result: model R2 0.972 mean (std 0.023) vs naive 0.919 mean (std 0.025) across all four folds, including a materially harder winter fold (0.934 vs 0.878) — a single lucky holdout window was a weak claim; four consistent folds is a strong one. Also ran SHAP TreeExplainer on the production model: lag7 (same day last week) dominates global importance (0.70 mean |SHAP|), followed by lag14 and the 28-day rolling mean; six worked "why this forecast" examples generated from the real model on real data, in the same plain-language format the product's explanation cards use (realdata/explanations_aar.json). Refined the conformal intervals to test hour-of-day-bucket conditioning (conformal_two_way in train_real_models.py) against the original prediction-decile-only version: result was a wash (97.8% vs 98.1% coverage, near-identical width), an honest negative finding worth keeping — it means the point prediction already encodes most of the hour-driven variance, so conditioning on hour again added nothing. Both methods are reported in metrics_real.json.

### Self-serve savings calculator (ntd/savings_calculator.py)

Built the backend for the "punch in your agency, see your own numbers" website widget Arya and Chris agreed on: public-data-only (every figure from the agency's own NTD filing), zero PHI, zero routing demo, so it doesn't touch the locked no-public-map-demo rule. Fuzzy agency search plus a computed savings scenario (deadhead-cut dollar value where deadhead data exists, cost-per-trip-gap-vs-median otherwise, honest "you already run lean" message when neither applies). Deliberately built ahead of the website (which stays last) because it's pure computation reusing data already on hand.

### Monolith transformer redesign: pretrain-then-finetune (kaggle/transitpulse_transformer.ipynb)

Arya asked directly why not train one big neural net across everything, given a 12-hour Kaggle T4 budget. Decision: not a flat single-loss mashup — the ~1.7B-trip mass-transit corpus would drown the ~93k-row AAR paratransit target in any joint loss. Redesigned as two stages: Stage 1 pretrains one shared transformer (d_model 256, 8 heads, 6 layers, ~15-20M params, dual Poisson-mean + quantile-pinball heads for native uncertainty) on the combined real mass-transit corpora (TLC always, Chicago/MTA bus/MTA subway if attached as an optional Kaggle Dataset), using a (dataset, zone) entity embedding so cities don't collide. Stage 2 fine-tunes on AAR specifically: new borough and dataset embeddings at full learning rate, pretrained backbone at 5% of that rate. This is a genuine transfer-learning claim for the application, not a parameter-count flex, and the notebook is explicit that the finetuned result must be compared against the XGBoost result in realdata/metrics_real.json before claiming the transformer is better.

### Data catalog and knowledge graph

Added docs/DATA_SOURCES.md: single-page index of every dataset (source, volume, dates, license, repo location, fetch script), including a section on sources investigated and rejected (London Dial-a-Ride: real UK paratransit-equivalent, but quarterly/local-authority granularity and over a decade stale — not usable, logged so no future session re-investigates it). Also ran /graphify on the full repo with Obsidian output to C:\Users\aryaa\Documents\Obsidian\GraphifyVault, per Arya's request to make the project queryable like a second brain across sessions.

### Product positioning, confirmed (not yet built into the application draft)

Four ideas from the prior session's "how do we sell this without outreach" discussion, all confirmed by Arya: (1) position the audit trail as the product — "every denial, litigation-ready, in one click" — not a feature bolted onto a routing algorithm; (2) the savings calculator above as the zero-call-required "wow"; (3) algorithmic-accountability regulatory tailwind as the "why now" (checked: S.2164, the Algorithmic Accountability Act of 2025, is real and pending in Senate Commerce Committee as of mid-2026, no paratransit-specific language yet, so cite it as a directional signal, not a settled mandate); (4) technical depth (walk-forward validation, honest baselines, calibrated uncertainty, billion-scale real data) as the credibility substitute for traction. None of this is written into docs/yc-application-draft.md yet — that file still does not exist.

### Running or interrupted at end of session

Background at last check: MTA bus hourly fetch ~56/78 months done; MTA subway hourly not yet started (queued after bus completes in the same process); Chicago TNP panel restarted with concurrent fetching, early days in progress. TLC parquet is fully complete (39.8 GB, Feb 2019 to May 2026, one gap patched). Resume commands, all skip-if-exists:

```
py -3 realdata/fetch_mta_apc.py          # bus then subway, resumes mid-feed
py -3 realdata/fetch_chicago_panel.py    # concurrent day-chunked, resumes mid-month
```

Then, once panels exist: `py -3 realdata/train_real_models.py` (adds Chicago), `py -3 realdata/aggregate_tlc.py` (TLC parquet -> zone-hour panel for local use), and re-run `py -3 realdata/backtest_and_explain.py` for Chicago's walk-forward + SHAP once its model exists.

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
