# Graph Report - c:\Users\aryaa\Documents\TransitPulse  (2026-07-21)

## Corpus Check
- Corpus is ~28,510 words - fits in a single context window. You may not need a graph.

## Summary
- 237 nodes · 281 edges · 32 communities (12 shown, 20 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 11 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Outreach and Market Evidence|Outreach and Market Evidence]]
- [[_COMMUNITY_TLCChicago Ingestion (DuckDB, Day-Chunking)|TLC/Chicago Ingestion (DuckDB, Day-Chunking)]]
- [[_COMMUNITY_Locked Product Strategy|Locked Product Strategy]]
- [[_COMMUNITY_Synthetic Trip Generator|Synthetic Trip Generator]]
- [[_COMMUNITY_SHAP Explanation Schema|SHAP Explanation Schema]]
- [[_COMMUNITY_Real-Data Model Metrics|Real-Data Model Metrics]]
- [[_COMMUNITY_Walk-Forward Backtest + SHAP Pipeline|Walk-Forward Backtest + SHAP Pipeline]]
- [[_COMMUNITY_NTD Economics and Outreach Hooks|NTD Economics and Outreach Hooks]]
- [[_COMMUNITY_Real-Data Training Pipeline|Real-Data Training Pipeline]]
- [[_COMMUNITY_AAR Backtest Fold Results|AAR Backtest Fold Results]]
- [[_COMMUNITY_Chicago Panel Fetcher Internals|Chicago Panel Fetcher Internals]]
- [[_COMMUNITY_MTA APC Fetcher Internals|MTA APC Fetcher Internals]]
- [[_COMMUNITY_Audit-Trail Scheduler Core|Audit-Trail Scheduler Core]]
- [[_COMMUNITY_Outreach Target Tiering|Outreach Target Tiering]]
- [[_COMMUNITY_Synthetic Trip Generation Internals|Synthetic Trip Generation Internals]]
- [[_COMMUNITY_Demo Asset Rendering|Demo Asset Rendering]]
- [[_COMMUNITY_TLC Bulk Download|TLC Bulk Download]]
- [[_COMMUNITY_Scheduler Pooling and Assignment|Scheduler Pooling and Assignment]]
- [[_COMMUNITY_AAR Backtest Fit Loop|AAR Backtest Fit Loop]]
- [[_COMMUNITY_NTD Fetch Script|NTD Fetch Script]]
- [[_COMMUNITY_AAR Fetch Script|AAR Fetch Script]]
- [[_COMMUNITY_NTD Economics Builder|NTD Economics Builder]]
- [[_COMMUNITY_Synthetic Demand Model Training|Synthetic Demand Model Training]]
- [[_COMMUNITY_TLC Aggregation Script|TLC Aggregation Script]]
- [[_COMMUNITY_Weather Fetch Script|Weather Fetch Script]]
- [[_COMMUNITY_NTD Fetcher (module node)|NTD Fetcher (module node)]]
- [[_COMMUNITY_Demo Asset Why This Trip|Demo Asset: Why This Trip]]
- [[_COMMUNITY_Demo Asset Capacity Alert|Demo Asset: Capacity Alert]]
- [[_COMMUNITY_Demo Asset Why This Forecast|Demo Asset: Why This Forecast]]
- [[_COMMUNITY_Demo Asset Demand Curve|Demo Asset: Demand Curve]]
- [[_COMMUNITY_Demo Asset Fleet Timeline|Demo Asset: Fleet Timeline]]
- [[_COMMUNITY_Vehicle Class|Vehicle Class]]

## God Nodes (most connected - your core abstractions)
1. `global_feature_importance_mean_abs_shap` - 17 edges
2. `nyc_access_a_ride` - 17 edges
3. `Session Handoff Doc` - 17 edges
4. `TransitPulse README` - 11 edges
5. `Project Journal` - 11 edges
6. `YC Execution Backlog` - 11 edges
7. `YC Application Notes (Locked Strategy)` - 9 edges
8. `Synthetic Pipeline README` - 9 edges
9. `Synthetic Zone-Hour Demand Model Trainer` - 8 edges
10. `Demo Asset Renderer` - 7 edges

