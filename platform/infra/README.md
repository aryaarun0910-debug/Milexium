# platform/infra/

Deployment and local-development infrastructure for the polyglot platform
(ADR-0026).

| Path | What |
|---|---|
| `compose/docker-compose.yml` | Local dev stack: PostgreSQL/PostGIS + MinIO (S3-compatible object storage) + OpenTelemetry collector. Requires Docker (see below). |
| `compose/.env.example` | Template for local secrets (copy to `.env`, gitignored). |
| `compose/otel-collector-config.yaml` | Minimal OTLP collector config. |

CI lives in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) — a
path-aware matrix: the Python suite runs on every push; the Rust and TypeScript
jobs activate automatically once `Cargo.toml` / `pnpm-workspace.yaml` exist.

## Status: the stack is up (2026-07-24, ADR-0032)

WSL2 + Docker Desktop are operational (Docker Engine 29.6.2, WSL2 kernel). The
compose stack runs:

```
docker compose -f platform/infra/compose/docker-compose.yml up -d
```

- **PostgreSQL 16 + PostGIS 3.4** on host port **5433** (not 5432 — the native
  PostgreSQL 17 from ADR-0006 keeps 5432; the container adds PostGIS and is the
  preferred dev target per ADR-0004).
- **MinIO** (S3-compatible object storage) — S3 API on `localhost:9000`, console
  on `:9001`. Backs `app/estate/object_store.py` (content-addressed
  immutable artifacts).
- **OpenTelemetry collector** — OTLP on `4317`/`4318`.

Copy `compose/.env.example` to `compose/.env` and set local secrets first (the
real `.env` is gitignored). Both PostGIS and object-storage blockers are now
cleared at the dev level (see `IMPLEMENTATION_STATUS.md`).

## Deferred (ADR-0026)

Multi-stage Dockerfiles per language (rust-builder, ts, python-worker, migration,
contract-gen, integration-test images), SBOM generation, pinned base-image
digests, and the full integration-test CI stage land with the Rust data-plane
services — not before. This directory holds the dev stack + CI foundation now.
