# ADR-0001: Adopt the expansion blueprint and initialize the control plane

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

A separate specification root, `C:\Users\aryaa\Documents\Milexium Expansion
plan`, describes a long-term platform architecture (canonical transport
substrate, MilexiumDB, Core/Forecast, Decide, Verify, Replay/Explain,
Forge/Fabric, Runtime, Edge, and a product/API surface — programs A-M in
`SWARM_MANIFEST.yaml`) implemented through contract-driven parallel agent work.

This repository also carries an active, dated backlog,
`docs/MASTER_ROADMAP.md`, targeting the YC Fall 2026 application deadline
(27 July 2026), which explicitly deferred new platform/database buildout
("scope kill list") until after submission.

On 2026-07-23, after the conflict between these two documents was raised,
the product owner (Arya) directed: proceed with the full expansion now
rather than deferring it, record the work in `docs/JOURNAL.md`, and pause at
defined checkpoints for review rather than running the entire blueprint
unattended.

## Decision

1. Adopt the expansion plan as the normative long-term product/architecture
   specification, with the authority order defined in its `CLAUDE.md` and
   `blueprint/19-agent-swarm-execution-system.md`: safety/privacy/tenant
   invariants > canonical domain semantics > published contracts > evidence/
   verifier/replay contracts > benchmark definitions > implementation design >
   optimization preferences.
2. Create the root control-plane directories specified in
   `blueprint/19-agent-swarm-execution-system.md`: `architecture/`,
   `packages/`, `conformance/`, `benchmarks/`, `research/`, `third_party/`,
   `ops/`, plus `workstreams/` for work-packet tracking and the dossier
   coverage ledger.
3. Use the exact status vocabulary from the expansion plan's `README.md`
   everywhere in this repository from now on: **Exists**, **Specified**,
   **Demonstrated**, **Validated**, **Production**. Never promote a
   "Specified" or "Demonstrated" claim into "Validated" without consented
   operator data against a declared baseline.
4. Preserve the existing Milexium product (real-data forecasting pipeline in
   `realdata/`, `ntd/`, `kaggle/`, the fictional reference-agency scheduler
   demo in `reference_agency/`) unchanged; the expansion extends it through
   new packages rather than modifying or deleting working evidence.
5. Build in dependency order per `SWARM_MANIFEST.yaml`: Program A (canonical
   substrate) has no dependencies and is built first as a versioned stub;
   downstream programs begin against that stub rather than waiting for a
   final implementation.
6. Do not create or restore a `web/` package — the website and domain remain
   owned separately by Chris, per both the expansion plan and this
   repository's existing `README.md`.

## Consequences

- Every future claim in this repository (docs, YC materials, code comments)
  must be checkable against this vocabulary; `IMPLEMENTATION_STATUS.md` is the
  living source of truth for what is actually Exists vs. Specified.
- Because this repository has no provisioned cloud infrastructure (no Docker,
  no working WSL, no existing Postgres, no object storage, no GPU cluster),
  early programs will mostly produce versioned contracts, local reference
  implementations, and conformance fixtures rather than deployed, "Production"
  capabilities. See ADR-0004 for the database-specific consequence.
- The YC submission's actual demo path (SQLite-backed, per
  `docs/MASTER_ROADMAP.md`) is not modified by this work; the canonical schema
  built under Program A is designed to serve both the roadmap's MilexiumDB
  vertical-slice task and the expansion's Program A contract, since they
  describe the same entities.
- Work proceeds continuously but stops at defined checkpoints (end of each
  major packet or tranche of parallel packets) for the product owner to
  review and redirect, rather than running unattended to blueprint
  completion in one pass.
