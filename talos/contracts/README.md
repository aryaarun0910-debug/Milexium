# talos/contracts/

The single authoritative contract layer for the polyglot platform
(ADR-0026, ADR-0027). One entity is never hand-written three times: the
portable artifacts here are **generated from the Python source of truth** so
Rust, TypeScript, and Python all bind to the same definitions.

| Path | What it is | Source | Consumed by |
|---|---|---|---|
| `jsonschema/canonical-v0.1.json` | The 12 canonical entities as JSON Schema | generated from `themis.canonical` Pydantic models | portable validation, plugin descriptors, the Rust verifier's reference |
| `openapi/milexium-api-v0.1.json` | The public HTTP surface (7 endpoints) | generated from the FastAPI app (`argus/api`) | the TypeScript SDK (`argus/sdk-typescript`) generates its types from this |
| `proto/` | Transport-contract seed for future internal RPC | hand-maintained `.proto` | Buf codegen (deferred — see ADR-0027) |
| `sql/` | Pointer to the portable persistence DDL | `themis/canonical/sql/schema_v0_1.sql` | Postgres + SQLite |

## Regenerate

```
py -3 talos/contracts/generate.py
```

CI runs this and fails if the committed artifacts differ from a fresh
generation — the contract can never silently drift from the code.

## Deferred (ADR-0026 / 0027)

Protobuf + Buf codegen (Rust/TS/Python clients, lint, breaking-change
detection), and Arrow schemas for the columnar analytical boundary, land with
the Rust data-plane work and the `buf`/`protoc` toolchain — not before. The
`proto/` seed exists so the transport contract has a home now.
