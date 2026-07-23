# Milexium project journal

Newest entries first. One entry per working session: what was added, the numbers produced, decisions made, and anything running or unfinished. This is the historical record; `docs/MASTER_ROADMAP.md` is the only active backlog.

Renamed from TransitPulse to Milexium on 2026-07-22 (see entry below). Entries
dated before the rename refer to the company as TransitPulse throughout,
unchanged, because this file is an append-only historical record.

## 2026-07-23 (evening): repositioning + governed data estate

Arya set the strategic frame explicitly: rather than wait on a large transit
agency to prove Milexium works (outreach is brutally hard pre-YC), build
enough product to generate undeniable operational evidence independently from
public data, win smaller customers with it, and climb upward — and reposition
Milexium as "the transport intelligence layer that converts operational data
into forecasts, feasible plans, and auditable decisions," a decision *runtime
other software integrates*, not just a dashboard agencies log into. This is
consistent with the expansion blueprint's own north star (blueprint 01,
"model-agnostic decision infrastructure"), so it's a sharpening of direction,
not a pivot.

The instinct was "download all the data and technology." The formidable
version of that — and the one the blueprint itself mandates — is governed
acquisition, not a bulk pull: blueprint 17 says "No download enters the estate
without [a manifest: rights, checksum, purpose, quality tests, retention]" and
blueprint 20 says "Do not vendor upstream projects blindly." A governed,
rights-clean, reproducible estate is exactly what makes Milexium integratable
by other software; an ungoverned pile is not. So this tranche built the
governance, not the volume:

- **`data/` estate** (blueprint 17 zone layout): `catalog/` (committed
  governance ledger) + `raw/`, `quarantine/`, `standards/`, `networks/`,
  `canonical/`, `features/`, `simulation/`, `semantic/`, `experience/`,
  `benchmarks/`, `evidence/`, `scratch/` (gitignored, large/reproducible).
- **`packages/estate/`**: an `AcquisitionManifest` contract where rights
  *must* be declared (not "unknown"), and `acquire()` enforcing free-space
  check → quarantine download → checksum → content-addressed promotion →
  catalog record. Plus catalog inventory + free-space reporting.
- **Proved end-to-end on real, rights-clean, on-point data**: acquired a TIDES
  `trips_performed.csv` sample (Apache-2.0 — the demand-responsive-transport
  trip-level standard, maximally on-brand for paratransit) into
  `data/standards/`, and a Geofabrik DC OpenStreetMap extract (ODbL, 20.9 MB
  real routing data) into `data/networks/`. Free space reported 335.33 →
  335.31 GB across the two pulls; raw bytes gitignored, catalog records
  committed.
- **`third_party/VENDORING_PROCESS.md`**: the gate for the "download the
  technology" half — a review manifest (license/maturity/security/benchmark)
  + ADR required before anything lands, nothing vendored yet. Named the
  nearest real candidates (pgvector, OR-Tools) and why the frontier dossier
  tech (FHE, silicon, world models) is deliberately nowhere near the gate.
- ADR-0013; 5 new governance conformance tests (rights required, free-space
  guard fires before download, checksum mismatch leaves the object in
  quarantine and never in the trusted zone, clean acquisition catalogs real
  bytes). Full suite 159 passed; audit still clean.

Deliberately NOT done, and why: the 250 GB is not bulk-downloaded (every
future dataset is a queued rights-checked manifest, one command away — this is
how "every byte has a manifest" is enforced without a reckless pull that could
fill the disk or ingest unlicensed data); no dossier technology vendored. The
value banked here is the governance pipeline, not the ~0.02 GB it has so far
pulled through it.

Next planned tranche (the actual repositioning payload): standards adapters —
TIDES `trips_performed` → `ServiceRequest`, GTFS-Flex → `ServiceRequest` —
against the newly-acquired `data/standards/` corpus. These are the
vendor-neutral ingestion surface that makes Milexium a runtime other software
plugs into, and they extend the existing two-adapter Connect base (ADR-0007,
0011) toward blueprint 03's full standards-adapter set.

## 2026-07-23 (later still): expansion tranche 3 — B second adapter, D first slice, I verification folded in

Three more parallel packets, dispatched after Arya said "GO GO GO" to
continue past the tranche-2 checkpoint:

