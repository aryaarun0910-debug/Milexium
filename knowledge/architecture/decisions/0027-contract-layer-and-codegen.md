# ADR-0027: The platform/contracts/ layer and code generation

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

A polyglot system (ADR-0026) must not hand-write three copies of the same
entity. Chris's brief specifies one authoritative contract layer generating
Rust/TypeScript/Python clients via Protobuf + Buf. The constraint: `buf`,
`protoc`, and Docker are not installed, and the Python Pydantic models are
already the working, tested source of truth.

## Decision

Establish `platform/contracts/` as the single contract home, populated by generation
from the Python source of truth so artifacts cannot drift:

```
platform/contracts/
  jsonschema/   canonical-v0.1.json   (generated from app.canonical Pydantic models)
  openapi/      milexium-api-v0.1.json (generated from the FastAPI app)
  proto/        seed .proto (transport contract; Buf codegen deferred)
  sql/          pointer to the portable DDL (app/canonical/sql/schema_v0_1.sql)
  generate.py   regenerates jsonschema + openapi
```

**Contract hierarchy** (whose invariant each layer enforces), per the brief:

- Pydantic canonical models + `app/canonical/sql/schema_v0_1.sql` are the
  **current** authoritative source (domain + persistence invariants).
- **JSON Schema** — portable validation / plugin descriptors, generated.
- **OpenAPI** — the supported external HTTP surface, generated from FastAPI.
- **Protobuf** — the *transport* contract for future internal RPC. Seeded as a
  hand-maintained `.proto`; **Buf codegen (Rust/TS/Python clients, lint,
  breaking-change detection) is deferred** until the `buf`/`protoc` toolchain is
  installed. Recorded, not skipped.
- **Arrow schemas** — columnar analytical interchange; deferred with the Rust
  data-plane work.

`platform/contracts/generate.py` regenerates JSON Schema + OpenAPI; a CI drift check
(ADR-0026 infra) fails if the committed artifacts don't match a fresh
generation, so the contract can never silently diverge from the code.

## Consequences

- One source of truth today (Python), portable artifacts generated from it —
  the TS SDK generates its types from `platform/contracts/openapi/…`, the Rust verifier
  reads `platform/contracts/jsonschema/…` for reference.
- When Buf/protoc land, Protobuf becomes the transport contract and codegen
  produces clients for all three languages; the Pydantic models can then be
  generated *from* proto, or proto generated from them — that direction is a
  follow-up ADR, deliberately not decided now to avoid a premature toolchain
  commitment.
- No new heavy dependency was installed to establish the layer; it is pure
  generation from what already exists.
