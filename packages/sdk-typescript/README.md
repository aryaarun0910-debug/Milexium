# @milexium/sdk

Typed TypeScript client for the **Milexium HTTP API** — the language-neutral
surface so software that is *not* written in Python can integrate the decision
runtime.

The request/response types are **generated from the OpenAPI contract**
(`contracts/openapi/milexium-api-v0.1.json`), not hand-written, so they cannot
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
