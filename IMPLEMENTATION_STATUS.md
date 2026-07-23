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

Test evidence for everything in this table: `py -3 -m pytest packages/ conformance/`
→ **92 passed, 0 failed** (last run 2026-07-23). `py -3 tools/audit_repository.py`
→ unaffected, still passes (0 errors, 0 warnings) — the expansion added files,
it did not modify anything the existing audit checks.

## Programs B through M: Specified only

Every other program in `SWARM_MANIFEST.yaml` (B Connect, D Core/adaptive
memory, E Forecast-as-a-runtime, F Decide/optimization, H Simulation/replay,
I Evidence/Experience IR, J Forge/Fabric, K Runtime/silicon, L Confidential/
edge, M APIs/ecosystem) has **no code in this repository** as of 2026-07-23.
Their entries in `blueprint/14-execution-roadmap.md` and `SWARM_MANIFEST.yaml`
remain the specification; nothing here should be read as more than that.

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
