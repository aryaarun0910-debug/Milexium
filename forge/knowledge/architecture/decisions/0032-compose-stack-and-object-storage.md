# ADR-0032: Local compose stack (PostGIS + MinIO + OTel) and the object-storage path

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

With WSL2 + Docker Desktop now operational (Docker Engine 29.6.2, Compose,
WSL2 kernel), two long-standing blockers can be cleared at the infra level:
PostGIS (was "not installed", ADR-0004) and object storage (was "Specified —
no S3 credentials", IMPLEMENTATION_STATUS blockers). The compose stack from
ADR-0026 (`talos/infra/compose/docker-compose.yml`) can be brought up.

## Decision

**Brought up the dev stack** (`docker compose -f talos/infra/compose/docker-compose.yml
up -d`): PostgreSQL 16 + **PostGIS 3.4** (GEOS/PROJ/STATS confirmed), **MinIO**
(S3-compatible), and an **OpenTelemetry collector** — all healthy.

- **Postgres host port is 5433, not 5432** (`docker-compose.yml` updated), so
  the containerized PostGIS coexists with the natively-installed PostgreSQL 17
  that already holds 5432 (ADR-0006). The native instance remains the target of
  the existing `PostgresCanonicalStore` tests; the container adds PostGIS and is
  the ADR-0004 "preferred dev target once Docker is available."
- **Secrets** live in `talos/infra/compose/.env` (gitignored, generated locally, no
  BOM), supplied to compose via `${VAR:?}` — never baked into an image or
  committed. `talos/infra/compose/.env.example` is the committed template.

**Wired the first real object-storage path** — `themis/estate/object_store.py`
`MinioObjectStore`: **content-addressed** S3 storage where an object's key *is*
its sha256, so storage is inherently deduplicated, a read verifies the bytes
hash back to the key (tamper/corruption-evident on every `get`, the same
integrity stance as the event-log hash chain), and keys are stable portable
references for manifests. `minio` is an optional dependency (the `objectstore`
extra), imported lazily, so importing the estate package never requires it.
Credentials are read at runtime from `talos/infra/compose/.env` or the environment.

## Consequences

- **Program C's "immutable object storage" is now Exists (dev)** — a
  round-trip conformance test (`test_object_store.py`) puts/gets/dedups a real
  object against the running MinIO and proves read-time integrity (a
  corrupted-key object is rejected). It **skips cleanly** when `minio` isn't
  installed or MinIO isn't up, so CI and clean clones stay green.
- **PostGIS is available** for the routing/spatial work (Program F/H travel-time
  matrices, the OSM `networks/` estate) — the extension is confirmed loaded; no
  canonical entity uses geometry yet, so wiring a spatial column is a later
  additive step.
- The estate's default object path remains local disk; `MinioObjectStore` is an
  additive backend. Backing the estate's raw zone with MinIO (promote objects to
  S3 by content-address) is the natural next step, deliberately not forced now.
- Not built (Specified): TLS on the dev endpoints, tenant-scoped bucket
  prefixes/credentials, lifecycle/retention policies on the bucket, and pointing
  `PostgresCanonicalStore` at the containerized PostGIS (the native instance
  still serves the tests). A production object store uses real cloud credentials
  and per-tenant isolation, not the dev MinIO root user.
