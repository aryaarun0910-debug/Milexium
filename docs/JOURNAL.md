# Milexium project journal

Newest entries first. One entry per working session: what was added, the numbers produced, decisions made, and anything running or unfinished. This is the historical record; `docs/MASTER_ROADMAP.md` is the only active backlog.

Renamed from TransitPulse to Milexium on 2026-07-22 (see entry below). Entries
dated before the rename refer to the company as TransitPulse throughout,
unchanged, because this file is an append-only historical record.

## 2026-07-22 (later): rebrand to Milexium

Company renamed TransitPulse -> Milexium. Tagline "Every mile, justified" proposed,
not yet confirmed. Chris is building the new marketing site at https://milexium.com
separately; `web/` in this repo (the old transitpulse-psi.vercel.app source) was
deliberately left untouched to avoid conflicting with that work. Updated company
name/URL/tagline references across active docs (README, MASTER_ROADMAP,
DATA_SOURCES, DATA_STORAGE, MODEL_CARDS, YC application draft), active scripts
(audit_repository.py, build_model_cards.py, fetch_osm_poi.py, make_real_demo_assets.py
x2, ntd/build_economics.py, ntd/fetch_ntd.py), and outreach/design_partner_pitch.md.
Left untouched on purpose: `docs/archive/` (historical record), prior JOURNAL.md
entries above this one (historical record), `artifacts/knowledge-graph/2026-07-21/`
(dated generated snapshot), and the live external resource identifiers `kaggle/transitpulse_transformer.ipynb`
and the Kaggle dataset `aryaarun07/transitpulse-real-panels` (renaming those means
recreating/re-pushing them on Kaggle - deferred, not blocking anything). Also
renamed the GitHub repo itself, aryaarun0910-debug/TransitPulse ->
aryaarun0910-debug/Milexium (`gh repo rename`), and updated the local `origin`
remote URL to match; GitHub redirects the old URL so existing clones (including
Chris's) keep working without action, though they should update their remote
URL when convenient. Local clone folder also renamed to `Milexium` to match.

## 2026-07-22: repository and data-storage audit

- Consolidated active planning into `docs/MASTER_ROADMAP.md`; moved superseded
  handoffs, initial plans, website briefs, and strategy notes to `docs/archive/`.
- Renamed the ambiguous synthetic `pipeline/` to `reference_agency/`. It remains
  the explicitly fictional trip-level source for scheduling demonstrations; real
  aggregate forecasting evidence remains in `realdata/`.
- Moved generated screenshots and the dated Graphify snapshot under `artifacts/`.
- Documented the 56 GB local data lifecycle in `docs/DATA_STORAGE.md` and added
  `tools/audit_repository.py` to check storage boundaries, schemas, duplicate
  keys, coverage, raw Parquet containers, checkpoint continuity, and links.
- The audit found a missing Chicago checkpoint for 2024-12 and empty header-only
  checkpoints incorrectly finalizing unpublished June/July 2026 data. Restored
  December, removed the false completions, rebuilt the panel, and increased the
  verified total to 555,422,454 trips through 2026-05. The fetchers now reject
  empty high-volume service days, distinguish `.partial.csv` current months, and
  publish checkpoints atomically through `.part` files.
- Final audit: all eight compact/local panels passed schemas and unique-key
  checks; all 88 FHVHV Parquet containers passed; monthly checkpoint sequences
  are continuous. The only warning is expected unfinished scope: green taxi has
  not been fetched.

## 2026-07-21 (evening): GPU acceleration, Kaggle live runs, nationwide data expansion

Discovered two capabilities that were sitting unused: (1) XGBoost GPU training works on this laptop's old MX350 (PyTorch's CUDA kernels don't support sm_61, but XGBoost's do), and (2) the Kaggle API is fully authenticated under account aryaarun07 with an existing token. Acted on both.

**GPU everywhere local:** switched all four real-data XGBoost models and the pretrain/finetune experiment to `device="cuda"`. Also added MTA bus (438 routes) and MTA subway (428 stations) models to train_real_models.py, so it now trains all four real modalities (AAR, Chicago, MTA bus, MTA subway) in one run.

