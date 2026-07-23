# ADR-0005: SemanticIndex interface with an exact-search default; no vendoring yet

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

The expansion plan requires "TurboVec must be isolated behind a SemanticIndex
interface with exact-search and pgvector alternatives"
(top-level orchestration instructions; `blueprint/16-semantic-state-and-
turbovec.md`; dossier ledger entry 6, "TurboQuant and TurboVec"). The same
plan also requires that upstream projects are not vendored blindly — maturity,
license, and security must be independently reviewed first
(`blueprint/01-north-star-and-boundaries.md`, `blueprint/20-dossier-coverage-
ledger.md` interpretation section).

## Decision

Define a `SemanticIndex` protocol (Python `Protocol`/ABC) in
`packages/canonical` (or a future `packages/core` once Program D exists) with
the minimal operations Program D/I actually need: `upsert(id, vector,
metadata)`, `query(vector, k, filters)`, `delete(id)`, `rebuild()`. Ship one
reference implementation now:

- **`ExactSearchIndex`** — brute-force cosine/L2 similarity in NumPy. No
  external dependency beyond NumPy (already installed). This is the
  bounded-quality reference every faster backend must match, per the
  expansion's "every optimized implementation must retain an exact or
  bounded-quality reference and fallback."

Do **not** implement or vendor a `pgvector` adapter yet (no Postgres
connection wired up — ADR-0004) or a TurboVec adapter (no license/security/
maturity review has been done; vendoring it now would violate the
no-blind-vendoring rule). Both are recorded as `Specified` in
`workstreams/DOSSIER_COVERAGE.md` with an explicit follow-up ADR required
before any TurboVec code enters `third_party/`.

## Consequences

- Program D/I work that needs semantic retrieval can start against the
  `SemanticIndex` protocol and `ExactSearchIndex` today without waiting on a
  vendoring decision.
- Adding `pgvector` later is additive (a new class implementing the same
  protocol); it does not require changing callers.
- Adding TurboVec requires a dedicated ADR covering license, maintenance
  status, security review, and a benchmark showing it beats
  `ExactSearchIndex` on the actual retrieval workload before it can be
  promoted past "Specified."