- **Program B, second adapter:** `packages/connect/tlc_trips.py` maps real
  NYC TLC FHVHV trip Parquet data (`realdata/raw_tlc/`, already downloaded
  for the forecasting pipeline) onto `ServiceRequest` — structurally
  different from the first adapter (columnar, pandas-null-typed, no rider
  identity at all, real observed schema drift across file vintages). Found
  and used real failure modes for quarantine tests: 108,898/20.16M null
  request times, ~600k rows with TLC's own unknown/outside-NYC placeholder
  zone codes. One genuine deviation from the original task brief, flagged in
  ADR-0011: TLC does carry a `wav_request_flag` (wheelchair-accessible-
  *vehicle* request), mapped to `mobility_device` with an explicit caveat
  that it's a vehicle attribute, not a direct statement of the rider's own
  device.
- **Program D, first slice:** `packages/core/` catalogs this repository's 5
  real, trained, evaluated models (`docs/MODEL_CARDS.md`) as `ModelVersion`
  registry entries with a closed task vocabulary (`forecast.demand`) and a
  simple per-task champion pointer. Every `training_data_manifest_hash` and
  `artifact_hash` is a real sha256 read from or computed against a committed
  file, cited per field — except NTD's artifact hash, honestly labeled
  `NOT_COMPUTED` because `realdata/model_ntd_monthly.py` never saves a
  booster file, rather than faking a hash. I independently re-verified one
  claimed hash against its source manifest myself before accepting the
  packet's work — exact match. Flagged a real contract gap in ADR-0010:
  `ModelVersion.tenant_id` is mandatory but these models aren't tied to any
  customer; a placeholder tenant id is a stopgap, not a resolution.
- **Program I, verification folded in:** extended `EvidencePacket` to
  aggregate schema conformance alongside the existing hash-chain check. The
  packet's own honest conclusion: for every real call path in this repo
  today, the schema check is close to a tautology (events arrive already
  Pydantic-validated), and it said so plainly rather than overselling the
  addition — then proved the one case where it isn't a tautology
  (`DecisionEvent.model_construct`, bypassing validation). State-transition
  verification could not be wired in at all: nothing in this repo's
  contracts yet records a `ServiceRequestState` sequence inside a
  `DecisionEvent` chain, so `state_check_applicable` stays honestly `False`
  rather than being faked — recorded as a structural gap in ADR-0012, not a
  shortcut.

Wrote three more ADRs (0010, 0011, 0012) during integration review, same
reasoning as tranche 2: agents flag decisions, the orchestrator numbers and
formalizes them centrally to avoid parallel-agent ADR-number collisions.

Deliberately did not dispatch a Program F (Decide/optimization) packet this
tranche — it would overlap with `docs/MASTER_ROADMAP.md`'s own Friday
OR-Tools scheduler task, which is Arya's directly-owned roadmap item, not
expansion-swarm territory. Two competing scheduler implementations with no
clear authority for the YC demo would be a real, avoidable risk.

Reviewed all three agents' actual code directly before integrating —
independently re-ran the full suite and re-verified specific factual claims
(a manifest hash, the real diff on already-committed evidence files) rather
than trusting self-reports alone. `py -3 -m pytest packages/ conformance/` →
**154 passed, 0 failed** (124 from tranche 2 + 30 new). `tools/
audit_repository.py` unaffected. Nothing in `realdata/` source,
`reference_agency/`, `ntd/`, `kaggle/`, `outreach/`, or existing `docs/`
content was touched by any of the three packets.

## 2026-07-23 (later): expansion tranche 2 — Programs B, C-Postgres, I first slices

After the Program A/G foundation checkpoint (below), Arya said to proceed
full steam and dispatched three parallel work packets against the versioned
A/G contract, each on a disjoint owned path:

- **Program B (Connect), `packages/connect/`:** a minimal adapter contract
  (`AdapterResult`/`QuarantinedRow`/`SemanticLossRecord`, exactly-one-outcome
  enforced by a Pydantic validator) plus one concrete adapter mapping
  `reference_agency/output/trips.csv` — a real, already-generated, but
  explicitly fictional 89,566-row source — onto `ServiceRequest`. Tokenizes
  rider identity via SHA-256; quarantines malformed rows (missing pickup
  date, invalid mobility-device value, out-of-range hour) instead of
  dropping or crashing; records every field the source has but
  `ServiceRequest` v0.1 doesn't as a semantic-loss entry rather than
  silently discarding it. Flagged one honest interpretive call: the source
  has one timestamp per trip, not five, so `requested_at` is filled and the
  negotiated/scheduled/predicted fields are left unset rather than guessed.
