# packages/

Implementation packages, one per program from `SWARM_MANIFEST.yaml` in the
expansion plan. Each package owns a disjoint path; cross-package contract
changes require an ADR in `architecture/decisions/` first.

| Package | Program | Status |
|---|---|---|
| `canonical/` | A — canonical transport substrate | v0.1 Exists: entities, ids, time, state machine, vocab, event log (in-memory + SQLite), SemanticIndex interface, and (new) a PostgreSQL-backed store (`postgres_storage.py`) — see `IMPLEMENTATION_STATUS.md` |
| `verify/` | G — independent verifiers | v0.1 Exists: schema, state-transition, hash-chain verifiers |
| `connect/` | B — Milexium Connect | v0.1 Exists: generic adapter contract (`AdapterResult`/`QuarantinedRow`/`SemanticLossRecord`) plus two structurally different concrete adapters — `reference_agency` trips (fictional CSV) and NYC TLC FHVHV trips (real Parquet) — both → `ServiceRequest`; rest of blueprint/03's adapter surface Specified — see ADR-0007, ADR-0011 |
| `evidence/` | I — Evidence/Experience IR | v0.1 Exists: `EvidencePacket`/`ExperiencePacket` reconstructed from a `DecisionEvent` history plus independent hash-chain, schema, and (inapplicable, honestly flagged) state-transition verification — see ADR-0009, ADR-0012 |
| `core/` | D — Core/adaptive memory | v0.1 Exists (partial): task/model registry (`ModelRegistry`, closed `TASK_REGISTRY`) cataloging this repo's 5 real trained models from `docs/MODEL_CARDS.md`; memory tiers, parameter-delta registry, calibration/drift services all Specified — see ADR-0010 |
| `forecast/`, `decide/`, `replay/`, `explain/`, `forge/`, `fabric/`, `runtime/`, `edge/` | E, F, H, J, K, L | Not created yet — created when their upstream dependency has a versioned stub, per the dependency rules in `blueprint/19-agent-swarm-execution-system.md` |

**Owner:** whoever owns the corresponding workstream packet in `workstreams/`.

**Version policy:** a package's public interface is whatever it exports from
its top-level module; that surface follows the same immutable-contract rule as
`architecture/contracts/`.

**Test command:** `py -3 -m pytest packages/<name>/` once a package has tests.
