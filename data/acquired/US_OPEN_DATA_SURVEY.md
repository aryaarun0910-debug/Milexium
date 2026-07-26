# US open transit & mobility data — survey and acquisition record

Packet `MX-C-US-OPENDATA-006`. Surveyed and acquired 2026-07-25.

The question this answers is not "what data exists" — a great deal exists — but
**"what is rights-clean, free of paid keys, and actually useful to Milexium's
demand models and canonical entities."** Those three filters cut the field hard,
and the honest headline is that they cut it *toward small*: the highest-value
rights-clean US transit data is a few hundred megabytes, while most of the
multi-gigabyte sources are either already held, legally encumbered, or volume
without forecasting value.

All figures below were measured (HTTP `Content-Length`, row counts on the
downloaded object, or the source's own machine-readable metadata) on
2026-07-25, not quoted from memory. Where a number could not be verified it is
marked **unverified**.

---

## 1. Headline numbers

| Question | Answer |
|---|---|
| Catalogued mobility feeds worldwide (Mobility Database) | **3,362** — 2,390 GTFS static, 972 GTFS-Realtime |
| US GTFS **static** feeds | **1,166 catalogued**; 825 active; **816 active and keyless** |
| US GTFS **Realtime** feeds | **445 catalogued**; 413 active; **246 active and keyless** |
| — of those keyless US RT feeds, by entity | 77 VehiclePositions, 78 TripUpdates, 80 ServiceAlerts, 11 combined |
| Distinct US transit providers with a catalogued feed | **768** |
| US states/territories covered | **53** subdivisions |
| NTD-reporting agencies with a monthly ridership series | **834** (Apr 2002 – Sep 2025, 293 months, 19 modes) |
| NTD reporters with an FTA-registered GTFS weblink | **1,539 agency-mode rows**, 1,214 distinct agencies |
| Stops in the federal National Transit Map | **680,275** across 1,209 agencies |
| Routes in the federal National Transit Map | **67,588** across 1,069 agencies |
| "NTD Annual Data" datasets on data.transportation.gov | **57** |
| NTAD (federal transportation atlas) datasets | ~90 (BTS statement, **unverified** independently) |
| Estimated total volume if you pulled *everything* below | low hundreds of GB to ~1 TB |
| Volume that is rights-clean **and** high-value for demand forecasting | **~250 MB** (acquired: 252.4 MB) |

The gap between the last two rows is the finding.

---

## 2. The rights picture, which is the actual constraint

Three tiers, and only the first two are usable without a lawyer.

**Tier 1 — US federal works: unambiguously public domain.**
Not subject to domestic copyright (17 U.S.C. § 105). USDOT's portal states this
in a machine-readable field: NTD datasets carry `licenseId: USGOV_WORKS`,
`termsLink: https://www.usa.gov/government-works`, and a DCAT Common Core
`License: http://www.usa.gov/publicdomain/label/1.0/`. BTS/NTAD datasets carry
the same `usa.gov/publicdomain/label/1.0` label on their data.gov records.
No fee, no attribution obligation, no share-alike, no field-of-use limit, no
revocation clause. **Everything acquired in this packet except one item is
Tier 1.**

**Tier 2 — standard open licences.** Apache-2.0 (Mobility Database catalogue),
ODbL 1.0 (OpenStreetMap / Geofabrik, already held as `osm-dc`). Commercial use
permitted with stated conditions.

**Tier 3 — per-agency developer licence agreements: NOT clean, and this is
where nearly all raw agency GTFS lives.** Worked example, the Chicago Transit
Authority agreement (fetched and read in full at
`transitchicago.com/downloads/sch_data/developers_license_agreement.htm`):

> "CTA grants you a limited, non-exclusive, non-assignable, non-transferable
> and **revocable** license to use … CTA Data … **for the sole purpose of
> assisting mass transportation … riders or in furtherance of promoting public
> transportation**. Except as expressly provided in this Agreement, CTA Data
> may not be used, in whole or in part, for any other purpose."

and

> "Your use of the CTA Data does not in any way grant you the right to sell the
> CTA Data by itself as a stand-alone product … You will not sell, auction or
> barter any CTA Data separate from your application."

plus a termination clause requiring deletion of all CTA Data from your systems.
A purpose-limited, revocable licence with a mandatory-deletion exit is not a
foundation for a B2B decision runtime that other software integrates. **CTA
GTFS was therefore surveyed and deliberately NOT acquired.** The same pattern —
agency-specific terms, not a standard licence — applies to most large US
agencies. MBTA's MassDOT Developers License Agreement is already in this estate
(`gtfs-rt-mbta-vehiclepositions`) carrying an explicit caveat for exactly this
reason.

**The unresolved federal/local conflict.** FTA's own GTFS Weblinks dataset
states: *"As of Report Year (RY) 2023, FTA requires that reporters with fixed
route modes create and maintain a **public domain** general transit feed
specification (GTFS) dataset that reflects their fixed route service."* So the
federal mandate says agency GTFS is public domain, while individual agencies
continue to wrap the same data in restrictive click-through terms. That
conflict is real, unresolved, and means **per-agency review is still required
before any agency feed enters the estate.** It also explains why the
BTS-republished National Transit Map is the right way to get national stop and
route geometry: the federal republication resolves the rights question that
~800 separate agency downloads would not.

Machine-readable licensing in the wild is rare: of 825 active US GTFS static
feeds, only **123** declare any licence URL at all, and only **6** declare a
standard open licence (4 × CC-BY-4.0, 2 × ODC-BY) — all tiny operators (Nevada
County Connects, Avon Transit, Mountain View Community Shuttle, PART NC, Blue
Sky Limo, SF Bay WETA). For GTFS-Realtime, 122 of 246 keyless US feeds declare
a licence URL and **none** is a standard open licence; every one points at an
agency-specific page.

---

## 3. Source-by-source survey

Legend: **Rights** — PD = US federal public domain, OPEN = standard open
licence, AGENCY = per-agency terms needing review, KEY = requires registration
or an API key (out of scope for this packet by hard constraint).

### 3.1 National Transit Database (FTA) — **PD** — ACQUIRED

Repo already held only a *slice*: `forge/business/ntd/raw/{metrics,service}_dr.csv` (2022–24,
demand-response modes only) and `data/curated/panels/ntd_monthly_dr.csv.gz`
(monthly, DR/DT only). The full published tables are far larger.

| Table | ID | Rows | Size | Status |
|---|---|---|---|---|
| Complete Monthly Ridership (all modes) | `8bui-9xvu` | 368,937 | 67.5 MB | **acquired** |
| Service Data & Operating Expenses by Mode, Time Series 2.1 (1991–2024) | `npsm-38gk` | 409,772 | 69.8 MB | **acquired** |
| GTFS Weblinks (live, monthly refresh) | `2u7n-ub22` | 1,539 | 0.41 MB | **acquired** |
| Service Data & Opex by Agency, Time Series 2.2 | `ectq-t3k3` | 243,397 | 36.6 MB | surveyed, skipped (agency-level rollup of `npsm-38gk`) |
| Annual Metrics 2022–24 | `ekg5-frzt` | 11,112 | 2.9 MB | already held DR-filtered |
| Breakdowns | `amkt-4ehs` | 3,731 | small | skipped — vehicle failures, not demand |
| ~50 further NTD Annual Data tables | — | — | few hundred MB total | skipped — facilities, employees, funding sources, safety events, track & roadway |

**Useful for:** the acquired monthly ridership table *is* the target variable at
national breadth. **Honest note on the rest:** the ~50 remaining NTD tables
(stations & facilities, employees by mode, funding sources federal/state/local,
maintenance facilities, guideway age) are genuinely public-domain and genuinely
uninteresting for demand forecasting — they are asset-management and finance
data. Pulling them would be volume without value.

### 3.2 Mobility Database / Transitland GTFS catalogues — **OPEN / KEY**

- **Mobility Database** (`storage.googleapis.com/mdb-csv/sources.csv`, 1.07 MB,
  3,362 rows): **Apache-2.0**, verified from the repo `LICENSE` file and the
  GitHub metadata API (`spdx_id: Apache-2.0`). No key. **ACQUIRED.** Its
  `urls.authentication_type` column is the machine-readable answer to "which US
  feeds can we poll for free", which is precisely this packet's constraint and
  the ADR-0035 observation-supply question.
- **Transitland REST API** (`transit.land/api/v2/rest/*`): returns
  `{"error":"Unauthorized"}` without a key. Free registration, but registration
  is registration — **SKIPPED** per the hard constraint. Noted here so the
  decision is on the record rather than an omission.

**Useful for:** feed discovery and, critically, governed feed *selection* — it
turns "which agency next" from an ad-hoc choice into a filterable question.
The Apache-2.0 grant covers the **catalogue**, not the feeds it points at.

### 3.3 GTFS-Realtime availability — **AGENCY**

246 US RT feeds are active and keyless (77 vp / 78 tu / 80 sa / 11 combined);
another 182 need an API key in a query param or header. A keyless feed snapshot
is ~30–200 KB, so the entire keyless US RT surface is only tens of MB per poll
— **volume is not the constraint here, rights are.** None of the 122 keyless US
RT feeds that declare a licence declares a standard open one.

**Useful for:** directly, the ADR-0035 observation entities
(`VehicleObservation`, `StopTimeObservation`). **Not acquired this packet**
because each additional feed needs its own agency-terms review, and the estate
already carries one worked example (MBTA VehiclePositions) with its caveat
recorded. The acquired Mobility Database catalogue is the input that makes the
next such review cheap and governed.

### 3.4 National Transit Map / NTAD (BTS) — **PD** — ACQUIRED

BTS ingests participating agencies' GTFS and republishes it as a federal
public-domain product with an explicit `usa.gov/publicdomain/label/1.0` licence.

| Layer | Rows | Size | Status |
|---|---|---|---|
| Stops | 680,275 across 1,209 agencies | 104.3 MB | **acquired** |
| Routes | 67,588 across 1,069 agencies (61,083 bus, 3,096 rail, 812 light rail, 705 metro, 389 ferry) | 9.3 MB | **acquired** |
| Agencies (addresses) | ~1,200 | small | skipped — the weblinks table already carries agency identity |

**Useful for:** the rights-clean national spatial substrate. Both layers carry
`ntd_id`, so they join straight onto the NTD ridership panel: **585 of the 834
NTD-ridership agencies have stop geometry**, 565 have route geometry, 590 have
a registered GTFS weblink.

### 3.5 NYC TLC — **AGENCY (permissive in practice)** — mostly already held

Already held: **62 GB / 422 files** — `fhvhv` 88 months (2019-02 → 2026-05,
39.9 GB), `yellow` 185 months (2011-01 → 2026-05) and `green` 149 months
(2014-01 → 2026-05), together 22.1 GB.

**NOT held:** `fhv_tripdata_*` — the *non*-high-volume for-hire records (black
car, livery, lux limo), ~23 MB/month × ~130 months ≈ **3 GB**; the taxi zone
shapefile (1.0 MB) and zone lookup (12 KB); and yellow 2009–2010.

**Honest assessment:** not worth pulling. `fhv` is a shrinking, poorly-populated
legacy segment (many months carry dispatching-base rows with no coordinates),
and the repo already derives `nyc_fhvhv_zone_hour.parquet` from the segment that
matters. The zone lookup is trivially re-fetchable when needed. **Skipped.**

### 3.6 Chicago — **AGENCY / restrictive**

- **TNP (rideshare) trips**, `data.cityofchicago.org`: already distilled into
  `data/curated/panels/chicago_tnp_zone_hour.csv.gz` (18.8 MB). The raw Socrata
  table is tens of GB; the hourly zone panel is the useful form and it is held.
- **Divvy bikeshare**, `divvy-tripdata.s3.amazonaws.com`: 25.5 MB/month,
  ~130 months ≈ **3 GB**. Governed by the Lyft/Divvy Data License Agreement,
  which is a bespoke agreement, not a standard licence — **Tier 3, needs
  review**. Also: bikeshare demand is a different process from transit demand.
  **Skipped** on both rights and value.
- **CTA GTFS**, 67.9 MB: rights not clean (see §2). **Skipped.**

### 3.7 MTA / New York State open data — **AGENCY (data.ny.gov terms)**

Already held: `mta_bus_route_hour.csv.gz` (86.9 MB) and
`mta_subway_station_hour.csv.gz` (105.4 MB), plus the Access-A-Ride hourly
borough panel — all derived from `data.ny.gov` Socrata endpoints. MTA publishes
a large and genuinely good open-data catalogue (subway origin-destination
estimates, hourly ridership by station, bus speeds, on-time performance).

**Honest assessment:** the two highest-value MTA series are already in the repo
in their aggregated form, and they are the ones that produced the measured
transfer-learning gain. Additional MTA tables are incremental. **Skipped this
packet.**

### 3.8 State DOT open-data portals — **mixed, mostly AGENCY**

53 US subdivisions have catalogued feeds. State portals (data.ca.gov,
data.ny.gov, data.wa.gov, data.texas.gov, …) each carry their own terms; a few
apply a state open-data licence, most defer to the publishing agency. There is
no single national rights position, which is precisely why the federal
NTD/NTAD route was preferred here. **Not acquired** — surveying 50 separate
terms-of-use pages is a poor use of the constraint budget when BTS already
publishes the national aggregate as public domain.

### 3.9 data.gov transit holdings — **PD (federal) / mixed (harvested)**

data.gov's CKAN API (`/api/3/action/package_search`) now returns HTTP 404 and
the catalogue UI is JS-rendered, so **a dataset count could not be
machine-verified** and is reported as unverified rather than guessed. What was
verified directly: **57** "NTD Annual Data" datasets on data.transportation.gov,
and the NTAD National Transit Map records carrying explicit public-domain
labels. data.gov is largely a *harvester* — the authoritative copies live on
data.transportation.gov and the BTS geoplatform, which is where this packet
went.

### 3.10 NHTS — National Household Travel Survey (FHWA/ORNL) — **PD**

`nhts.ornl.gov/assets/2022/download/csv.zip` = **3.9 MB**;
`.../2016/download/csv.zip` (NHTS 2017) = **83.7 MB**. Downloadable with no
key. Federal work, public domain. (The geographically-detailed restricted-use
version requires an application — out of scope.)

**Honest assessment: low value here, and this is worth stating plainly.** NHTS
is a cross-sectional household travel *survey* — it describes national travel
behaviour, not any agency's ridership over time. Milexium's models forecast
demand time series for a named agency; a national survey with no agency
identity and no time index cannot enter that feature space without heavy
assumption-making. Useful for market sizing (which the repo already does in
`forge/business/ntd/market_sizing.md`), not for forecasting. **Skipped.**

### 3.11 Census LODES / ACS journey-to-work — **PD**

LODES8 per-state files at `lehd.ces.census.gov/data/lodes/LODES8/<st>/`:
OD `main` is 92.0 MB for CA, 39.8 MB for NY, 28.0 MB for IL; RAC 5.9 MB and
WAC 2.5 MB for NY. Across 51 states × 3 file types × ~20 vintages the full
LODES corpus is **well over 100 GB**. Public domain (Census Bureau / LEHD).
ACS journey-to-work is already partly used — `forge/business/ntd/census_latent_demand.csv`
comes from `api.census.gov/data/{year}/acs/acs5/profile`.

**Honest assessment: real but limited value, and large.** LODES gives
block-level home→work flows — an excellent *spatial* prior for where demand
should exist. But it is annual and static: it has essentially no temporal
signal, and Milexium's models are hourly/daily/monthly time series where
demand-history lags carry ~80% of the signal (per `data/curated/LEAKAGE_AUDIT.md`
and the SHAP work). Adding a static cross-sectional layer to a lag-dominated
temporal model is the classic way to add gigabytes and gain nothing.
**Skipped**, and flagged as a candidate only if and when a *new-territory,
no-history* cold-start model is built — which is the one place it would
genuinely earn its space.

### 3.12 NOAA weather — **PD**

GHCN-Daily `by_year/2024.csv.gz` = **164.2 MB/year** (all global stations);
the full by-year archive is roughly **12 GB**. Station metadata
`ghcnd-stations.txt` 10.9 MB, `ghcnd-inventory.txt` 36.0 MB. NCEI
Local Climatological Data ~6.2 MB per station-year. All public domain.

**Honest assessment: measured to be worthless here, and the repo already has
the receipt.** `data/curated/WEATHER_ABLATION_RESULTS.md` ablated weather features
on the AAR holdout and found R² 0.9851 (no weather) vs 0.9853 (daily) vs 0.9849
(hourly) vs 0.9857 (both) — all inside noise. The repo's own conclusion was
"weather adds essentially nothing, and we say so." Acquiring 12 GB of GHCN to
re-learn that would be the definition of volume without value. **Skipped, with
evidence.**

### 3.13 OpenStreetMap extracts — **OPEN (ODbL 1.0)**

Geofabrik: `us-latest.osm.pbf` = **11.48 GB**; `new-york-latest.osm.pbf` =
471 MB; District of Columbia = 21 MB — **already held** as `osm-dc`
(ODbL 1.0, commercial use permitted with attribution and share-alike on derived
databases).

**Honest assessment:** the full US extract is the single largest item that
would fit this packet's 15 GB budget, and it is the clearest example of volume
without current value. `forge/legacy/third_party/VENDORING_PROCESS.md` records that no
routing engine (OSRM/Valhalla) has cleared the vendoring gate, so 11.5 GB of
road network would sit inert. The DC extract already proves the `networks/`
zone path end-to-end. **Deliberately skipped** — pull a metro extract when a
concrete routing capability needs it, per the blueprint's own
"infrastructure before demand" warning.

---

## 4. What was acquired

All six went through `themis/estate/acquire.py` — manifest → free-space guard
→ quarantine → sha256 → content-addressed promotion → catalog record — with
`back_with_object_store=True`, so every object is also mirrored into the local
MinIO (`milexium-artifacts`) under a key equal to its sha256.

| dataset_id | Size | Rows | Licence | Zone |
|---|---|---|---|---|
| `ntd-monthly-ridership-all-modes` | 67.51 MB | 368,937 | PD — USGOV_WORKS | raw/public |
| `ntd-service-opex-by-mode-timeseries` | 69.78 MB | 409,772 | PD — USGOV_WORKS | raw/public |
| `ntd-gtfs-weblinks` | 0.41 MB | 1,539 | PD — USGOV_WORKS | raw/public |
| `mobility-database-catalog` | 1.07 MB | 3,362 | Apache-2.0 | raw/public |
| `ntm-stops-national` | 104.32 MB | 680,275 | PD — usa.gov PD Label 1.0 | raw/public |
| `ntm-routes-national` | 9.28 MB | 67,588 | PD — usa.gov PD Label 1.0 | raw/public |
| **Total** | **252.4 MB** | **1,531,677** | | |

Estate free space went 315.13 GB → 316.86 GB across the run (other processes
were freeing space concurrently); estate retained total is now 0.2856 GB.
Budget was ~15 GB; **1.7% of it was used**, deliberately.

Two objects (`ntm-stops-national`, `ntm-routes-national`) are promoted with a
`.bin` extension because their download URLs carry a query string and
`acquire()` derives the suffix from the URL path. The bytes are plain CSV and
the sha256 content address is authoritative; this is recorded in their
manifests rather than worked around by modifying `themis/estate`.

---

## 5. Which of these will actually improve the demand models

Stated honestly, because two of the six are infrastructure rather than signal.

**Will improve the models — with a measured reason.**
`data/curated/TRANSFER_RESULTS.md` already established that pretraining on other
cities' transit corpora and fine-tuning on the target agency lifts AAR R² from
0.9862 to 0.9913 and cuts MAE from 20.10 to 17.18 — **a 15% error reduction**.
That result was obtained with pretraining on three panels (Chicago TNP, MTA bus,
MTA subway). `ntd-monthly-ridership-all-modes` multiplies that pretraining
corpus: the repo previously held only the DR/DT slice — 151,991 rows across 637
agencies — and the full table adds **216,946 further rows (+143%) and 197
further agencies**, including 143,804 fixed-route bus rows. If cross-corpus
pretraining is the mechanism that works, this is the largest single expansion of
that mechanism's input available for free anywhere, and it is unambiguously
public domain. **This is the acquisition that matters.**

`ntd-service-opex-by-mode-timeseries` is second: 34 years of per-agency service
supply (revenue vs actual hours/miles, deadhead, days of service, speed) gives
supply-side covariates and normalisers (trips per revenue hour) that the demand
panel alone cannot provide, and it feeds the deadhead work behind ADR-0039.

**Will not improve the models directly — and are not pretending to.**
`ntd-gtfs-weblinks`, `mobility-database-catalog`, `ntm-stops-national` and
`ntm-routes-national` add **zero** forecasting features today. They are
*join infrastructure and rights infrastructure*: they make the NTD panel
addressable (585/834 agencies now have stop geometry, 590 have a registered
feed URL), they tell us which feeds can be polled for free, and they supply a
rights-clean national stop and route inventory that per-agency GTFS acquisition
could not. Their value is that they make the *next* packet cheap and governed.
`ntm-stops-national` at 104 MB is the largest object acquired and contributes
nothing to any current model — that is a deliberate, stated trade.

**Gaps this surfaced, recorded rather than papered over.**
Milexium has no canonical `Stop` entity and no canonical `Route` entity, even
though `StopTimeObservation.stop_id` already references stop identity as an
opaque string. It also has no aggregate-ridership entity, so a 369k-row
agency-mode-month demand panel maps to `canonical_contract: none-yet`. These are
the same class of operational-entity gap ADR-0035 recorded for vehicle
observations; they are noted in the manifests and left for a canonical packet
to decide, not invented here.
