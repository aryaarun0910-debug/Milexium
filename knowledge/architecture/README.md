# knowledge/architecture/

Normative decisions, contracts, threat models, and formal specifications for the
Milexium expansion. This directory is the top of the authority order defined in
`blueprint/19-agent-swarm-execution-system.md` of the expansion plan
(`C:\Users\aryaa\Documents\Milexium Expansion plan`): safety/privacy/tenant
invariants first, then canonical domain semantics, then published contracts.

- **Owner:** Arya (accountable for all contract changes until a second engineer
  is named).
- **`decisions/`** — architecture decision records (ADRs). One file per decision,
  numbered sequentially, never edited after acceptance — superseding decisions
  get a new ADR that references the old one.
- **`platform/contracts/`** — normative schemas and interface definitions (JSON Schema,
  SQL DDL, protocol definitions). These are versioned; breaking changes require
  a new version and a migration note, not an in-place edit.
- **`threat-models/`** — per-capability threat models following
  `blueprint/10-security-privacy-and-ai-governance.md`.
- **`formal/`** — TLA+/SMT/Lean specifications for invariants that are load-bearing
  enough to warrant machine checking. Empty until a capability actually needs one;
  this is not populated speculatively.

**Version policy:** ADRs and contracts are immutable once accepted. Changes are
new numbered files, not edits, so history stays reconstructable.

**Test command:** none at this level — see `evidence/conformance/` for the executable
checks that enforce these contracts.
