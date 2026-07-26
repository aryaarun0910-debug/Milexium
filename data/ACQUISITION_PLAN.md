# Acquisition plan — closing the deadhead observation gap

Research scouting pass, 2026-07-25. **Nothing was acquired, downloaded, or
registered for in producing this document.** It is a plan for the founder to act
on.

Builds on `data/US_OPEN_DATA_SURVEY.md` and ADR-0050. Those two answered
*"what US open transit data is worth having for the demand models."* This one
answers a narrower and harder question: **what would let Milexium measure
vehicle movement instead of inferring it.**

---

## 0. The gap, stated precisely

Everything the estate knows about deadhead comes from
`ntd-service-opex-by-mode-timeseries` — the NTD Service form. That is **one
self-reported deadhead figure per operator, per mode, per year.** For a runtime
whose job is to explain *why this trip could not be scheduled*, an annual
aggregate is not evidence; it is a prior. The audit trail cannot cite it against
a specific block on a specific day.

There are exactly three ways to do better, and they are not equivalent:

| Tier | What it gives | Where it comes from |
|---|---|---|
| **Inferred** (today) | one number per operator-mode-year | NTD Service form |
| **Reconstructed** | scheduled deadhead per block per service day — the geographic and temporal gap between the end of trip *N* and the start of trip *N+1* in the same `block_id` | GTFS `trips.txt` + `stop_times.txt` + `stops.txt` |
| **Observed** | where a vehicle actually was between revenue trips | GTFS-Realtime VehiclePositions archives, raw AVL, TIDES `vehicle_locations` |

The **Reconstructed** tier is the one the estate is structurally ready for and
does not currently exploit — Program A landed `Block`, `RunPiece` and
`DeadheadSegment` as canonical entities (commit `6d55004`) and there is no
national input feeding them. The **Observed** tier is the actual capability
jump, and it is where the rights get hard.

Three things changed since the survey that make this tractable:

1. **FTA states in writing that GTFS submitted to the NTD enters the public
   domain.** The survey noted the federal/local conflict; it did not push on the
   federal side of it. That statement, if it holds, is the rights basis for a
   national schedule harvest — and the estate already holds the index
   (`ntd-gtfs-weblinks`, 1,539 rows / 1,214 agencies).
2. **A free, keyless, US-wide GTFS-Realtime archive now exists** (`gtfsrt.io`).
   The survey correctly said RT is "under-exploited"; it assumed we would have
   to poll forward from today. We would not — history exists.
3. **Caltrans publishes a statewide GTFS schedule assembly under CC-BY** with an
   explicit "No restrictions on public use" rights field. That is the
   Reconstructed tier for ~California's whole operator set, rights-clean, today.

**A note on the numbers below.** The survey measured every figure it quoted
(`Content-Length`, row counts). This pass did not — the brief forbids
downloading. **Every size in this document is an estimate and is labelled as
one.** Where a licence could not be read directly it is marked *unverified*.
Verification failures are logged in §6 rather than papered over.

---

## 1. Ranked shortlist

Ranked by capability delta — what Milexium could do afterwards that it cannot do
now — not by size, ease, or availability.

| # | Source | Tier it unlocks | Rights | Effort |
|---|---|---|---|---|
| 1 | gtfsrt.io GTFS-RT archive | **Observed** | per-feed, unresolved | high |
| 2 | National GTFS harvest via NTD weblinks | **Reconstructed** ×1,214 ops | federal PD, needs written confirmation | high |
| 3 | Cal-ITP GTFS-Ingest Pipeline Dataset | **Reconstructed** ×~200 ops | **CC-BY, clean** | low |
| 4 | Cal-ITP Average Transit Speeds by Stop / Route | observed running times | **CC-BY, clean** | very low |
| 5 | Census ACS 5-year (API) | DRT cold-start demand | **PD, clean** | low |
| 6 | LEHD LODES8 | DRT cold-start spatial prior | **PD, clean** | medium |
| 7 | EPA Smart Location Database v3 | built-environment covariates | PD, *unverified label* | low |
| 8 | SSA OASDI/SSI by county | ADA-eligibility proxy | **PD, clean** | low |
| 9 | Self-archive keyless RT feeds | **Observed**, from today forward | per-feed | medium, slow payoff |

---

### 1. gtfsrt.io — historical GTFS-Realtime archive

- **What it is.** A continuously-updated archive of GTFS-Realtime feeds from US
  transit agencies, operated by Jarvus Innovations (the Cal-ITP data-infra
  contractor). Raw protobuf snapshots organised by hour, plus daily-compacted
  Parquet for analytics. Hive-style partitioning.
- **URL / access.** <https://gtfsrt.io/>
  - Parquet: `http://parquet.gtfsrt.io/<feed_type>/date=<date>/base64url=<base64url>/data.parquet`
  - Protobuf: `http://protobuf.gtfsrt.io/<feed_type>/date=<date>/hour={ISO_HOUR}/base64url=<base64url>/{timestamp}.pb`
  - Archiver source: <https://github.com/JarvusInnovations/gtfs-realtime-archiver>
- **Account / key.** None. The site states: *"No authentication required — all
  data is publicly accessible."*
