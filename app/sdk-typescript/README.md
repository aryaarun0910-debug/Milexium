# @milexium/sdk

Typed TypeScript client for the **Milexium HTTP API** — the language-neutral
surface so software that is *not* written in Python can integrate the decision
runtime.

The request/response types are **generated from the OpenAPI contract**
(`platform/contracts/openapi/milexium-api-v0.1.json`), not hand-written, so they cannot
drift from the canonical domain. `MilexiumClient` is a thin, typed wrapper over
`fetch` — one method per endpoint, no domain logic.

## Quickstart

```ts
import { MilexiumClient } from "@milexium/sdk";

const client = new MilexiumClient({ baseUrl: "http://localhost:8000" });

await client.health();                          // { status: "ok" }
const rec = await client.recordDecision({       // POST /decisions (a system act)
  aggregate_id: "req-42",
  payload: { assigned_vehicle_id: "veh-9" },
});
await client.recordOverride("req-42", {         // POST .../overrides (a human act)
  payload: { assigned_vehicle_id: "veh-2" },
  actor_id: "dispatcher-jane",
});
const packet = await client.evidence("req-42");        // reconstructed EvidencePacket
const pack = await client.evidencePack("req-42");       // portable, self-verifying pack
const check = await client.verify("req-42");            // independent hash-chain check
console.log(rec.hash, packet.integrity_verified, check.verified);
```

A non-2xx response throws `MilexiumApiError` (`.status`, `.url`, `.body`).

## API surface

| Method | HTTP |
| --- | --- |
| `health()` | `GET /health` |
| `version()` | `GET /version` |
| `recordDecision(body)` | `POST /decisions` |
| `recordOverride(aggregateId, body)` | `POST /decisions/{aggregate_id}/overrides` |
| `evidence(aggregateId)` | `GET /decisions/{aggregate_id}/evidence` |
| `evidencePack(aggregateId)` | `GET /decisions/{aggregate_id}/evidence-pack` |
| `verify(aggregateId)` | `GET /decisions/{aggregate_id}/verify` |

`recordDecision` requires `aggregate_id` + `payload`; `recordOverride` requires
`payload` + `actor_id`. Every other body field (`actor_id`, `aggregate_type`,
`reason_codes`, `occurred_at`, `idempotency_key`) is optional and defaulted by
the server — matching the contract's `required` set.

## Scripts

```bash
npm run generate    # regenerate src/generated/openapi.ts from the OpenAPI contract
npm run typecheck   # tsc --strict, no emit
npm run build       # emit dist/ (JS + .d.ts)
npm test            # node --test (mocked fetch, no server needed)
```

Types are regenerated with [`openapi-typescript`](https://github.com/openapi-ts/openapi-typescript)
directly from the committed contract, so `src/generated/openapi.ts` stays a
faithful projection of the API. Re-run `npm run generate` whenever the contract
changes.

### Drift

"Whenever the contract changes" was not enough on its own: the generated file
once went **835 lines stale** while two endpoints landed, because nothing
checked. Two things check now, and they are deliberately different:

- **CI** (`.github/workflows/ci.yml`, TypeScript job) regenerates and fails on
  any diff. Byte-exact, so it also catches formatting and generator-version
  drift — and it only runs on a runner.
- **`npm test`** (`test/generated-drift.test.ts`) asserts every path,
  operation and schema in the committed contract is present in the generated
  types. Weaker than byte equality, and it runs on your machine before you push.

The contract JSON is itself generated from `app/api/app.py`, so the full
chain is `app/api/app.py → platform/contracts/openapi/*.json →
src/generated/openapi.ts`, with a gate on each link. Note the second gate is
blind to the spec's `info` block — `openapi-typescript` emits only
`paths`/`components`/`operations`, so an API version bump changes the contract
and produces byte-identical TypeScript. The first gate is what covers that.

**Known gap:** `src/client.ts` has methods for the six decision-loop endpoints
only. `POST /teardowns` and `POST /operator-exports/validate` exist in the
generated **types** but have no client method yet, so calling them from
TypeScript means hand-writing a `fetch` against the generated types.
