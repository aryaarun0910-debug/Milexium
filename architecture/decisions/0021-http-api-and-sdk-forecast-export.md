# ADR-0021: HTTP/OpenAPI API + SDK forecast/export methods (Program M)

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

The SDK (ADR-0015) is the Python integration surface, but "other software
integrates Milexium" needs a language-neutral HTTP surface, and the SDK was
missing ergonomic access to the forecast runtime (ADR-0016) and evidence-pack
export (ADR-0017). `blueprint/08` Program M.

## Decision

**SDK** (`packages/sdk/client.py`):
- `export_pack(aggregate_id, outcome=None) -> EvidencePack` — mirrors
  `evidence_for` but returns the portable, independently-verifiable pack.
- `forecast(task, feature_row, *, horizon_start, horizon_end, issued_at,
  interval_half_width=None, registry, artifact_resolver)` — thin wrapper over
  `ForecastRuntime`. `registry`/`artifact_resolver` are **per-call keyword-only,
  not held on the client**: the canonical loop needs zero ML infra, so
  requiring a model catalog + resolver to construct a client would couple the
  ten-minute `in_memory` path to xgboost. `packages.forecast` is imported
  lazily to keep xgboost/pandas off the SDK import path.

**HTTP API** (`packages/api/`, FastAPI — already a pinned dependency):
- Seven endpoints mirroring the SDK: `GET /health`, `GET /version`,
  `POST /decisions`, `POST /decisions/{id}/overrides`, `GET .../evidence`,
  `GET .../evidence-pack`, `GET .../verify`. `create_app(client=None)` factory +
  module `app`.
- **Ingestion + forecast endpoints deliberately excluded from HTTP** — adapters
  are Python objects and model artifacts are on-disk files; they'd be dishonest
  as JSON bodies. Stated in the docstring; they stay on the SDK.
- `DecisionEvent` is projected to an API-owned `RecordedEvent` wire model (typed
  ids/enums → strings) so the HTTP contract is decoupled from the canonical
  entity; request bodies are `extra="forbid"`.
- Backed by one in-memory `MilexiumClient` (`check_same_thread=False`, async
  handlers, serial access); a real deployment injects a Postgres-backed store —
  noted.
- `verify` checks history first (404 on unknown aggregate) rather than reporting
  `verified=true` over zero rows.
- OpenAPI at `/openapi.json` is the machine-readable contract.
- Auth / multi-tenant gateway / rate limiting are **Specified, not faked**.

## Consequences

- Exists (Demonstrated on the in-memory loop): the two SDK methods, the HTTP API
  driving the full loop, the auto-generated OpenAPI contract. A tampered chain
  surfaces `verified=false` over HTTP (tested); an evidence pack re-verifies from
  the HTTP response bytes alone (tested).
- Tests use the real `fastapi.testclient.TestClient` (httpx present). A harmless
  starlette/httpx deprecation warning is emitted; not failing CI (no
  `filterwarnings=error`).
- Not built (Specified): auth, multi-tenant gateway, rate limiting, Postgres-store
  injection for the API, HTTP ingestion/forecast, CLI, TS/Rust SDKs.
