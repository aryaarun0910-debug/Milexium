# Milexium implementation status

Living document. Status vocabulary is exact and fixed, per
`architecture/decisions/0001-adopt-expansion-blueprint-and-control-plane.md`:

- **Exists** — working code or evidence in this repository.
- **Specified** — documented in the expansion plan but not implemented.
- **Demonstrated** — works on the fictional reference agency or public proxy data.
- **Validated** — tested on consented operator data against a declared baseline.
- **Production** — operated with security controls, monitoring, recovery, support,
  and a named accountable owner.

No claim in this file, in `docs/`, or in the YC application may use a stronger
word than what's true here. See `workstreams/DOSSIER_COVERAGE.md` for the
80-technology/72-project ledger.

## What this repository already had (Exists, unmodified by the expansion)

This is the product `docs/README.md`, `docs/MASTER_ROADMAP.md`, and
`docs/JOURNAL.md` already describe — untouched by this work:

| Capability | Status | Evidence |
|---|---|---|
| Real aggregate demand forecasting (AAR, NTD, Chicago TNP, MTA) | **Exists** | `realdata/`, `docs/MODEL_CARDS.md` |
| Point-in-time leakage audit | **Exists** | `realdata/leakage_audit.py`, `docs/JOURNAL.md` (2026-07-22 entry) |
| Transfer learning (pretrain-then-finetune) | **Exists**, negative-and-positive results both kept | `kaggle/`, `realdata/transfer_control.py` |
| Fictional reference-agency scheduler | **Demonstrated** (explicitly synthetic, not validated) | `reference_agency/` |
| NTD market sizing / economics | **Exists** | `ntd/` |
| Repository/data integrity audit | **Exists** | `tools/audit_repository.py` |

## What the expansion added this session (Program A + G foundation)

| Capability | Program | Status | Evidence |
|---|---|---|---|
| Canonical entities (Tenant, ServiceRequest, Vehicle, Driver, Policy, ModelVersion, ForecastVintage, ScheduleRun, DecisionAlternative, DecisionEvent, Outcome, OutboxEntry) | A | **Exists** (v0.1) | `packages/canonical/entities.py`; schema exported via `packages/verify/schema_verifier.py` |
| Typed identifiers (UUIDv7) | A | **Exists** | `packages/canonical/ids.py` |
| Explicit requested/negotiated/scheduled/predicted/actual time fields + bitemporal correction + "known as of" replay cutoff | A | **Exists**, unit-tested | `packages/canonical/time.py`; `conformance/property-tests/test_bitemporal_correction.py` |
| ServiceRequest state machine (8 states, exhaustively tested transition table) | A | **Exists** | `packages/canonical/state_machine.py`; `conformance/property-tests/test_state_transitions.py` (72 parametrized cases) |
| Policy/reason-code/sensitivity vocabularies | A | **Exists** | `packages/canonical/vocab.py` |
| Append-only, hash-chained decision event log — two independent implementations (in-memory, SQLite) of one contract | A | **Exists** | `packages/canonical/events.py`, `packages/canonical/storage.py`; both run the same property tests |
| Portable SQL DDL (SQLite today, PostgreSQL-compatible subset) | A/C | **Exists** (schema only — not yet run against the installed PostgreSQL instance) | `packages/canonical/sql/schema_v0_1.sql` |
| Independent verifiers: JSON-Schema, state-transition, hash-chain | G | **Exists**, organizationally separate from the generator | `packages/verify/` |
| Tampering / tenant-isolation adversarial tests | reliability/adversarial | **Exists** | `conformance/adversarial/test_tamper_and_isolation.py` (7 tests: payload tamper, deleted-event gap, forged-hash chain-break, cross-tenant read, cross-tenant raw-row disjointness, DB-level duplicate-sequence rejection) |
| SemanticIndex interface + exact-search reference backend | C (partial) | **Exists** (interface + one backend only — no pgvector/TurboVec adapter) | `packages/canonical/semantic_index.py` |
| Control-plane scaffolding (`architecture/`, `packages/`, `conformance/`, `benchmarks/`, `research/`, `third_party/`, `ops/`, `workstreams/`) | orchestration | **Exists** | this commit |
| ADRs 0001-0005 | orchestration | **Exists** | `architecture/decisions/` |
| PostgreSQL 17 installed and running as a Windows service | C (infra only) | **Exists** (infra readiness only — nothing in this repo talks to it yet) | `architecture/decisions/0004-...md`; confirmed via `Get-Service postgresql-x64-17` = Running |

