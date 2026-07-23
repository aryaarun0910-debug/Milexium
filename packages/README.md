# packages/

Implementation packages, one per program from `SWARM_MANIFEST.yaml` in the
expansion plan. Each package owns a disjoint path; cross-package contract
changes require an ADR in `architecture/decisions/` first.

| Package | Program | Status |
|---|---|---|
| `canonical/` | A — canonical transport substrate | In progress (see `IMPLEMENTATION_STATUS.md`) |
| `connect/`, `core/`, `forecast/`, `decide/`, `verify/`, `replay/`, `explain/`, `forge/`, `fabric/`, `runtime/`, `edge/` | B, D, E, F, G, H, I, J, K, L | Not created yet — created when their upstream dependency has a versioned stub, per the dependency rules in `blueprint/19-agent-swarm-execution-system.md` |

**Owner:** whoever owns the corresponding workstream packet in `workstreams/`.

**Version policy:** a package's public interface is whatever it exports from
its top-level module; that surface follows the same immutable-contract rule as
`architecture/contracts/`.

**Test command:** `py -3 -m pytest packages/<name>/` once a package has tests.
