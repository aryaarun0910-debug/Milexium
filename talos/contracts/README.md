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
| `jsonschema/operator-data-contract-v0.1.json` | What we must ask an operator for, field by field | generated from `operator_contract.py` | an agency's IT lead, answering yes / no / we-do-not-record-that per line |
| `OPERATOR_DATA_CONTRACT.md` | The same contract for an operations director, without a schema | generated from `operator_contract.py` | the outreach conversation |

## The operator data contract

Milexium holds **zero operator data**. `operator_contract.py` is the source of
truth for what would have to arrive, stated so that every field says what it
unlocks and what is lost without it — a field that cannot say both does not
belong in it, because an operator asked for everything gives nothing.

Both renderings are generated from that one module, so the document engineering
reads and the document an operations director signs off cannot say different
things.

`validate_operator_export.py` is the checkable half: point it at a sample export
and it reports, capability by capability, what that file can and cannot support.

```
py -3 talos/contracts/validate_operator_export.py sample.csv
py -3 talos/contracts/validate_operator_export.py sample.csv --declarations answers.json --json
```

It is a **contract, not a connector**. `themis/connect/operator_export.py` is the
adapter that ingests a real file and `forge/knowledge/docs/OPERATOR_DATA_INTAKE.md`
is the intake document an agency's counsel reads; this layer states what to ask
for and checks whether an answer arrived, and deliberately imports the identity
classifier from the adapter rather than growing a second one.

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
