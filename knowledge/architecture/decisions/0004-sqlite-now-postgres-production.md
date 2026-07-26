# ADR-0004: SQLite for the current demo, PostgreSQL/PostGIS as the pinned production target

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

The expansion plan's non-negotiable architecture states "PostgreSQL/PostGIS is
authoritative operational state" (`CLAUDE.md`, `SWARM_MANIFEST.yaml` global
invariants, `blueprint/14-execution-roadmap.md` Program C). `knowledge/docs/
MASTER_ROADMAP.md` independently specifies SQLite for the YC-deadline demo,
"document PostgreSQL as the production target," to avoid adding deployment
risk before the deadline.

This development machine has no Docker, no working WSL (`wsl --status`
errors with "Class not registered"), and had no PostgreSQL installed as of
the start of this session.

## Decision

- Treat SQLite as the **local development and demo** engine only — it
  satisfies the roadmap's zero-dependency demo requirement and lets Program A's
  conformance fixtures run without any infrastructure.
- Treat PostgreSQL 17 (with PostGIS) as the **pinned production target** for
  Program C, per the expansion plan's non-negotiable.
- PostgreSQL 17 was installed natively on this machine via
  `winget install --id PostgreSQL.PostgreSQL.17` on 2026-07-23 at the product
  owner's explicit request ("tell me what I need to download... for us to
  have no hindrance"), so that the target engine is available for Program C
  implementation work without blocking on further infrastructure decisions.
  The generated superuser password is stored locally at
  `%USERPROFILE%\.milexium_pg_dev_password.txt` (gitignored path, not
  committed) — see the session record in `knowledge/docs/JOURNAL.md` for the exact
  install outcome.
- PostGIS itself is **not yet installed** (it ships separately via Stack
  Builder or a standalone Windows build) and spatial columns are **not yet in
  the base canonical schema** (ADR-0002) — both remain "Specified" until a
  packet actually needs geometry (e.g. zone/facility geocoding), so as not to
  add an unused dependency now.
- All canonical SQL DDL is written in the portable subset (ADR-0002) so the
  same schema definition runs against either engine; a thin storage adapter
  in `app/canonical` selects the driver (`sqlite3` from the standard
  library now; `psycopg` added only when Program C actually connects to the
  installed Postgres instance).

## Consequences

- No code in this repository may claim "runs on PostgreSQL" as "Validated" or
  "Production" until it has actually been run against the installed instance
  with its own conformance fixtures — installing the engine is infrastructure
  readiness, not feature completion.
- Row-level security, PostGIS, replication, backup/restore, and connection
  pooling remain "Specified" in `IMPLEMENTATION_STATUS.md` regardless of the
  engine being installed.
- If Docker Desktop or a working WSL becomes available later, a containerized
  Postgres/PostGIS becomes the preferred dev target over the native install
  (easier to reset/version); this ADR does not preclude that — it only
  removes the current hindrance.