- **Cadence.** Continuous ingest; Parquet compaction runs daily.
- **Size.** **Unverified.** The inventory table is JS-rendered and I could not
  read feed counts or byte totals. Order-of-magnitude reasoning only: a
  VehiclePositions feed polled ~1×/min for a mid-size agency is roughly
  10–100 MB/day as Parquet. Three feeds × 90 days is therefore plausibly
  3–30 GB. **Probe before committing.**

**What it lets Milexium do that it cannot today.** This is the only item on the
list that reaches the **Observed** tier. Joined against `block_id` from a GTFS
schedule (items 2/3), a VehiclePositions history lets the runtime answer, for a
real operator on a real day: *the vehicle finished trip N at 14:07 at stop X,
and appeared at the start of trip N+1 at 14:31 at stop Y — that is 24 minutes
and 3.1 km of non-revenue movement.* That is a measured `DeadheadSegment`. It
also yields observed inter-stop running times, which replaces the scheduled or
Euclidean travel-time matrix the DARP solver currently has to assume, and gives
the audit trail an empirical basis for "no vehicle could have reached this
pickup in time."

**Rights verdict: FREE AND KEYLESS, BUT THE DATA CARRIES NO GRANT.**
The repository is **AGPL-3.0** — that licenses the *archiver software*. I found
**no data licence, no terms-of-use page, and no disclaimer** on either the site
or the repo. The bytes are verbatim upstream agency GTFS-Realtime, so **each
feed's own agency terms still govern** — the same Tier 3 problem the survey
documented for CTA. An archive republishing a feed does not launder that feed's
licence. **Verdict: capability #1, rights unresolved. Acquire feed-by-feed
only, and only for feeds whose upstream rights are independently clean** —
cross-reference `mobility-database-catalog.urls.license` (already held) and the
FTA public-domain basis in item 2.

---

### 2. National GTFS schedule harvest, via the NTD GTFS Weblinks table

- **What it is.** Not a new dataset — a new *use* of one already held.
  `ntd-gtfs-weblinks` (`2u7n-ub22`, 1,539 agency-mode rows, 1,214 distinct
  agencies) is FTA's register of every NTD reporter's public GTFS URL. Following
  those URLs yields full GTFS bundles including `trips.txt` (which carries
  `block_id`), `stop_times.txt`, and `stops.txt`.
- **URLs.**
  - Index (held): <https://data.transportation.gov/Public-Transit/General-Transit-Feed-Specification-Weblinks/2u7n-ub22>
  - FTA data product page: <https://www.transit.dot.gov/ntd/data-product/2023-annual-database-general-transit-feed-specification-gtfs-weblinks>
  - The 1,539 target URLs are the `gtfs_weblink` column of the held CSV.
- **Account / key.** None for the index. Individual agency feeds are mostly
  keyless; some sit behind a developer portal.
- **Cadence.** Index refreshes monthly. Agency feeds change on service-change
  boundaries — roughly quarterly, some weekly.
- **Size (estimate).** Agency GTFS zips run from ~0.5 MB (rural single-route) to
  ~68 MB (CTA, measured by the survey). Assuming a median near 3 MB and a long
  right tail: **4–8 GB compressed, 25–50 GB expanded** for all 1,214.
  `stop_times.txt` dominates — it scales with trips × stops and is typically
  80–90% of an expanded bundle.

**What it lets Milexium do that it cannot today.** Reconstructed deadhead at
national operator breadth. Every `Block` in `trips.txt` gives an ordered chain of
trips; the gap between consecutive trips in a block is a `DeadheadSegment` with a
computable duration and an origin/destination stop pair. That converts one
annual NTD number per operator into **a per-block, per-service-day distribution**
for up to 1,214 operators. It is the input Program A's canonical entities were
built for and currently do not have. It also gives the first honest answer to
"how much of this operator's fleet-time is non-revenue, and where does it
happen" — which is the commercial pitch.

**Rights verdict: FEDERAL PUBLIC DOMAIN ON FTA'S OWN STATEMENT — BUT GET IT IN
WRITING BEFORE ACQUIRING.**
FTA's requirement states that as of Report Year 2023, reporters with fixed-route
modes must create and maintain a **public domain** GTFS dataset, and that *"upon
publication, all GTFS data submitted to the NTD will enter the public domain."*
Separately, BTS records that pre-mandate NTM participants granted USDOT a
**CC-BY-3.0 US** licence via the FACES opt-in.

Against that sits the survey's §2 finding, which I did not overturn: large
agencies continue to wrap the identical data in revocable, purpose-limited
click-through licences (CTA's is quoted in full in the survey; CapMetro's is the
same pattern — *"non-exclusive, limited and revocable"*). **The conflict is real
and unresolved, and it is not ours to resolve by assumption.** This is a
one-email problem, not a lawyer problem — see Action 3. Until that email is
answered, this ranks #2 rather than #1 despite having the larger operator count.

---

### 3. Cal-ITP GTFS-Ingest Pipeline Dataset (Caltrans, data.ca.gov)

- **What it is.** Caltrans collects every California transit operator's GTFS
  nightly and publishes the statewide assembly as **29 flat CSVs** — one per GTFS
  table, concatenated across operators, with operator identity preserved.
  Includes `trips.csv` (**with `block_id`**), `stop_times.csv`, `stops.csv`,
  `routes.csv`, `calendar.csv`, `calendar_dates.csv`, `shapes.csv`, plus
  Cal-ITP's own `gtfs_datasets.csv`, `organizations_latest_with_caltrans_district.csv`
  and `provider_gtfs_data.csv` for operator identity.
