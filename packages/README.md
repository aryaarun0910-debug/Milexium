# packages/

Implementation packages, one per program from `SWARM_MANIFEST.yaml` in the
expansion plan. Each package owns a disjoint path; cross-package contract
changes require an ADR in `architecture/decisions/` first.

| Package | Program | Status |
|---|---|---|
| `canonical/` | A — canonical transport substrate | v0.1 Exists: entities, ids, time, state machine, vocab, event log (in-memory + SQLite), SemanticIndex interface, and (new) a PostgreSQL-backed store (`postgres_storage.py`) — see `IMPLEMENTATION_STATUS.md` |
| `verify/` | G — independent verifiers | v0.1 Exists: schema, state-transition, hash-chain verifiers |
| `connect/` | B — Milexium Connect | v0.1 Exists: generic adapter contract plus **four** structurally different adapters → `ServiceRequest` — `reference_agency` (fictional CSV), NYC TLC FHVHV (real Parquet), **TIDES** `trips_performed` (open DRT standard), **GTFS-Flex** on-demand (open DRT feed standard, maps booking windows → negotiated windows); rest of blueprint/03's surface Specified — see ADR-0007, 0011, 0014 |
| `sdk/` | M — APIs/SDK/ecosystem | v0.1 Exists: `MilexiumClient` facade — one import drives the whole loop (in-memory setup → ingest → record decision/override → verified evidence packet); runnable ten-minute quickstart. HTTP/CLI/plugin-cert/TS+Rust SDKs Specified — see ADR-0015 |
| `evidence/` | I — Evidence/Experience IR | v0.1 Exists: `EvidencePacket`/`ExperiencePacket` + independent hash-chain/schema verification, and a portable **evidence-pack export** (`build_evidence_pack`/`verify_evidence_pack`/`redact_pack`) a third party can re-verify without Milexium — see ADR-0009, 0012, 0017 |
| `core/` | D — Core/adaptive memory | v0.1 Exists (partial): task/model registry (`ModelRegistry`, closed `TASK_REGISTRY`) cataloging this repo's 5 real trained models from `docs/MODEL_CARDS.md`; memory tiers, parameter-delta registry, calibration/drift services all Specified — see ADR-0010 |
| `estate/` | C — data-estate layer | v0.1 Exists: manifest-gated acquisition (`AcquisitionManifest`, `acquire()` with free-space guard + quarantine + checksum + content-addressed promotion) and catalog inventory/free-space reporting; proves the governed `data/` estate — see ADR-0013 |
| `forecast/` | E — Forecast runtime | v0.1 Exists: `ForecastRuntime` serves a `ForecastVintage` from the registered champion model, hash-verifying the artifact before predicting; proven end-to-end on the real Access-A-Ride booster — see ADR-0016 |
| `decide/`, `replay/`, `explain/`, `forge/`, `fabric/`, `runtime/`, `edge/` | F, H, J, K, L | Not created yet — created when their upstream dependency has a versioned stub, per the dependency rules in `blueprint/19-agent-swarm-execution-system.md` |

Also present: `estate/` (Program C data-estate layer — see above).

**Owner:** whoever owns the corresponding workstream packet in `workstreams/`.

**Version policy:** a package's public interface is whatever it exports from
its top-level module; that surface follows the same immutable-contract rule as
`architecture/contracts/`.

**Test command:** `py -3 -m pytest packages/<name>/` once a package has tests.