## Surprising Connections (you probably didn't know these)
- `Synthetic Zone-Hour Demand Model Trainer` --semantically_similar_to--> `Real Demand Model Trainer (conformal intervals)`  [INFERRED] [semantically similar]
  pipeline/train_demand.py → realdata/train_real_models.py
- `Demand Forecast vs Observed Chart` --conceptually_related_to--> `Seasonal-Naive Baseline Honesty Norm`  [INFERRED]
  docs/demo-assets/demand_curve.png → realdata/README.md
- `TransitPulse Website One-Liner Positioning` --semantically_similar_to--> `Explainability / Audit-Trail Wedge`  [INFERRED] [semantically similar]
  docs/website-brief.md → YC_APPLICATION_NOTES.md
- `Kaggle Temporal Transformer Notebook` --semantically_similar_to--> `Audit-Trail Scheduler`  [INFERRED] [semantically similar]
  kaggle/README.md → pipeline/README.md
- `Deadhead Cost Attribution Formula` --semantically_similar_to--> `pipeline/output/day_stats.json`  [INFERRED] [semantically similar]
  ntd/build_economics.py → pipeline/schedule_trips.py

## Hyperedges (group relationships)
- **Socrata SoQL Open-Data Fetch Pattern** — fetch_ntd_module, fetch_chicago_panel_module, fetch_mta_apc_module, fetch_nyc_aar_module [INFERRED 0.85]
- **"Why this forecast" explainability pipeline (synthetic demo + real SHAP)** — make_demo_assets_module, backtest_and_explain_explain_fn, explanations_aar_json [INFERRED 0.80]
- **Real-data ingestion feeding the production demand model** — fetch_nyc_aar_hourly_output, fetch_chicago_panel_output, fetch_weather_output, train_real_models_module [INFERRED 0.85]
- **Marketing Demo Asset Set (rendered from synthetic pipeline)** — img_capacity_alert, img_demand_curve, img_fleet_timeline, img_why_this_forecast, img_why_this_trip, pipeline_readme_doc [EXTRACTED 1.00]
- **Locked YC Strategy Decisions (beachhead, wedge, geography, FPGA cut)** — concept_beachhead_customer, concept_paratransit_wedge, concept_us_first_geography, concept_fpga_cut, yc_notes_doc [INFERRED 0.85]
- **Real-Data Evidence Ladder (AAR to Chicago TNP to TLC transformer, honest protocol)** — concept_aar_real_demand, concept_chicago_tnp, concept_tlc_fhvhv, concept_kaggle_transformer, concept_conformal_prediction [EXTRACTED 1.00]

## Communities (32 total, 20 thin omitted)

### Community 0 - "Outreach and Market Evidence"
Cohesion: 0.13
Nodes (28): Cold Outreach Email Template, NYC Access-A-Ride Real Demand Data, CCAM-TAC (CTAA Technical Assistance Center), Chicago TNP Rideshare Data, Split-Conformal Prediction Intervals, Community Transportation Association of America (CTAA), 10% Deadhead Reduction Value ($94M/yr), EWB Ladywood Bus Routing Project (+20 more)

### Community 1 - "TLC/Chicago Ingestion (DuckDB, Day-Chunking)"
Cohesion: 0.09
Nodes (23): DuckDB out-of-core streaming (never loads raw trips into memory), TLC FHVHV Parquet Aggregator (DuckDB), realdata/panels/nyc_fhvhv_zone_hour.parquet, Walk-Forward Backtest + SHAP Explainability, combine(), Day-level chunking to avoid Socrata month-level group-by timeout, Chicago TNP Zone-Hour Panel Fetcher, realdata/panels/chicago_tnp_zone_hour.csv.gz (+15 more)

### Community 2 - "Locked Product Strategy"
Cohesion: 0.18
Nodes (21): ADA 49 CFR 37.131(b)(2) Negotiation Window, Audit-Trail Scheduler, Paratransit Beachhead Customer Decision, Founder Equity Split / CEO Designation, FPGA/Hardware Cut From Product, HIPAA/PHI Awareness Requirement, Incumbent Opaque Dispatch Software (Ecolane, TripSpark, RouteMatch/Uber Health), Locked Strategy Decisions (+13 more)