- **URL.** <https://data.ca.gov/dataset/cal-itp-gtfs-ingest-pipeline-dataset>
  Direct resources (stable CKAN paths under dataset `de6f1544-…`):
  - `trips.csv` — `…/resource/0e4da89e-9330-43f8-8de9-305cb7d4918f/download/trips.csv`
  - `stop_times.csv` — `…/resource/d31eef2f-e223-4ca4-a86b-170acc6b2590/download/stop_times.csv`
  - `stops.csv` — `…/resource/8c876204-e12b-48a2-8299-10f6ae3d4f2b/download/stops.csv`
  - `routes.csv` — `…/resource/c6bbb637-988f-431c-8444-aef7277297f8/download/routes.csv`
  - `calendar.csv` — `…/resource/a79f10b8-b322-43f3-b3f4-ba46a8dbe9ab/download/calendar.csv`
  - `gtfs_datasets.csv` — `…/resource/e4ca5bd4-e9ce-40aa-a58a-3a6d78b042bd/download/gtfs_datasets.csv`
- **Account / key.** **None.** Plain HTTPS CSV.
- **Cadence.** Monthly (portal field). Last updated 2026-07-21; created 2021-06-09.
- **Size (estimate).** Not published on the page. `stop_times` statewide is the
  driver — plausibly **1–5 GB**; everything else together likely **<500 MB**.

**What it lets Milexium do that it cannot today.** Exactly item 2's capability,
for California's operator set, **with no rights question and no harvest
engineering** — 29 URLs instead of 1,539. It is the correct *first* move: it
proves the block→deadhead reconstruction end-to-end on real multi-operator data
before anyone spends a week writing a 1,539-URL fetcher against unresolved
rights. If the reconstruction does not produce a usable `DeadheadSegment`
distribution here, item 2 is not worth attempting.

**Rights verdict: CLEAN. COMMERCIAL USE PERMITTED.**
The portal declares **License: Creative Commons Attribution** and
**Rights: "No restrictions on public use"**, Public Access Level: Public. This is
consistent with Caltrans' own California Transit Data Guidelines, which direct
agencies to license GTFS under ODC-BY or CC-BY and explicitly warn against
share-alike. **One gap:** the dataset page names the licence family but not the
*version*. Capture `license_id` / `license_url` from the CKAN API
(`https://data.ca.gov/api/3/action/package_show?id=cal-itp-gtfs-ingest-pipeline-dataset`)
into the manifest rather than assuming 4.0.
Licence text: <https://creativecommons.org/licenses/by/4.0/> (version to be
confirmed from the CKAN field, not from this document).

---

### 4. Cal-ITP Average Transit Speeds by Stop / by Route (Caltrans)

- **What it is.** 20th/50th/80th-percentile transit speeds, all-day and peak, on
  stop-to-stop segments (subdivided at 1 km where stop spacing exceeds that),
  **estimated directly from GTFS-Realtime vehicle positions** for every CA
  operator that publishes RT. Plus an aggregate by route-direction with trip
  counts.
- **URLs.**
  - <https://data.ca.gov/dataset/average-transit-speeds-by-stop>
  - <https://data.ca.gov/dataset/average-transit-speeds-by-route>
  - CSV (route): `https://gis.data.ca.gov/api/download/v1/items/071df783099f4224b7ebb54839eae007/csv?layers=0`
  - Also GeoJSON / Shapefile / FileGDB / ArcGIS REST.
- **Account / key.** None.
- **Cadence.** "Irregular" per the portal. Last updated 2026-07-25.
- **Size (estimate).** Segment-level geometry statewide: **50–400 MB** depending
  on format. GeoJSON will be the largest; take CSV.

**What it lets Milexium do that it cannot today.** It is *observed* running time
by segment and time-of-day, delivered pre-aggregated and rights-clean — Caltrans
has already done the GTFS-RT processing whose raw inputs we cannot cleanly hold.
It replaces scheduled or straight-line travel times in the DARP feasibility check
with empirical percentiles, and a 20th/80th spread is exactly the input an
honest "this trip was infeasible" explanation needs. It does **not** contain
deadhead — it is revenue-segment speed only. Cheap, small, immediately useful,
which is why it ranks above the demographic sources despite a smaller conceptual
jump.

**Rights verdict: CLEAN.** License: **Creative Commons Attribution**;
Rights: **"No restrictions on public use."** Same version caveat as item 3.

---

### 5. Census ACS 5-year estimates, via the Census Data API

- **What it is.** Tract- and block-group-level estimates for the populations that
  actually generate demand-response trips. The tables that matter here:
  - `S1810` — Disability Characteristics (subject table, pre-computed percentages)
  - `B18105` — ambulatory difficulty (serious difficulty walking/climbing stairs) — the closest open proxy for ADA paratransit eligibility
  - `B18101` — disability by sex by age
  - `B01001` — sex by age → 65+, 75+, 85+ geography
  - `B08201` — household size by vehicles available → zero-vehicle households
  - `B08301` — means of transportation to work
- **URL.** API root `https://api.census.gov/data/{year}/acs/acs5` and
  `…/acs5/subject`. Dataset docs:
  <https://www.census.gov/data/developers/data-sets/acs-5year.html>
