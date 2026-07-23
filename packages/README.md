# packages/

Implementation packages, one per program from `SWARM_MANIFEST.yaml` in the
expansion plan. Each package owns a disjoint path; cross-package contract
changes require an ADR in `architecture/decisions/` first.

| Package | Program | Status |
|---|---|---|
| `canonical/` | A — canonical transport substrate | v0.1 Exists: entities, ids, time, state machine, vocab, event log (in-memory + SQLite), SemanticIndex interface, and (new) a PostgreSQL-backed store (`postgres_storage.py`) — see `IMPLEMENTATION_STATUS.md` |
| `verify/` | G — independent verifiers | v0.1 Exists: schema, state-transition, hash-chain verifiers |
| `connect/` | B — Milexium Connect | v0.1 Exists: generic adapter contract (`AdapterResult`/`QuarantinedRow`/`SemanticLossRecord`) plus one concrete adapter (`reference_agency` trips → `ServiceRequest`); rest of blueprint/03's adapter surface Specified — see ADR-0007 |
| `evidence/` | I — Evidence/Experience IR | v0.1 Exists: `EvidencePacket`/`ExperiencePacket` reconstructed from a `DecisionEvent` history plus independent hash-chain verification — see ADR-0009 |
| `core/`, `forecast/`, `decide/`, `replay/`, `explain/`, `forge/`, `fabric/`, `runtime/`, `edge/` | D, E, F, H, J, K, L | Not created yet — created when their upstream dependency has a versioned stub, per the dependency rules in `blueprint/19-agent-swarm-execution-system.md` |

**Owner:** whoever owns the corresponding workstream packet in `workstreams/`.

**Version policy:** a package's public interface is whatever it exports from
its top-level module; that surface follows the same immutable-contract rule as
`architecture/contracts/`.

**Test command:** `py -3 -m pytest packages/<name>/` once a package has tests.