**Kaggle live, not just a notebook to hand off:** uploaded the real panels as a Kaggle Dataset (aryaarun07/transitpulse-real-panels) and pushed the transformer notebook as an actual running kernel with `--accelerator NvidiaTeslaT4`. First run surfaced two real bugs the local CPU smoke test could not: (a) Kaggle silently decompresses uploaded .csv.gz to .csv, so every attached panel lookup failed (fixed with a find_panel helper checking both suffixes); (b) TEST_MODE's 6-month window couldn't fit the 90+90-day tune/test reservation, leaving zero training windows (fixed by scaling TUNE_DAYS/TEST_DAYS down under TEST_MODE). The first completed run gave an honest bad number: pretrain on TLC-alone got R2 -0.56 vs naive 0.91 on the untouched test set. That is a confounded, incomplete run (TLC-only, no multi-city pretrain, no AAR finetune, all because of the .gz bug), not a fair test of the design - re-running with the fix. Whatever the corrected number is, it ships next to the naive baseline, win or lose.

**Nationwide data expansion (the "more data than people can get" push, all resumable through a laptop shutdown):**
- NTD Monthly nationwide demand-response panel: 637 agencies, 2002-2026, 2.18 BILLION paratransit trips (realdata/panels/ntd_monthly_dr.csv.gz, ~2 MB gzipped, committed). This is the broadest public paratransit demand data that exists - every reporting US agency's monthly ridership time series. Complements AAR's hourly single-agency depth with national breadth. Not yet modeled.
- NYC TLC Yellow + Green taxi download (realdata/fetch_tlc_yellow_green.py, raw_tlc_taxi/ gitignored): 2011-present, 15+ years, two more real NYC demand modalities. Running at shutdown; resume by rerunning the script (skips existing files).
- NOAA NCEI HOURLY weather for NYC + Chicago (realdata/fetch_weather_hourly.py): upgrades the daily weather feature to hourly. Uses the token-free bulk LCD CSVs; a CDO token is saved in .env for any future API use.

**Honest scope note:** true trip/stop-level APC data is NOT public - agencies hold it. There is no download for it; it becomes accessible through a pilot. The nationwide NTD monthly panel is the closest public equivalent and is now captured. Did not launch low-value downloads (GTFS schedules, tract census) just to fill the window.

**Resume after shutdown (all resumable, rerun from repo root):**
```
py -3 realdata/fetch_tlc_yellow_green.py   # continues taxi download
py -3 realdata/fetch_weather_hourly.py     # re-fetches hourly weather (one-shot, fast)
py -3 realdata/train_real_models.py        # GPU, all 4 models -> metrics_real.json
py -3 realdata/pretrain_finetune_xgboost.py # GPU transfer-learning experiment
```
Kaggle transformer: check https://www.kaggle.com/code/aryaarun07/transitpulse-transformer-test-mode; when the TEST_MODE run is validated, flip TEST_MODE=False and push the full-scale run. Optional WMATA key still pending from Arya for DC ridership.

## 2026-07-21 (later): code review found real bugs, all fixed and verified

An external review of commit 14dd8b9 (the one pushed for Codex to look at) found six real issues, five of them substantive enough to actually change numbers or claims. All verified against the code before fixing (not taken on faith), then fixed, then re-verified. This entry is the record of what was wrong and what changed.

**P1, fixed: silent-failure fetchers marking incomplete months as done.** `fetch_mta_apc.py` and `fetch_chicago_panel.py` retried a failed day 5 times, then returned an EMPTY DataFrame instead of a failure signal; the caller concatenated that empty result into the month and wrote it to disk unconditionally, so the `if dest.exists(): continue` resume check treated a month with silently-missing days as permanently complete. Fixed: `fetch_day` now returns `None` on failure (never indistinguishable from a legitimately-empty response), and a month is only written if every one of its days succeeded — otherwise the whole month is left unwritten so the next run retries it in full. Audited every already-downloaded month file for gaps before trusting any of them further: found exactly one casualty, `mta_bus_monthly/2026-07.csv` (missing days 15-18 within its own expected range), deleted it, let the fixed fetcher redo it. Everything else scanned clean.