- **Account / key.** **Free API key required.** Sign-up:
  <https://api.census.gov/data/key_signup.html>
- **Cadence.** Annual (new 5-year vintage each December).
- **Size (estimate).** Pulling the six tables above for all US tracts is
  **tens of MB**, not GB. This is a small, surgical pull.

**What it lets Milexium do that it cannot today.** The estate has
`business/ntd/census_latent_demand.csv` from the ACS *profile* endpoint — a coarse slice.
Disability, senior geography, and zero-vehicle households at tract level are the
denominators of demand-response demand. Today, if an operator asks *"what
should our DRT demand be in this new service zone"*, Milexium has no answer
without ridership history. This gives a **cold-start** answer: an eligible-
population estimate per zone. The survey was right that static covariates add
nothing to a lag-dominated warm-start model — that is not what this is for.

**Rights verdict: CLEAN, WITH A REQUIRED ATTRIBUTION LINE.**
Terms: <https://www.census.gov/data/developers/about/terms-of-service.html>.
Commercial use is permitted — the terms grant the right to *"develop a service…
to search, display, analyze, retrieve, view and otherwise 'get' information from
Census Bureau data."* Two binding conditions:
1. Display prominently: *"This product uses the Census Bureau Data API but is
   not endorsed or certified by the Census Bureau."*
2. **Do not use the data, alone or combined with any other data, to identify any
   individual person, household, business or other entity.** Milexium must not
   join ACS microgeography to operator trip records in a way that re-identifies
   riders. That is a real constraint on the tenant-isolation boundary, not
   boilerplate.
Census is also free to limit or block access for policy violations — so the key
is revocable, though the underlying data (a federal work) is not.

---

### 6. LEHD LODES8 — origin-destination employment statistics

- **What it is.** Census block-level home→work flows (`OD`), plus residence-area
  (`RAC`) and workplace-area (`WAC`) characteristics, per state, per year.
- **URL.** `https://lehd.ces.census.gov/data/lodes/LODES8/<st>/` — e.g.
  `…/ca/od/ca_od_main_JT00_2022.csv.gz`. Tech doc:
  <https://lehd.ces.census.gov/doc/help/onthemap/LODESTechDoc.pdf>
- **Account / key.** None.
- **Cadence.** Annual.
- **Size.** The survey measured per-state files (CA OD main 92.0 MB, NY 39.8 MB,
  IL 28.0 MB) and put the full corpus at **>100 GB**. **Do not take the corpus.**
  Take OD + RAC + WAC for the ~6 states where Milexium actually has or targets an
  operator, latest vintage only: **~250–500 MB**.

**What it lets Milexium do that it cannot today.** Same cold-start argument as
item 5 — a spatial prior for where trip demand should exist in a zone with no
history. The survey skipped it, correctly, for the warm-start temporal models,
and explicitly flagged it as *"a candidate only if and when a new-territory,
no-history cold-start model is built."* That is the model this plan is arguing
for. **I agree with the survey's reasoning and disagree with applying it here —
the condition it named has now arrived.** Scope it to states, not nationally.

**Rights verdict: PUBLIC DOMAIN (US federal work, Census/LEHD), commercial use
permitted.** No click-through, no key. Honest caveat: **I did not find an
explicit machine-readable licence field on `lehd.ces.census.gov`** — the basis is
17 U.S.C. § 105 plus the Census Bureau's general terms, not a per-dataset label
like the USGOV_WORKS field on data.transportation.gov. That is a weaker
declaration than the NTD sources carry and the manifest should say so rather
than claim parity.

---

### 7. EPA Smart Location Database v3

- **What it is.** ~90 built-environment attributes per census block group,
  nationwide: employment and housing density, land-use diversity/entropy,
  street-network design (intersection density, %4-way), destination
  accessibility, and transit-service measures.
- **URL.** <https://www.epa.gov/smartgrowth/smart-location-mapping>
  Direct: `https://edg.epa.gov/EPADataCommons/public/OA/SLD/SmartLocationDatabaseV3.zip`
- **Account / key.** None.
- **Cadence.** Effectively none — v3 released 2021, prior versions 2013 and 2011.
  **This is a static snapshot, not a series.**
- **Size (estimate).** Block-group national with ~90 attributes: **~1–2 GB**
  zipped. Unverified.

**What it lets Milexium do that it cannot today.** The single best available
open answer to "is this zone the kind of place that generates demand-response
trips" — low density, poor walkability, few destinations within reach is
precisely the DRT-viable signature. Cold-start only, same as items 5–6.

**Rights verdict: PUBLIC DOMAIN, BUT THE LABEL IS UNVERIFIED.** EPA is a US
federal agency so § 105 applies, and the file sits on EPA's public data commons.
**However, the landing page carries no explicit licence or terms-of-use
statement** — I looked and it is not there. Ranked 7th partly for that reason.
Before acquisition, pull the ISO/FGDC metadata record from EPA's Environmental
Dataset Gateway and record the `useConstraints` field verbatim in the manifest.
If it comes back empty, declare it as "US federal work, § 105, no explicit
label" and not as "public domain, declared."

---

### 8. SSA — OASDI and SSI beneficiaries by state and county

- **What it is.** Counts of Social Security beneficiaries by county, broken out
  by benefit type — including **disabled workers** and **aged 65+** — plus SSI
  recipients by county including blind-and-disabled categories.
