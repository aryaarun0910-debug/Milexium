# Data source catalog

Every dataset TransitPulse uses, where it comes from, what it's for, and where it lives in the repo. Update this file whenever a new source is added or an existing pull is refreshed. This is the index; the fetch scripts and their READMEs (ntd/README.md, realdata/README.md, kaggle/README.md) are the authority on exact columns and run instructions.

## Real, event-level data (the evidence base)

| Source | What it is | Volume | Date range | License | Repo location | Fetch script |
|---|---|---|---|---|---|---|
| NYC Access-A-Ride | Real paratransit bookings, hourly by borough and provider type. Our exact product target variable. | 26.3M trips | 2024-01 to 2026-05 | Open Data NY, public domain | realdata/panels/aar_hourly_borough.csv.gz | realdata/fetch_nyc_aar.py |
| NYC Access-A-Ride (daily) | Daily scheduled-trip totals, longer history. | 1,776 days | 2020-03 to 2025-01 | Open Data NY | realdata/panels/aar_daily.csv | realdata/fetch_nyc_aar.py |
| NYC TLC FHVHV | Every Uber/Lyft/Via trip in NYC. Transformer-scale pretraining corpus and door-to-door demand proof point. | ~1.7B raw trips, 39.8 GB parquet | 2019-02 to 2026-05 | NYC TLC, public | realdata/raw_tlc/ (gitignored) -> aggregated via aggregate_tlc.py | realdata/fetch_tlc_parquet.py |
| Chicago TNP trips | Every rideshare trip in Chicago under the city's reporting ordinance. Aggregated server-side to community-area-hour. | ~300M raw trips | 2018-11 to present | City of Chicago Data Portal, public | realdata/panels/chicago_tnp_zone_hour.csv.gz | realdata/fetch_chicago_panel.py |
| MTA bus hourly ridership | Real APC/AFC-sourced bus ridership by route and hour. Closest public analog to bus automatic-passenger-counter data; phase-2 (fixed-route) evidence. | 447M+ raw rows, aggregated to route-hour | 2020-01 to present | Open Data NY, public | realdata/panels/mta_bus_route_hour.csv.gz | realdata/fetch_mta_apc.py |
| MTA subway hourly ridership | Real AFC-sourced subway ridership by station and hour. | 121M+ raw rows, aggregated to station-hour | 2020-01 to present | Open Data NY, public | realdata/panels/mta_subway_station_hour.csv.gz | realdata/fetch_mta_apc.py |
| Open-Meteo weather | Daily temperature, precipitation, snowfall history for Chicago and NYC. Exogenous feature for every real-data model. | 2,819 days x 2 cities | 2018-11 to present | Open-Meteo, free/keyless | realdata/panels/weather_daily.csv | realdata/fetch_weather.py |

## Government economics data (market sizing and outreach)

| Source | What it is | Volume | Repo location | Fetch script |
|---|---|---|---|---|
| FTA National Transit Database, demand-response | Every US paratransit/NEMT operator's annual filing: trips, cost, revenue hours, deadhead detail. | 3,075 agencies, 2022-2024 | ntd/raw/, ntd/agency_economics.csv, ntd/market_sizing.md | ntd/fetch_ntd.py, ntd/build_economics.py |

Derived products: ntd/build_outreach_targets.py (80 tiered outreach targets with per-agency hooks), ntd/savings_calculator.py (self-serve "your agency's own numbers" calculator, backend for the future website widget).

## Synthetic data (v1 pipeline, being retired)

| What | Why it existed | Retirement condition |
|---|---|---|
| pipeline/generate_trips.py output | Bootstrapped the demo before real data was pulled; anchored to NTD demand-response norms. | Retire once real-data demo assets replace docs/demo-assets/*.png AND the audit-trail scheduler has a real booking stream (Chicago TNP trip records are the candidate). |

## Latent demand and real-geography features (differentiators, not event data)

| Source | What it is | Volume | Repo location | Fetch script |
|---|---|---|---|---|
| Census ACS 5-year, 2023 | County-level share 65+, share with a disability, share of no-vehicle households. The addressable-population view: who's ADA-paratransit-eligible by age/disability alone, not just who's currently riding. Requires a free API key (see .env, CENSUS_API_KEY). | 3,222 counties | ntd/census_latent_demand.csv | ntd/fetch_census_latent_demand.py |
| OpenStreetMap POI (dialysis, senior centers, hospitals, nursing homes) | Real facility locations, replacing the synthetic pipeline's guessed zone flags with real geography for any county. | Partial — see status below | ntd/osm_poi/ | ntd/fetch_osm_poi.py |

**OSM POI status:** works correctly for small bounding boxes (verified against a downtown-Chicago test query) but the shared public Overpass instance (overpass-api.de) returns 504 Gateway Timeout on full-county-sized bboxes even split one-category-per-request, apparently server load on the free shared instance rather than a query-design problem. Needs either a smaller-area chunking strategy (query by zip code or a grid of sub-boxes instead of the whole county) or a paid/dedicated Overpass instance to run reliably. Not blocking anything else; revisit when needed for a specific outreach target.

## Investigated, not used

| Source | Why not |
|---|---|
| London Dial-a-Ride usage statistics (London Datastore) | Real UK paratransit-equivalent service, but the published stats are quarterly, local-authority granularity, and the dataset has not been updated in over a decade. Not usable for hourly demand modeling. Revisit if TfL's Open Data portal exposes anything finer-grained. |

## Modeling protocol (applies to every real-data model, no exceptions)

Strict temporal holdout (last 90 days), seasonal-naive baseline (same zone/hour/day-of-week average) reported alongside every model result, split-conformal or learned-quantile uncertainty. See realdata/README.md for the full method and current numbers, realdata/backtest_and_explain.py for the walk-forward multi-fold version and SHAP explainability, and kaggle/README.md for the pretrain-then-finetune transformer.