## Second tranche this session (Programs B, C-Postgres, I first slices)

Dispatched as three parallel work packets against the versioned A/G contract
above (disjoint owned paths, no shared-file edits between them):

| Capability | Program | Status | Evidence |
|---|---|---|---|
| Generic adapter contract (`AdapterResult`/`QuarantinedRow`/`SemanticLossRecord`, exactly-one-outcome enforced by a Pydantic validator) | B | **Exists** (v0.1) | `packages/connect/adapter.py`; ADR-0007 |
| One concrete adapter: `reference_agency/output/trips.csv` → `ServiceRequest`, tokenized rider identity, quarantine on malformed rows, semantic-loss recording on every unmapped source field | B | **Demonstrated** (source is explicitly fictional) | `packages/connect/reference_agency_trips.py`; verified against the real generated 89,566-row CSV |
| `PostgresCanonicalStore` — same method contract as `SqliteCanonicalStore`, running against the installed PostgreSQL 17 via `milexium_dev` (non-superuser) role, portable DDL applied unmodified | C | **Exists** (v0.1: append/history/tamper-test-helper only — no RLS, PostGIS, replication, backup/restore) | `packages/canonical/postgres_storage.py`; ADR-0006, ADR-0008 |
| Postgres test isolation via disposable per-instance schema (`mx_<uuid>` + `DROP ... CASCADE`) | C | **Exists** | ADR-0008; verified zero leftover schemas after repeated runs |
| `EvidencePacket`/`ExperiencePacket` (Evidence IR / Experience IR v0.1) reconstructed from a `DecisionEvent` history plus independent hash-chain verification; refuses to build an `ExperiencePacket` from an unverified chain | I | **Exists** (v0.1: hash-chain check only, not schema/state-transition checks yet) | `packages/evidence/`; ADR-0009 |
| ADRs 0006-0009 | orchestration | **Exists** | `architecture/decisions/` |

Test evidence for everything in both tables: `py -3 -m pytest packages/ conformance/`
→ **124 passed, 0 failed** (last run 2026-07-23; 92 from the first tranche + 32
from this one). `py -3 tools/audit_repository.py` → unaffected, still passes
(0 errors, 0 warnings).

## Sixth tranche this session (Forecast runtime + evidence-pack export)

| Capability | Program | Status | Evidence |
|---|---|---|---|
| `ForecastRuntime` — resolves champion model from the registry, hash-verifies the artifact, predicts, emits a canonical `ForecastVintage` | E | **Demonstrated** on real aggregate data (a real forecast served from the committed Access-A-Ride booster) | `packages/forecast/`; ADR-0016 |
| Portable evidence pack — `build_evidence_pack`/`verify_evidence_pack` a third party re-verifies without Milexium; honest `redact_pack` | I | **Exists** (v0.1) | `packages/evidence/export.py`; ADR-0017 |
| ADRs 0016-0017 | orchestration | **Exists** | `architecture/decisions/` |

Test evidence: `py -3 -m pytest packages/ conformance/` → **212 passed, 0
failed** (202 → 212: +5 forecast, +5 evidence-pack export). Audit clean.

Program E now serves the repo's *real* forecasting models through the runtime
(previously reachable only via `realdata/` scripts), and Program I can emit a
self-contained, independently-verifiable evidence artifact — the "undeniable
operational evidence you can hand a partner" the go-to-market rests on. Both
stay honest on status: forecasts are Demonstrated on real *aggregate* data
(not operator-validated dispatch), and the evidence pack is tamper-evident,
not immutable and not a compliance certificate.

## Fifth tranche this session (standards adapters + SDK — the integration surface)

Three parallel packets, all landed and integrated:

| Capability | Program | Status | Evidence |
|---|---|---|---|
| TIDES `trips_performed` → `ServiceRequest` adapter | B | **Demonstrated** | `packages/connect/tides_trips.py`; ADR-0014; built against real acquired TIDES schema |
| GTFS-Flex on-demand → `ServiceRequest` adapter — maps booking windows → `negotiated_window_*` (first adapter to populate that field from real data) | B | **Demonstrated** | `packages/connect/gtfs_flex.py`; ADR-0014; built + tested against the real acquired Aspen feed |
| `MilexiumClient` SDK facade — one import drives ingest→decide→override→verified-evidence; runnable quickstart | M | **Demonstrated** | `packages/sdk/`; ADR-0015 |
| All four Connect adapters wired into `packages/connect/__init__.py` | B | **Exists** | central integration this tranche |
| ADRs 0014-0015 | orchestration | **Exists** | `architecture/decisions/` |