- **URL.** <https://www.ssa.gov/policy/docs/statcomps/oasdi_sc/index.html>
  (annual, most recent 2024); machine-readable via SSA Open Data
  <https://www.ssa.gov/data/>.
- **Account / key.** None.
- **Cadence.** Annual.
- **Size.** Trivial — **single-digit MB**. County-level, ~3,143 rows per year.

**What it lets Milexium do that it cannot today.** A second, administratively-
derived ADA-eligibility proxy that is independent of the ACS survey estimate.
Two independent proxies that agree is a defensible cold-start number; one survey
estimate is a guess. Cheap enough that there is no reason not to.

**Rights verdict: PUBLIC DOMAIN (US federal work).** Practical caveat: the
primary publication is **PDF**, which is a poor ingest target. Take the SSA Open
Data / data.gov CSV distributions, not the statistical-supplement PDFs, and if
only PDFs exist for a given year, skip that year rather than parse it.

---

### 9. Self-archiving the keyless US GTFS-RT VehiclePositions feeds

- **What it is.** Not an acquisition — a standing capability. The estate already
  holds `mobility-database-catalog`, whose `urls.authentication_type` column
  identifies **77 active, keyless US VehiclePositions feeds**. Poll them, store
  the protobufs.
- **Account / key.** None, by construction — that is what "keyless" means.
- **Size (estimate).** The survey measured a keyless RT snapshot at 30–200 KB. At
  77 feeds × 1 poll/min × 100 KB ≈ **11 GB/day raw**, ~1–2 GB/day as compacted
  Parquet. **Scope hard: 5–10 feeds, not 77.**

**What it lets Milexium do that it cannot today.** The Observed tier, on data we
control, with a provenance chain we wrote ourselves. Ranked last among the yeses
for one reason: **it produces nothing until it has been running for months.** It
is a decision to make now and harvest later, and it does not solve the rights
question — a keyless feed is not a licensed feed.

---

## 2. Rights verdicts — summary

| Source | Commercial use? | Licence | Where it says so |
|---|---|---|---|
| Cal-ITP GTFS-Ingest | **Yes** | CC Attribution (version unconfirmed) | data.ca.gov dataset page: License "Creative Commons Attribution", Rights "No restrictions on public use" |
| Cal-ITP Transit Speeds | **Yes** | CC Attribution (version unconfirmed) | same, both dataset pages |
| Census ACS API | **Yes**, with disclaimer + no-reidentification | US federal work + API ToS | <https://www.census.gov/data/developers/about/terms-of-service.html> |
| LEHD LODES8 | **Yes** | US federal work, 17 U.S.C. § 105 | no per-dataset label found — weaker declaration |
| SSA OASDI/SSI | **Yes** | US federal work | ssa.gov/data |
| EPA SLD v3 | **Probably** | US federal work; **no explicit label on the page** | *unverified* — pull EDG metadata `useConstraints` |
| NTD GTFS weblink feeds | **Probably yes** | FTA: GTFS submitted to NTD "will enter the public domain"; NTM pre-mandate CC-BY-3.0 US | <https://www.transit.dot.gov/ntd/data-product/2023-annual-database-general-transit-feed-specification-gtfs-weblinks> — **conflicts with agency click-throughs; confirm in writing** |
| gtfsrt.io archive | **Unresolved** | AGPL-3.0 covers the *code only*; **no data licence stated** | <https://github.com/JarvusInnovations/gtfs-realtime-archiver> |
| Bus Observatory | **NO** | CC BY-NC 4.0 | <https://api.busobservatory.org/> — "All data is licensed under a CC BY-NC 4.0 license" |
| Transitland feed archive | **NO** (free tier) | free credits are "for Hobbyists and Academics performing non-commercial work" | <https://www.transit.land/plans-pricing/> |
| California TIDES | n/a — **paid access** | requester-pays GCS bucket | <https://tides.dds.dot.ca.gov/> |
| MBTA / MassDOT | **Unverified** | MassDOT Developers License Agreement (PDF) | <https://www.mass.gov/massdot-developers-data-sources> — already flagged unverifiable in ADR-0050 |
| MTA / NYC | **Doubtful** | MTA terms; commercial/ad-supported apps "may be charged a license fee" | <https://www.mta.info/terms-and-conditions> |
| CTA, CapMetro, 511 SF Bay, SamTrans | **NO** | "non-exclusive, limited and **revocable**", purpose-limited | agency developer pages; CTA quoted in full in the survey |

---

## 3. Founder action list

Numbered, in order. Everything here is free. **Nothing below costs money and
nothing below requires a credit card.** If any page asks for payment details,
stop and flag it — that means I got something wrong.

**Register for exactly one thing.**

1. **Get a Census Data API key.**
   Go to <https://api.census.gov/data/key_signup.html>. Tick the terms-of-service
   box. You will be asked for an **organisation name** and an **email address**.
   Put `Loughborough University` — that is accurate and there is no verification
   step, so nothing turns on it. The key arrives by email, usually within a few
   minutes, occasionally an hour. **Do not paste the key into any file in this
   repo** — it goes in the local environment only.
   *Expect:* one email, one string, no approval queue, no cost, no renewal.

**Send two emails. Both are asks, not applications.**

