# infra/

Deployment and local-development infrastructure for the polyglot platform
(ADR-0026).

| Path | What |
|---|---|
| `compose/docker-compose.yml` | Local dev stack: PostgreSQL/PostGIS + MinIO (S3-compatible object storage) + OpenTelemetry collector. Requires Docker (see below). |
| `compose/.env.example` | Template for local secrets (copy to `.env`, gitignored). |
| `compose/otel-collector-config.yaml` | Minimal OTLP collector config. |

CI lives in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) — a
path-aware matrix: the Python suite runs on every push; the Rust and TypeScript
jobs activate automatically once `Cargo.toml` / `pnpm-workspace.yaml` exist.

## Prerequisite: Docker is not yet available on the dev machine

`docker` is not installed and WSL2 currently errors ("Class not registered").
The compose stack is written and ready; bringing it up needs WSL2 fixed and
Docker Desktop installed first. Until then, local dev uses the natively-installed
PostgreSQL 17 (ADR-0004/0006) and the SQLite path; object storage is Specified.

## Deferred (ADR-0026)

Multi-stage Dockerfiles per language (rust-builder, ts, python-worker, migration,
contract-gen, integration-test images), SBOM generation, pinned base-image
digests, and the full integration-test CI stage land with the Rust data-plane
services — not before. This directory holds the dev stack + CI foundation now.
