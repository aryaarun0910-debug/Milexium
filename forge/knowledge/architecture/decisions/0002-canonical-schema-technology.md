# ADR-0002: Canonical schema technology choice

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

Program A (`blueprint/04-milexiumdb-canonical-state.md`,
`blueprint/14-execution-roadmap.md` Program A) requires canonical bounded
contexts, typed identifiers, explicit time semantics, bitemporal records,
domain state machines, and relational/event projections, expressed as a
versioned normative contract per `forge/knowledge/architecture/contracts/`.

This repository's Python environment already has `pydantic` 2.x,
`jsonschema`, and `pytest` installed; it does not have `sqlalchemy`,
`psycopg2`, or any ORM. No database server is provisioned yet (ADR-0004).

## Decision

Define the canonical contract once, in Python, using Pydantic v2 models as
the source of truth, and derive two projections from it mechanically rather
than maintaining them by hand:

1. **JSON Schema** (via Pydantic's `model_json_schema()`) — the
   interchange/validation contract for non-Python consumers and for
   `aletheia/conformance/fixtures`.
2. **Portable SQL DDL** (hand-written, reviewed against the Pydantic model in
   a test) restricted to a subset that runs unmodified on both SQLite (the
   YC-demo target) and PostgreSQL (the documented production target):
   standard types only, no `JSONB`, no Postgres-only functions, no PostGIS
   spatial types in the base contract. Spatial columns are an explicit,
   separately versioned PostGIS extension contract added once Program C
   actually targets Postgres (see ADR-0004) — this keeps the base schema
   portable rather than silently Postgres-only.

Typed identifiers use `NewType`-style wrappers (e.g. `TenantId`, `RequestId`)
over `str` (UUIDv7-formatted) rather than bare strings, so a verifier can
reject a value of the wrong identifier kind at the type level in Python and
via a `pattern`/`format` constraint in the JSON Schema.

## Consequences

- The Pydantic model is the single hand-maintained artifact; JSON Schema and
  documentation examples are generated from it, so they cannot drift.
- The SQL DDL is hand-written and independently tested against the Pydantic
  model's field set (a conformance test fails if they diverge), rather than
  generated, because portable-subset SQL generation from Pydantic is not
  reliable enough to trust as a normative contract.
- No new runtime dependency is required for Program A's first version;
  `sqlalchemy`/`psycopg2` are deferred until Program C actually connects to a
  real Postgres instance (ADR-0004), avoiding an unused dependency in the
  interim.
- This defers, and does not solve, the harder MilexiumDB concerns (row-level
  security, PostGIS, replication, backup/restore) — those remain "Specified"
  in `IMPLEMENTATION_STATUS.md` until Program C is actually built out.