2. **Ask FTA to confirm the GTFS public-domain position in writing.**
   FTA's NTD data-product page states that GTFS submitted to the NTD enters the
   public domain. Several large agencies simultaneously publish the same feed
   under a revocable, purpose-limited developer licence. We need FTA's view on
   record before we hold a byte of it.
   Contact: the NTD Help Desk, via <https://www.transit.dot.gov/ntd> (the
   "Contact NTD" route — use the published address, not one from this document).
   Ask, in one paragraph: *does the public-domain status of GTFS submitted under
   the RY2023 requirement permit a third party to use and redistribute those
   feeds commercially, notwithstanding an individual agency's separate
   click-through developer licence covering the same data?*
   *Expect:* 5–15 business days. A "yes" unlocks item 2 of the shortlist —
   1,214 operators. A "no" or a non-answer means we take Cal-ITP only and say so.
   Whatever comes back, save the reply; it becomes the rights record.

3. **Ask Caltrans DDS whether the California TIDES data can be made freely
   accessible.**
   California TIDES (<https://tides.dds.dot.ca.gov/>) is a statewide repository
   of real transit operations data — AVL vehicle locations, APC passenger counts,
   fare transactions — in the TIDES standard. It is **the single best dataset in
   this entire review** and we cannot take it, because it is served from a
   *requester-pays* Google Cloud bucket: "every request must be billed to a
   Google Cloud project you own." That requires a billing-enabled cloud account,
   which is out of bounds.
   Contact: `hello@calitp.org` (Cal-ITP), and/or the Caltrans Division of Data
   and Digital Services via <https://dot.ca.gov/cal-itp>.
   Ask: whether a static extract could be published on data.ca.gov under the same
   Creative Commons Attribution licence as their other transit datasets, or
   mirrored somewhere without requester-pays.
   **This is the one place your Loughborough affiliation genuinely helps.** Say
   plainly that you are an undergraduate at Loughborough University working on
   transit operations research, and that the requester-pays model is the specific
   barrier. State agencies respond to that framing. Be honest that the work has a
   commercial dimension — do not describe it as purely academic (see item 7).
   *Expect:* variable, 1–4 weeks, possibly no reply. Cost of asking: zero.

**Download nothing yet — but these need no registration when the time comes.**

4. Cal-ITP GTFS-Ingest Pipeline Dataset, Cal-ITP Transit Speeds, LODES8,
   EPA Smart Location Database, SSA county data, and gtfsrt.io are **all keyless
   plain HTTP**. There is **no account to create for any of them.** If you find
   yourself on a sign-up page for one of these, you are on the wrong site.

**Do not do these.**

5. **Do not sign up for Transitland / Interline free credits.** They offer 500
   free historical GTFS feed downloads, which looks exactly like what we want.
   The offer is explicitly *"For Hobbyists and Academics performing non-commercial
   work."* Milexium is a commercial product. Taking those credits would be
   obtaining data under terms we do not meet. Commercial access is a paid plan
   (Professional $200–250/month, or "contact for quote") and is therefore out of
   bounds regardless.

6. **Do not create a Google Cloud, AWS, or Azure billing account** for California
   TIDES or anything else. The estate runs on local MinIO. See §4.

7. **Understand what your student status does and does not do.** It helps you
   *ask* — a state DOT will read a Loughborough undergraduate's research enquiry
   (Action 3) more generously than a vendor's. It does **not** make Milexium's use
   non-commercial. Every CC BY-NC dataset and every "free for academics" tier in
   this review stays off-limits, and being a student does not change that. Do not
   let anyone — including me — talk you into using academic access for
   product data.

---

## 4. Hard NO list

**Non-commercial licences.** Fatal, not negotiable.

- **Bus Observatory** (Jacobs Urban Tech Hub, Cornell Tech) —
  <https://api.busobservatory.org/>. A genuinely excellent public archive of
  minute-by-minute NYC bus vehicle positions in Parquet, in a public S3 bucket
  (`busobservatory-lake`). **"All data is licensed under a CC BY-NC 4.0
  license."** NC means no. This is the most painful exclusion on the list.
- **Transitland historical feed archive** — free credits restricted to
  non-commercial hobbyist/academic work; commercial is paid. Out on both counts.

**Paid, in any form.** Hard constraint: no paid services, no paid cloud storage.

- **California TIDES** (`calitp-tides`) — requester-pays GCS bucket; needs a
  billing-enabled Google Cloud project; no anonymous downloads. Even at "pennies",
  it is a paid service and a cloud billing relationship. **Excluded.** Re-open
  only if Action 3 succeeds.
- **Transitland Professional** ($200–250/mo), **Transitland Datasets commercial**
  (quote), **SafeGraph, Replica, StreetLight, INRIX, Swiftly, Via, Spare** — all
  paid vendors. Excluded without further discussion.
- **Any AWS / GCS / Azure storage tier.** The estate is local MinIO. Reading from
  a *publicly readable* bucket that someone else pays egress on (gtfsrt.io,
  busobservatory-lake) is not the same thing and is not excluded by this rule —
  but *storing* in one, or paying to read from one, is.

**Revocable, purpose-limited agency licences.** Same reasoning as the survey's
CTA analysis — a licence that can be withdrawn, with a deletion clause, is not a
foundation for a runtime other software integrates.

- **CTA** — quoted in full in `US_OPEN_DATA_SURVEY.md` §2. Unchanged.
- **CapMetro / Austin** (`data.austintexas.gov/…/eiei-9rpf`) — grants
  *"non-exclusive, limited and revocable"* rights. Same shape as CTA.
- **511 SF Bay / SamTrans** — free token, but *"non-exclusive, limited and
  revocable"*, and the provider reserves the right to withdraw data without
  notice.
- **MTA / NYC** — <https://www.mta.info/terms-and-conditions>. Beyond the
  revocability, there is an indication that **commercial and ad-sponsored
  applications may be charged a licence fee for use of MTA intellectual
  property.** That is a paid-service risk attached to data we would already be
  holding. Note this does **not** retroactively taint the MTA panels already in
  `realdata/` — those were acquired earlier and are already recorded; it means
  *no new MTA acquisitions*.
- **`data.mytransit.nyc` / `nycbuspositions`** — third-party republications of
  MTA feeds. They inherit MTA's terms, declare no licence of their own, and are
  not maintained or endorsed by MTA. Two rights problems stacked. No.
- **MTA Bus Time historical archive** (<https://bustime.mta.info/wiki/Developers/ArchiveData>)
  — a one-month B63 extract from 2011 and an Aug–Oct 2014 dump. Even setting
  rights aside: one route, one month, twelve years stale. Not worth the
  argument.

**Personal data we would then have to protect.**

- **Medicaid NEMT / CMS T-MSIS trip records** — individual-level health-linked
  transport records. Restricted-use, and holding them would drag Milexium into a
  data-protection regime it is not built for.
- **ADA paratransit eligibility rosters** — e.g. MBTA's RIDE eligibility database
  (~40,721 individuals) is referenced in public research but is not open data,
  and should not be sought. Eligibility status is health data about named people.
- **Any individual-level trip record with an identifiable rider.** The estate's
  existing NYC AAR holding is a *borough-hour aggregate* and that is the right
  granularity. Do not go finer.

**Unverified rights — ranked out rather than banned.**

- **MBTA LAMP** (<https://performancedata.mbta.com/>) — governed by the MassDOT
  Developers License Agreement, whose commercial clause ADR-0050 already records
  as machine-unverifiable. Additionally: I checked the published prefixes and
  LAMP currently publishes **subway** on-time performance, a GTFS schedule
  archive, and alerts — **no public bus vehicle-position or vehicle-event
  dataset**. So it fails on both rights and content. Revisit if MBTA publishes
  the Bus Performance Manager outputs.
- **PORTAL** (Portland State, <https://portal.its.pdx.edu/>) — holds TriMet AVL
  and APC stop-event data, which is genuinely the right *kind* of data. But the
  site states no licence, no terms of use, and no data-sharing agreement that I
  could find. **Unverified is not a rights declaration.** Do not acquire; it
  would be a reasonable target for an Action-3-style enquiry later.

**Already settled by the survey — no change.**

- **NOAA GHCN / weather** (~12 GB). `realdata/WEATHER_ABLATION_RESULTS.md`
  measured R² 0.9851 without weather vs 0.9857 with both daily and hourly — all
  inside noise. The repo already has the receipt. **Still no.**
- **OSM `us-latest.osm.pbf`** (11.5 GB) — no routing engine has cleared the
  vendoring gate; it would sit inert. Still no.
- **NHTS** — national cross-sectional survey, no agency identity, no time index.
  Still no.
- **NYC TLC `fhv_tripdata`** (~3 GB) — shrinking legacy segment, many months
  without coordinates. Still no.

---

## 5. Size and effort estimate, and the verdict on ~250 MB

### Estimated volume, if everything in §1 is taken

| Item | Estimate | Confidence |
|---|---|---|
| 3. Cal-ITP GTFS-Ingest (29 CSVs, `stop_times` dominant) | 1.5–5 GB | low — sizes not published |
| 4. Cal-ITP transit speeds (CSV) | 50–400 MB | low |
| 5. ACS 5-year, 6 tables, all tracts | 20–80 MB | medium |
| 6. LODES8, 6 states, latest vintage | 250–500 MB | medium — survey measured per-state files |
| 7. EPA SLD v3 | 1–2 GB | low |
| 8. SSA county | <10 MB | high |
| 1. gtfsrt.io probe (3 feeds × 30 days, Parquet) | 1–10 GB | **very low** |
| 2. National GTFS harvest (all 1,214), compressed | 4–8 GB | medium |
| **Total, everything** | **~8–26 GB** | |
| **Recommended first tranche** (items 3, 4, 5, 8 + a 7-day gtfsrt.io probe) | **~2–6 GB** | |

Against the ~15 GB budget the survey worked to, the full plan fits and the first
tranche is comfortable. **Take the first tranche only.** Items 1 and 2 are both
gated on outcomes — a probe measurement and an FTA email — and neither should be
committed before its gate clears.

### Effort

- Items 4, 5, 8: **hours.** Stable URLs, one manifest each.
- Item 3: **1–2 days.** 29 URLs, but `stop_times` statewide is large enough to
  need a streaming reader, and the block→deadhead reconstruction is new code.
- Item 6, 7: **half a day each**, mostly manifest and rights-record work.
- Item 1: **3–5 days.** Base64url feed-key encoding, partition discovery, protobuf
  decode, and — the real cost — a per-feed rights review before each feed enters
  the estate.
- Item 2: **1–2 weeks.** 1,539 URLs with a meaningful dead/redirect/moved rate,
  per-agency rights records, and a fetch loop that must be polite. **Do not start
  this before the FTA reply.**

### Does the survey's ~250 MB conclusion survive?

**Yes, for the question it asked — and it needs a second row for the question we
are asking now.**

The survey scoped "useful" as *"improves the demand-forecast models."* Under that
scope I found **nothing that overturns 250 MB.** I looked specifically for
counter-evidence and did not find it: no open corpus of demand-response trip
records exists beyond what the estate already holds; the ADA-eligibility and
senior-geography sources (items 5, 6, 8) are tens to hundreds of MB, not
gigabytes; and the sources that *are* multi-gigabyte are the ones the survey
already ablated to zero (weather) or reasoned away (OSM, NHTS, LODES for
warm-start). The survey's own measurements are the strongest evidence for its
own conclusion, and they still hold.

**But the scope has moved, and the number moves with it.** Deadhead measurement
is not demand forecasting, and it is data-hungry in a way forecasting is not,
for a structural reason: reconstruction needs `stop_times.txt`, which scales with
trips × stops and is 80–90% of any GTFS bundle; observation needs vehicle
positions, which scale with vehicles × seconds. Neither compresses to hundreds of
megabytes at national breadth. So the honest updated statement is two rows, not
one:

| Scope | Rights-clean and useful volume |
|---|---|
| Demand forecasting (survey's question) | **~250 MB** — unchanged, and I could not break it |
| Scheduling / deadhead measurement (this question) | **single-digit to low tens of GB** |

That is not a correction. It is a second measurement of a different thing, and
the survey should not be read as having claimed otherwise.

### Does "more distinct operators, not more rows" survive?

**Yes — and it is the organising principle of this entire plan, which is the
strongest form of agreement I can offer.** Every top-ranked item was chosen for
operator breadth and for nothing else: Cal-ITP delivers ~200 California operators
in 29 URLs; the NTD weblinks route reaches 1,214; gtfsrt.io spans many feeds.
Nothing here is ranked for row count.

**One refinement, offered as a sharpening rather than a disagreement.** For the
scheduling work the alternative to "more operators" is not "more rows" — it is
**more time depth per operator**, and that fails for a different and more
interesting reason. Block structure is near-*static within a service change*: ten
years of one operator's GTFS is roughly forty distinct block structures, not ten
years of signal. Deadhead is a property of how an operator builds its schedule,
and each operator has essentially one such property per service change. So the
ordering is:

> **more operators ≫ more time depth ≫ more rows**

and it is even more lopsided for scheduling than for forecasting. The survey's
instinct was right and generalises further than it claimed. The practical
consequence is concrete: when item 2 runs, take **one recent bundle per agency
across as many agencies as possible**, never a deep historical archive for a few.

---

## 6. Verification log

Recorded so the next reader knows what is established and what is inference.

**Verified by reading the source directly:**
- gtfsrt.io: keyless access, both URL patterns, AGPL-3.0 on the archiver, absence
  of any data-licence statement.
- Bus Observatory: CC BY-NC 4.0, verbatim.
- Transitland: free tier is non-commercial for the feed archive; Professional
  $200–250/month; source-feed licences are the consumer's responsibility.
- California TIDES: requester-pays GCS, "you pay the egress", no anonymous access.
- Cal-ITP GTFS-Ingest: 29 CSV resources with URLs, License "Creative Commons
  Attribution", Rights "No restrictions on public use", Monthly, last updated
  2026-07-21.
- Cal-ITP transit speeds (stop and route): same licence and rights fields;
  derivation from GTFS-RT vehicle positions stated on the page.
- Census API terms: commercial use, disclaimer requirement, no-reidentification
  clause.
- EPA SLD: variables, geography, v3 vintage, direct ZIP URL — **and the absence
  of any licence statement on the page.**
- MBTA LAMP: the published prefixes — subway OTP, GTFS archive, Tableau rail and
  alerts. **No public bus vehicle-position dataset.**
- MTA Bus Time archive page: contents and date ranges.
- PORTAL: holds TriMet AVL/APC; **no licence or terms found.**

**Confirmed via search index and the repo's own prior quotation, but the
authoritative page returned HTTP 403 to this client:**
- FTA's "GTFS submitted to the NTD will enter the public domain" statement
  (`transit.dot.gov`). The survey independently quotes materially the same
  wording from the Socrata record for `2u7n-ub22`, which is why I treat it as
  established rather than unverified — **but the founder should open the page in
  a browser and capture it for the rights record before item 2 proceeds.**
- BTS National Transit Map CC-BY-3.0 US / FACES opt-in (`bts.gov`, `bts.dot.gov`).
- MassDOT Developers License Agreement PDF (`mass.gov` 403). Its commercial
  clause remains **unverified**, exactly as ADR-0050 recorded.

**Could not verify at all:**
- gtfsrt.io inventory — feed count, agency list, archive start date, total bytes.
  The inventory table is client-rendered. **Everything in this document about
  gtfsrt.io's scale is an order-of-magnitude estimate and must be measured by a
  probe before item 1 is committed.**
- Every byte size in §5 except the LODES per-state figures, which come from the
  survey's own measurements.
- MTA's commercial licence-fee position — indicated in secondary sources, and
  `web.mta.info/developers/developer-data-terms.html` redirects in a way this
  client could not follow. Treated as a risk flag, not a finding.
