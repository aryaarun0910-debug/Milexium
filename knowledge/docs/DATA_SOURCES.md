# Data source catalog

Every dataset Milexium uses, where it comes from, what it's for, and where it lives in the repo. Update this file whenever a new source is added or an existing pull is refreshed. This is the index; the fetch scripts and their READMEs (business/ntd/README.md, realdata/README.md, _legacy/kaggle/README.md) are the authority on exact columns and run instructions.

## Real, event-level data (the evidence base)

| Source | What it is | Volume | Date range | License | Repo location | Fetch script |
|---|---|---|---|---|---|---|
| NYC Access-A-Ride | Real paratransit bookings, hourly by borough and provider type. Our exact product target variable. | 26.3M trips | 2024-01 to 2026-05 | Open Data NY, public domain | realdata/panels/aar_hourly_borough.csv.gz | realdata/fetch_nyc_aar.py |
| NYC Access-A-Ride (daily) | Daily scheduled-trip totals, longer history. | 1,776 days | 2020-03 to 2025-01 | Open Data NY | realdata/panels/aar_daily.csv | realdata/fetch_nyc_aar.py |
| NYC TLC FHVHV | Every Uber/Lyft/Via trip in NYC. Transformer-scale pretraining corpus and door-to-door demand proof point. | ~1.7B raw trips, 39.8 GB parquet | 2019-02 to 2026-05 | NYC TLC, public | realdata/raw_tlc/ (gitignored) -> aggregated via aggregate_tlc.py | realdata/fetch_tlc_parquet.py |
| NYC TLC Yellow + Green taxi | The two classic street-hail taxi modalities, reaching back to 2011 (yellow) and 2014 (green). Deeper history than FHVHV and a different demand regime (street-hail vs app-dispatch); widens the pretraining corpus across 15+ years and 3 NYC modalities. | ~1B+ raw trips (yellow), monthly parquet | 2011-01 to present | NYC TLC, public | realdata/raw_tlc_taxi/ (gitignored) | realdata/fetch_tlc_yellow_green.py |
| NTD Monthly nationwide (demand-response) | Every US transit agency's MONTHLY demand-response ridership (UPT), revenue hours/miles, peak vehicles, back to 2002. Nationwide monthly paratransit DEMAND panel: breadth (637 agencies x 20+ yrs) complementing AAR's single-agency hourly depth. Distinct from business/ntd/ annual economics. | 152k rows, 637 agencies, 2.18B trips | 2002-01 to 2026-05 | FTA / data.transportation.gov (8bui-9xvu), public | realdata/panels/ntd_monthly_dr.csv.gz | realdata/fetch_ntd_monthly.py |
| Chicago TNP trips | Every rideshare trip in Chicago under the city's reporting ordinance. Aggregated server-side to community-area-hour. | 555.4M trips | 2018-11 to 2026-05 | City of Chicago Data Portal, public | realdata/panels/chicago_tnp_zone_hour.csv.gz | realdata/fetch_chicago_panel.py |
| MTA bus hourly ridership | Real AFC (automated fare collection: OMNY/MetroCard tap) ridership by route and hour. NOT onboard-sensor APC data — a legitimate real ridership proxy, but sourced from fare payment, not physical boarding counts; do not market it as APC-scale proof without this qualification. Phase-2 (fixed-route) evidence. | 447M+ raw rows, aggregated to route-hour | 2020-01 to present | Open Data NY, public | realdata/panels/mta_bus_route_hour.csv.gz | realdata/fetch_mta_apc.py |
| MTA subway hourly ridership | Real AFC-sourced subway ridership (turnstile/tap) by station and hour. | 121M+ raw rows, aggregated to station-hour | 2020-01 to present | Open Data NY, public | realdata/panels/mta_subway_station_hour.csv.gz | realdata/fetch_mta_apc.py |
| Open-Meteo weather (daily) | Daily temperature, precipitation, snowfall history for Chicago and NYC. Exogenous feature for the current real-data models. | 2,819 days x 2 cities | 2018-11 to present | Open-Meteo, free/keyless | realdata/panels/weather_daily.csv | realdata/fetch_weather.py |
| NOAA NCEI weather (HOURLY) | Hourly temperature, dew point, precipitation, wind, humidity for NYC (LaGuardia) and Chicago (O'Hare). Upgrades the daily weather feature to hourly, matching the zone-hour modeling granularity. CDO token saved in .env; the bulk LCD CSVs used here need no token. | ~2 stations x hourly, 2018-present | 2018 to present | NOAA NCEI LCD, public | realdata/panels/weather_hourly.csv.gz | realdata/fetch_weather_hourly.py |

## Government economics data (market sizing and outreach)

| Source | What it is | Volume | Repo location | Fetch script |
|---|---|---|---|---|
| FTA National Transit Database, demand-response | Every US paratransit/NEMT operator's annual filing: trips, cost, revenue hours, deadhead detail. | 3,075 agencies, 2022-2024 | business/ntd/raw/, business/ntd/agency_economics.csv, business/ntd/market_sizing.md | business/ntd/fetch_ntd.py, business/ntd/build_economics.py |

Derived products: business/ntd/build_outreach_targets.py (80 tiered outreach targets with per-agency hooks), business/ntd/savings_calculator.py (self-serve "your agency's own numbers" calculator, backend for the future website widget).

## Synthetic reference agency (trip-level demonstration only)

| What | Why it existed | Status |
|---|---|---|
| `business/reference_agency/generate_trips.py` output | Supplies fictional trip-level bookings for scheduler and audit-trail demonstrations; anchored to NTD demand-response norms. | Demand-forecasting assets have real AAR replacements in `evidence/artifacts/demo-assets/`. Trip-level scheduling assets remain explicitly synthetic because no public paratransit source exposes the required booking stream. Retirement is gated on consented design-partner data; see `business/reference_agency/README.md`. |

## Latent demand and real-geography features (differentiators, not event data)

| Source | What it is | Volume | Repo location | Fetch script |
|---|---|---|---|---|
| Census ACS 5-year, 2023 | County-level share 65+, share with a disability, share of no-vehicle households. A latent-mobility-need PROXY, not an ADA-eligibility count: 49 CFR Part 37 defines paratransit eligibility by functional inability to use fixed-route service (often trip-specific), not by age or disability status alone — age in particular does not qualify anyone. Use only as a directional market-sizing/outreach signal. Requires a free API key (see .env, CENSUS_API_KEY). | 3,222 counties | business/ntd/census_latent_demand.csv | business/ntd/fetch_census_latent_demand.py |
| OpenStreetMap POI (dialysis, senior centers, hospitals, nursing homes) | Real facility locations, replacing the synthetic pipeline's guessed zone flags with real geography for any county. | Partial — see status below | business/ntd/osm_poi/ | business/ntd/fetch_osm_poi.py |

**OSM POI status:** works correctly for small bounding boxes (verified against a downtown-Chicago test query) but the shared public Overpass instance (overpass-api.de) returns 504 Gateway Timeout on full-county-sized bboxes even split one-category-per-request, apparently server load on the free shared instance rather than a query-design problem. Needs either a smaller-area chunking strategy (query by zip code or a grid of sub-boxes instead of the whole county) or a paid/dedicated Overpass instance to run reliably. Not blocking anything else; revisit when needed for a specific outreach target.

## Investigated, not used

| Source | Why not |
|---|---|
| London Dial-a-Ride usage statistics (London Datastore) | Real UK paratransit-equivalent service, but the published stats are quarterly, local-authority granularity, and the dataset has not been updated in over a decade. Not usable for hourly demand modeling. Revisit if TfL's Open Data portal exposes anything finer-grained. |

## Modeling protocol (applies to every real-data model, no exceptions)

Strict temporal holdout (last 90 days), seasonal-naive baseline (same zone/hour/day-of-week average) reported alongside every model result, split-conformal or learned-quantile uncertainty. See realdata/README.md for the full method and current numbers, realdata/backtest_and_explain.py for the walk-forward multi-fold version and SHAP explainability, and _legacy/kaggle/README.md for the pretrain-then-finetune transformer.