- **Program C continued (Postgres store), `packages/canonical/postgres_storage.py`:**
  a `PostgresCanonicalStore` mirroring `SqliteCanonicalStore`'s exact method
  contract, running against the PostgreSQL 17 instance installed earlier this
  session via the `milexium_dev` role (never the superuser). Applies
  `schema_v0_1.sql` completely unmodified. Test isolation uses a disposable
  per-instance PostgreSQL schema (`mx_<uuid>` + `DROP ... CASCADE`) rather
  than any shared fixture database — verified zero leftover schemas after
  repeated runs. New Postgres-backed tests skip cleanly (not fail) if
  `milexium_dev` isn't reachable, so the suite stays green on a clone without
  it provisioned.
- **Program I (Evidence/Experience IR), `packages/evidence/`:** an
  `EvidencePacket` that reconstructs, from an aggregate's recorded
  `DecisionEvent` history alone, what was known, proposed, considered as an
  alternative, approved/overridden, executed, and observed — plus the actual
  result of running `packages.verify.verify_chain` against it, so a tampered
  chain is visibly flagged (`integrity_verified=False`) rather than presented
  as trustworthy evidence. `build_experience_packet` refuses to run against
  an unverified packet. Flagged a real gap: `packages/canonical` has no store
  method for the `decision_alternatives` table `schema_v0_1.sql` already
  defines, so alternatives are read from a `RECOMMENDATION` event's
  `payload["alternatives"]` as a v0.1 convention, not a canonical contract
  change — recorded in ADR-0009 as something to reconcile once a real
  scheduler needs to write that table.

Formalized four more ADRs (0006 dedicated Postgres role — written before
dispatching, since it involved real credential setup; 0007 Connect adapter
contract; 0008 Postgres test-isolation strategy; 0009 Evidence IR
conventions) during integration review, since the three agents were
instructed not to self-author ADRs (to avoid three parallel agents colliding
on the same ADR number) and to flag decisions in their reports instead.

Reviewed all three agents' actual code and test output directly (not just
their self-reports) before integrating — confirmed the same test counts
independently: `py -3 -m pytest packages/ conformance/` → **124 passed, 0
failed** (92 from the first tranche + 32 new). `tools/audit_repository.py`
still passes unchanged. Nothing in `realdata/`, `reference_agency/` source,
`ntd/`, `kaggle/`, `outreach/`, or existing `docs/` content was touched by
any of the three packets.

Next planned tranche (pending checkpoint review with Arya): Program D
(Core/adaptive memory — task registry, feature contracts) and Program H
(Replay — exact/historical replay using `EvidencePacket` as its evidence
source) are the next dependency-unblocked programs per `SWARM_MANIFEST.yaml`.

## 2026-07-23: expansion kickoff — Program A/G foundation

A separate specification, `C:\Users\aryaa\Documents\Milexium Expansion plan`
(blueprint documents 01-20, `SWARM_MANIFEST.yaml`, a dossier of 80
technologies and 72 intelligence-layer projects), describes a long-term
platform architecture: canonical transport substrate, MilexiumDB, Core/
Forecast, Decide, Verify, Replay/Explain, Forge/Fabric, Runtime, Edge, and a
product/API surface, built through contract-driven parallel agent work
(programs A-M).

Arya directed implementing this now, in parallel with the YC deadline work in
`docs/MASTER_ROADMAP.md` rather than instead of it, with the instruction to
record everything here and stop at defined checkpoints rather than running
unattended to full blueprint completion. Before writing any code, the
conflict between the expansion's scope and the roadmap's explicit "scope kill
list until submission" was raised; Arya's call was to proceed with the full
expansion and treat the roadmap as the thing to protect, not the thing to
follow narrowly.