Test evidence: `py -3 -m pytest packages/ conformance/` → **202 passed, 0
failed** (159 → 202: +16 TIDES, +19 GTFS-Flex, +8 SDK). Audit clean. Five
adapters now map five structurally different sources (fictional CSV, real
Parquet, TIDES open standard, GTFS-Flex open standard) onto one
`ServiceRequest` contract — concrete progress on blueprint 01's "unavoidable"
test #1 ("external data producers map to the schema without custom downstream
code"). Program M (the integration surface that makes "other software
integrates this" real) now has its first working slice.

## Fourth tranche this session (governed data estate — Program C data layer)

Strategic repositioning (2026-07-23): Milexium as a transport decision
*runtime other software companies integrate*, generating independent
operational evidence from public data rather than waiting on a large agency.
The data-estate governance layer is the foundation that makes that credible.

| Capability | Program | Status | Evidence |
|---|---|---|---|
| `data/` estate zone layout (blueprint 17) + gitignore governance (raw ignored, catalog committed) | C | **Exists** | `data/README.md`, `.gitignore` |
| Acquisition-manifest contract (rights **must** be declared) | C | **Exists** | `packages/estate/manifest.py` |
| Manifest-gated `acquire()` — free-space guard, quarantine, checksum, content-addressed promotion, catalog record | C | **Exists** | `packages/estate/acquire.py`; 5 governance tests |
| Catalog inventory + free-space reporting (completion evidence #7/#8) | C | **Exists** | `packages/estate/catalog.py` |
| Two real rights-clean datasets acquired end-to-end | C | **Exists** | TIDES `trips_performed.csv` (Apache-2.0) → `data/standards/`; Geofabrik DC OSM extract 20.9 MB (ODbL) → `data/networks/`; catalog records committed |
| Technology-vendoring gate (review manifest + ADR required; no blind cloning) | orchestration | **Exists** (process only — nothing vendored) | `third_party/VENDORING_PROCESS.md` |
| ADR-0013 | orchestration | **Exists** | `architecture/decisions/` |

Test evidence: `py -3 -m pytest packages/ conformance/` → **159 passed, 0
failed** (154 + 5 estate governance tests). `py -3 tools/audit_repository.py`
→ still passes.

Explicitly **not** done: the 250 GB is not bulk-downloaded (each future
dataset is a queued, rights-checked manifest, one `acquire()` call away); no
dossier technology is vendored; PostGIS still not installed; the OSM extract
in `networks/` has no routing-graph derivation yet (Program F/H). The estate
holds ~0.02 GB of new governed data plus the pipeline to grow it deliberately
— the value delivered is the *governance*, not the volume.

## Third tranche this session (Programs B second adapter, D first slice, I verification folded in)

| Capability | Program | Status | Evidence |
|---|---|---|---|
| Second Connect adapter: NYC TLC FHVHV trip Parquet → `ServiceRequest`, structurally different from the first (columnar, pandas-null-typed, no rider identity) | B | **Demonstrated** (real public data, not consented operator data) | `packages/connect/tlc_trips.py`; ADR-0011; verified against real files, including observed schema drift (`cbd_congestion_fee`) |
| Task/model registry: closed task vocabulary + `ModelRegistry` (register/get/list/promote-champion), cataloging this repo's 5 real trained models | D | **Exists** (v0.1: in-memory reference registry only; memory tiers, parameter-deltas, drift/calibration all Specified) | `packages/core/`; ADR-0010; every `training_data_manifest_hash`/`artifact_hash` value independently spot-checked against the actual committed manifest/model files |
| `EvidencePacket` integrity check extended to schema conformance (all 3 checks now aggregate into `integrity_verified`) | I | **Exists** (v0.1); state-transition check honestly marked structurally inapplicable, not faked | `packages/evidence/`; ADR-0012 |
| ADRs 0010-0012 | orchestration | **Exists** | `architecture/decisions/` |

Test evidence: `py -3 -m pytest packages/ conformance/` → **154 passed, 0
failed** (124 + 30 new across this tranche's three packets). `py -3
tools/audit_repository.py` → unaffected, still passes.

## Programs E, F, H, J, K, L, M: Specified only

Every other program in `SWARM_MANIFEST.yaml` (E Forecast-as-a-runtime, F
Decide/optimization, H Simulation/replay, J Forge/Fabric, K Runtime/silicon,
L Confidential/edge, M APIs/ecosystem) has **no code in this repository** as
of 2026-07-23. Their entries in `blueprint/14-execution-roadmap.md` and
`SWARM_MANIFEST.yaml` remain the specification; nothing here should be read
as more than that.

Program F (Decide) is deliberately not being worked by this expansion effort
right now: it overlaps with `docs/MASTER_ROADMAP.md`'s own "Friday 24 July:
constrained scheduling and decision evidence" task (OR-Tools CP-SAT scheduler),
explicitly owned by Arya directly. Building a parallel expansion-agent solver
implementation risks two competing schedulers with no clear authority for the
YC demo — this is being held back on purpose, not forgotten.

Programs B, C, D, G, and I now have real first slices but remain far from
their full blueprint scope — e.g. Program B's adapter surface is one method
of six and has two adapters, not the full standards-adapter set; Program C
has no RLS/PostGIS/replication; Program D has no memory tiers or drift
detection; Program I's state-transition check is structurally inapplicable
until a new payload convention or signature change is decided (ADR-0012).

Notably: the existing `reference_agency/` scheduler (greedy, fictional data)
is *not* Program F. Program F is Decision IR + a real solver portfolio (CP-SAT/
MILP/SMT/heuristic) with an independent feasibility checker — unbuilt. The
roadmap's own OR-Tools scheduler task (`docs/MASTER_ROADMAP.md`, "Friday 24
July") is a distinct, narrower, YC-deadline-scoped effort and is not tracked
in this file.

## Genuine blockers requiring the product owner's decision

These are not implementation details resolvable from the blueprint or
"safe engineering judgment" — flagging per the standing instruction to
interrupt for credentials, unavailable external systems, and infrastructure/
vendoring decisions:

1. **TurboVec vendoring** (`architecture/decisions/0005-...md`) — the
   expansion plan explicitly forbids vendoring it without a license/security/
   maturity review. Not started.
2. **Object storage** — no S3/GCS/Azure Blob credentials configured anywhere
   in this environment. Program C's "immutable object and artifact manifests"
   cannot become Exists without either real cloud credentials or an explicit
   decision to simulate it with a local content-addressed directory (dev-only,
   would need to be labeled as such).
3. **PostGIS** — not installed (ships separately from the PostgreSQL 17
   engine). No canonical entity currently needs geometry, so this is not
   urgent, but Program C's "PostgreSQL/PostGIS" non-negotiable is only
   half-satisfied by the engine install alone.
4. **GPU / cloud compute for Forge, Runtime, and hardware programs (J, K, L)**
   — genuinely out of scope for this local machine. These stay Specified
   indefinitely absent a decision to provision (and pay for) real compute.
5. **Lean/TLA+/SMT toolchains** for Program G's formal-methods layer
   (`architecture/formal/`) — not installed; `packages/verify` v0.1 is plain
   Python, a manual precursor to formal verification, not formal verification
   itself.

Not a blocker, but flagging so it isn't lost: **`DecisionAlternative` has no
store method** (`packages/canonical/storage.py`/`postgres_storage.py` never
read/write the `decision_alternatives` table `schema_v0_1.sql` already
defines). `packages/evidence` worked around this with a v0.1 convention
(alternatives embedded in a `RECOMMENDATION` event's payload, ADR-0009) —
worth reconciling once a real scheduler (Program F, or the roadmap's OR-Tools
work) actually needs to write `decision_alternatives` rows.

Also not a blocker, also flagging: **`ModelVersion.tenant_id` has no answer
for platform-trained models** that don't belong to any one customer (ADR-0010)
— the model registry fixtures use a placeholder tenant id with no real
meaning, pending a decision between a reserved "platform" tenant convention
or an optional tenant_id specifically for this entity.

## Relationship to the YC deadline

Per the product owner's direction on 2026-07-23, this expansion work
proceeds in parallel with (not instead of) `docs/MASTER_ROADMAP.md`. Nothing
in this session modified `realdata/`, `reference_agency/`, `ntd/`, `kaggle/`,
`outreach/`, or any YC application material. The canonical schema built here
is designed to also satisfy the roadmap's "MilexiumDB vertical slice" task
(same tables, same append-only hash-chained ledger design) so the two efforts
compound rather than compete for the same implementation work — but the
roadmap's own checklist in `docs/MASTER_ROADMAP.md` is the authority on
whether that task is actually done for YC-demo purposes (e.g. it still needs
a FastAPI layer, a seed/reset CLI command, and OR-Tools scheduling, none of
which this session built).