**P1, fixed: transformer notebook reused the holdout for both checkpoint selection and reported metrics.** Both training stages picked the best epoch using `valid_dl`, then reported final numbers on that same loader — that's tuning-set performance, not holdout performance. Fixed: real three-way split, `train` / `tune` (checkpoint selection only) / `test` (final holdout, touched exactly once, at the very end of each stage). Verified this doesn't just move the goalposts by re-reading every cell that touches `test_dl`/`ft_test_dl` to confirm nothing upstream of the final evaluation cells ever sees those pairs.

**P1, fixed: shared-clock densification fabricated zero demand.** `build_matrix()` spanned the earliest-to-latest date across ALL attached datasets and zero-filled every entity for the full range — so an entity from a dataset that starts later than another attached dataset (MTA bus from 2020-01 while TLC runs from 2019-02) got FABRICATED zero-demand training examples for the gap, not correct exclusion. Fixed: track each entity's real coverage (first/last hour actually observed, computed before zero-filling) and only build train/tune/test windows that fall entirely inside it. Verified the fix logic locally with a synthetic two-dataset test before touching the notebook — confirmed the old approach would have produced 40 fabricated-zero windows for a late-starting entity and the fixed approach produces zero.

Discovered mid-fix that this laptop actually has PyTorch installed (2.10.0+cu128) and a GPU (an old NVIDIA MX350, too weak and too old an architecture for this PyTorch build's compiled kernels to actually use, but CPU execution works fine). Used that to go one step further than pandas-only verification: wrote a standalone CPU smoke test reproducing the exact architecture, window-construction, and training loop from the notebook against tiny synthetic data, and ran it. Forward pass, backward pass, loss computation, the tune/test split, and the non-crossing-quantile constraint all passed. This is not the same claim as "the real GPU run happened" — it is the claim that the code itself runs correctly, which is a real, if partial, upgrade from pure static review.

**P1, fixed: ACS latent-demand data mislabeled as ADA-eligible population.** docs/DATA_SOURCES.md and the fetch script's docstring said residents are "ADA-paratransit-eligible by age/disability alone." This is legally wrong: 49 CFR Part 37 Subpart F defines paratransit eligibility by FUNCTIONAL inability to use fixed-route service (often trip-specific), not by age or disability status alone — age in particular does not qualify anyone. This was a real credibility/legal-accuracy risk if it had ended up verbatim in outreach to a compliance officer who knows the regulation. Fixed everywhere: reframed as a latent-mobility-need proxy for market sizing, never an eligibility count.

**P2, fixed: conformal calibration set was also used for XGBoost early stopping.** `train_real_models.py` fit with `eval_set=[(cal, cal.y)]` for early stopping, then used that same `cal` block's residuals to calibrate conformal intervals — using one block for both purposes forfeits the clean split-conformal exchangeability guarantee. Fixed: real four-way split, train / tune (early stopping only) / cal (calibration only, never seen during fit) / valid (final reporting). Retrained AAR after the fix: R2 0.985 vs 0.923 naive (was 0.987 pre-fix) — materially unchanged, which is reassuring: the original result wasn't an artifact of the conflation, it just hadn't been rigorously isolated from it.

**P2, fixed: notebook claimed weather sensitivity but never loaded weather; parameter count was wrong; notebook status wasn't documented.** The intro claimed the model learns "weather sensitivity," and kaggle/README.md said `weather_daily.csv` should be attached, but no cell ever read or used it — the model only ever saw log-count and calendar features. Fixed: weather is now a real 4-channel input (tmax/tmin/precip/snow, city-indexed per dataset, zero-filled and skipped gracefully if not attached). Separately, kaggle/README.md claimed "roughly 15-20M parameters" without ever computing it; the true figure, verified analytically against PyTorch's documented layer shapes (not guessed, not run — I don't have a GPU to execute the notebook), is 4.92M to 5.15M depending on how many datasets are attached. Also added an explicit "this notebook has not been executed end to end" notice to both the notebook and its README, since it hadn't been and the earlier version didn't say so.

**P2, fixed: "APC-sourced" MTA bus data was inaccurate.** MTA's hourly bus and subway ridership datasets are OMNY/MetroCard fare-payment (AFC) derived, not onboard-sensor (APC) data. Real, legitimate ridership proxy either way, but conflating the two terms is the kind of thing a transit-industry-literate reader (an FTA person, an actual paratransit ops director) would catch immediately, undermining the domain-credibility claim we're actually going for. Fixed the terminology everywhere (docs/DATA_SOURCES.md, realdata/README.md, docs/JOURNAL.md, the fetch script's own docstring), without renaming the script itself.

**Separately, in response to a large "enterprise product/architecture" brief Arya pasted mid-session:** triaged rather than executed wholesale. The brief's own closing section ("Do Not Build For Appearances") argues against most of itself for a two-founder pre-launch repo four days from a deadline — building OR-Tools VRPTW, a dispatcher console, Temporal/Dagster/MLflow infra, or SOC2/HIPAA compliance apparatus this week would look less credible, not more. Kept: the reframing of the audit trail as "compliance-grade replay" (deterministic, rule-traceable scheduling decisions, never SHAP — SHAP stays scoped to demand-forecast explanation only, which the existing scheduler already does correctly, just not documented as a deliberate separation), and the correction that AAR is aggregate borough-hourly data, useful for validating demand FORECASTING but not individual-trip DISPATCH decisions. Everything else from that brief is logged as future-scope, not built.

Every fix above was verified against the actual code before changing anything (grepped for the exact claims, read the exact functions) and re-verified after (retrained models, compile-checked every touched script, ran the coverage-masking logic against synthetic data). Nothing in this entry is taken on the reviewer's word alone.

## 2026-07-21: rigor pass, real AFC ridership data, monolith transformer redesign, knowledge graph

Directive this session: outreach deferred to later today, full focus on model/data/technical sophistication. Arya confirmed all four positioning ideas from yesterday's discussion (audit-trail-as-product, self-serve calculator, regulatory tailwind, technical depth as credibility signal) and asked for the repo to be structured like a lab notebook. Also: AI attribution is fine going forward (see [[arya-style-rules]]), travel meant the laptop closed mid-session; both long downloads are written to resume cleanly (see below).

### Hygiene: killed a data-corruption bug before it mattered

Two background fetches from the prior session survived the laptop shutdown as orphaned OS processes (Windows does not reliably kill children when the harness's tracking says "stopped"). They raced the freshly-resumed fetchers on identical output filenames, producing `WinError 32` file-lock errors and at least two possibly-corrupted `.part` files. Found via `Get-CimInstance Win32_Process -Filter "Name='python.exe'"` cross-referenced against command lines, killed the stale PIDs, deleted the two suspect partials, let the live processes redownload them clean. Lesson: after any laptop sleep/close during a background fetch, check for duplicate processes before trusting "resumed" output.

### Real AFC-sourced ridership: MTA bus and subway (realdata/fetch_mta_apc.py)

Added MTA Bus Hourly Ridership (447M+ raw rows, 2020-present) and MTA Subway Hourly Ridership (121M+ raw rows, 2020-present), both real fare-tap (AFC, OMNY/MetroCard) derived ridership by route/station and hour. Correction (see the 2026-07-21 review-fixes entry below): this is fare-payment data, not onboard-sensor APC data, and earlier notes in this journal and in DATA_SOURCES.md calling it "APC-sourced" were wrong; fixed throughout. This is the phase-2 (fixed-route/campus/hub) evidence base and, combined with Chicago TNP and NYC TLC, the pretraining corpus for the transformer. Chicago's day-chunked fetcher (from the 20 July session) was found to be dangerously slow on the older 2018-2022 dataset (~50s/day sequential, projecting 20+ hours) and was rewritten to fetch days concurrently (ThreadPoolExecutor, 4 workers) with soft-fail-and-gap-log instead of a hard crash on a bad day.

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