Infrastructure: this machine had no Docker, no working WSL ("Class not
registered" error), and no PostgreSQL. Arya asked what to install to remove
the hindrance; PostgreSQL 17 was installed natively via
`winget install --id PostgreSQL.PostgreSQL.17` and confirmed running as a
Windows service. PostGIS is not installed yet (ships separately) and nothing
in this repository talks to the new Postgres instance yet — see
`architecture/decisions/0004-sqlite-now-postgres-production.md`.

Built this session (all under new root directories `architecture/`,
`packages/`, `conformance/`, `benchmarks/`, `research/`, `third_party/`,
`ops/`, `workstreams/`, plus root `IMPLEMENTATION_STATUS.md` and
`pyproject.toml` — nothing in `realdata/`, `reference_agency/`, `ntd/`,
`kaggle/`, `outreach/`, or existing `docs/` content was touched):

- **Program A (canonical substrate), `packages/canonical/`:** typed UUIDv7
  identifiers; explicit requested/negotiated/scheduled/predicted/actual time
  fields with a `known_as_of()` replay-cutoff method; a bitemporal-correction
  envelope; the 12 canonical entities from `docs/MASTER_ROADMAP.md`'s
  MilexiumDB table list (Tenant, ServiceRequest, Vehicle, Driver, Policy,
  ModelVersion, ForecastVintage, ScheduleRun, DecisionAlternative,
  DecisionEvent, Outcome, OutboxEntry); an 8-state ServiceRequest state
  machine; policy/reason-code/sensitivity vocabularies; an append-only,
  SHA-256 hash-chained decision-event log implemented *twice*
  (in-memory and SQLite-backed) against one shared contract; a portable SQL
  DDL file that runs unmodified on SQLite today and is intended for
  PostgreSQL later.
- **Program G (verify), `packages/verify/`:** independent JSON-Schema, state-
  transition, and hash-chain verifiers, deliberately organized as a separate
  package that never imports the event-log's write path — it re-derives
  legality and hash integrity from raw stored rows instead of trusting the
  writer's own bookkeeping.
- **SemanticIndex interface** (`packages/canonical/semantic_index.py`): a
  `Protocol` plus one reference implementation, brute-force cosine
  `ExactSearchIndex` — no TurboVec or pgvector adapter yet; vendoring TurboVec
  specifically requires a license/security review this session did not do
  (`architecture/decisions/0005-...md`).
- **Conformance suite:** 92 pytest tests across
  `conformance/fixtures/`, `conformance/property-tests/`, and
  `conformance/adversarial/` — exhaustive state-transition-table coverage (72
  parametrized cases), idempotent-command replay, duplicate-payload
  rejection, payload tampering detection, deleted-event gap detection,
  forged-hash chain-break detection, cross-tenant read isolation, and a
  database-level duplicate-sequence rejection test. All 92 pass;
  `tools/audit_repository.py` still passes unchanged (0 errors, 0 warnings).
- **ADRs 0001-0005** in `architecture/decisions/`: adopting the expansion
  blueprint; canonical schema technology (Pydantic v2 + generated JSON
  Schema); the append-only hash-chained event log design; SQLite-now/
  PostgreSQL-production storage strategy; the SemanticIndex interface
  decision.
- **`workstreams/DOSSIER_COVERAGE.md`:** seeded the full 80-technology/
  72-project ledger from the expansion's dossier, honestly marked
  Specified across the board (0/152 Exists) — Programs A and G now have a
  first versioned contract, which is not the same as any of the 152 specific
  technologies being implemented.
- **`IMPLEMENTATION_STATUS.md`:** the living Exists/Specified/Demonstrated/
  Validated/Production gap analysis this journal entry summarizes.

Deliberately not started this session: Programs B, D, E, F, H, I, J, K, L, M
(no code); real PostgreSQL wiring (engine installed, nothing talks to it);
PostGIS; object storage; TurboVec vendoring; any Lean/TLA+/SMT tooling.

Next planned tranche (pending checkpoint review with Arya): dispatch parallel
packets against the versioned A/G stubs — likely B (Connect adapter
skeleton), continued C (a Postgres-backed store implementing the same
`SqliteCanonicalStore` contract), and I (Evidence/Experience IR skeleton) —
each as a disjoint-path work packet in the `blueprint/19-agent-swarm-
execution-system.md` format.

## 2026-07-22 (website handoff and YC execution reset)

- Removed the tracked `web/` directory. Chris owns the new Milexium website,
  domain, and Cloudflare deployment outside this repository; keeping the old
  static site here created two sources of truth.
- Updated the repository map and structural audit so a website is no longer a
  required product-repository component. Curated product screenshots remain in
  `artifacts/demo-assets/` for demos and applications.
- Replaced the open-ended backlog with a deadline-gated execution plan through
  27 July 2026 at 8pm PT and added sourced competitive positioning. The technical
  wedge is now a decision-evidence system that sits alongside incumbent dispatch
  products, not an unsupported claim that Milexium already replaces them.

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