### Community 3 - "Synthetic Trip Generator"
Cohesion: 0.14
Nodes (17): Deadhead Cost Attribution Formula, Harland County Mobility (fictional agency, NTD-anchored synthetic norms), Synthetic Paratransit Trip Generator, pipeline/output/trips.csv, pipeline/output/weather.csv, pipeline/output/zones.csv, Demo Asset Renderer, pipeline/output/audit_log.json (+9 more)

### Community 4 - "SHAP Explanation Schema"
Cohesion: 0.10
Nodes (19): example_explanations, global_feature_importance_mean_abs_shap, borough, dow, hour, hour_cos, hour_sin, is_holiday (+11 more)

### Community 5 - "Real-Data Model Metrics"
Cohesion: 0.11
Nodes (17): nyc_access_a_ride, best_iteration, conformal_achieved_coverage, conformal_mean_interval_width, conformal_target_coverage, model_mae, model_r2, model_rmse (+9 more)

### Community 6 - "Walk-Forward Backtest + SHAP Pipeline"
Cohesion: 0.17
Nodes (11): fit(), prep(), Walk-forward backtest and SHAP explainability on the real demand models.  Two ad, walk_forward(), add_calendar(), add_lags(), conformal(), Train and validate demand models on REAL data, with conformal intervals.  Two mo (+3 more)

### Community 7 - "NTD Economics and Outreach Hooks"
Cohesion: 0.17
Nodes (12): explain(), SHAP in poisson margin (log-rate) space: sign/rank valid, not additive in count units, agency_economics.csv, market_sizing.md, NTD Economics Table Builder, hook(), Outreach Target List Builder, outreach/targets_ntd.csv (+4 more)

### Community 8 - "Real-Data Training Pipeline"
Cohesion: 0.28
Nodes (9): prep(), Open-Meteo Daily Weather Fetcher, realdata/panels/weather_daily.csv, Real-data model metrics (AAR + Chicago, with conformal coverage), add_calendar(), add_lags(), conformal(), Mondrian split-conformal (binned by predicted decile), generous naive baseline (train+cal) (+1 more)

### Community 9 - "AAR Backtest Fold Results"
Cohesion: 0.29
Nodes (6): folds, model_r2_mean, model_r2_std, naive_r2_mean, naive_r2_std, note

### Community 11 - "MTA APC Fetcher Internals"
Cohesion: 0.47
Nodes (4): month_days(), month_starts(), Fetch real APC-sourced transit ridership: MTA subway and bus, hourly.  Both data, run_feed()

### Community 17 - "Scheduler Pooling and Assignment"
Cohesion: 0.50
Nodes (4): Assignment stage (greedy vehicle insertion + audit), 49 CFR 37.131(b)(2) negotiated pickup window, Pooling stage (hub-batching of shared runs), travel_min()

## Knowledge Gaps
- **63 isolated node(s):** `note`, `folds`, `model_r2_mean`, `model_r2_std`, `naive_r2_mean` (+58 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **20 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Real Demand Model Trainer (conformal intervals)` connect `TLC/Chicago Ingestion (DuckDB, Day-Chunking)` to `Real-Data Training Pipeline`, `Synthetic Trip Generator`?**
  _High betweenness centrality (0.046) - this node is a cross-community bridge._
- **Why does `Synthetic Zone-Hour Demand Model Trainer` connect `Synthetic Trip Generator` to `TLC/Chicago Ingestion (DuckDB, Day-Chunking)`?**
  _High betweenness centrality (0.041) - this node is a cross-community bridge._
- **What connects `Build the per-agency demand-response economics table from raw NTD pulls.  For ev`, `Generate a prioritized, personalized outreach target list from NTD data.  Tierin`, `Download FTA National Transit Database demand-response tables.  Sources (DOT Soc` to the rest of the system?**
  _92 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Outreach and Market Evidence` be split into smaller, more focused modules?**
  _Cohesion score 0.12698412698412698 - nodes in this community are weakly interconnected._
- **Should `TLC/Chicago Ingestion (DuckDB, Day-Chunking)` be split into smaller, more focused modules?**
  _Cohesion score 0.09420289855072464 - nodes in this community are weakly interconnected._
- **Should `Synthetic Trip Generator` be split into smaller, more focused modules?**
  _Cohesion score 0.14210526315789473 - nodes in this community are weakly interconnected._
- **Should `SHAP Explanation Schema` be split into smaller, more focused modules?**
  _Cohesion score 0.1 - nodes in this community are weakly interconnected._