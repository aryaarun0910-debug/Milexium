/**
 * Unit tests for MilexiumClient. These assert the client builds the right HTTP
 * request (method, path, headers, body) for each endpoint and parses the
 * response -- all against a mocked `fetch`, so no running Milexium server is
 * required. Run with `node --test` (native TypeScript type stripping).
 */
import { test } from "node:test";
import assert from "node:assert/strict";

import { MilexiumApiError, MilexiumClient } from "../src/client.ts";
import type { RecordedEvent, VerifyResponse } from "../src/types.ts";

interface CapturedInit {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
}
interface Captured {
  url: string;
  init: CapturedInit;
}

/** Build a client wired to a mock fetch that records every call and returns a
 * canned JSON response. */
function stubClient(
  response: { status?: number; body?: unknown } = {},
  options: { headers?: Record<string, string> } = {},
): { client: MilexiumClient; calls: Captured[] } {
  const calls: Captured[] = [];
  const status = response.status ?? 200;
  const fetchImpl = (async (input: unknown, init?: unknown) => {
    calls.push({ url: String(input), init: (init ?? {}) as CapturedInit });
    const payload =
      response.body === undefined ? "" : JSON.stringify(response.body);
    return new Response(payload, {
      status,
      headers: { "content-type": "application/json" },
    });
  }) as unknown as typeof fetch;

  const client = new MilexiumClient({
    baseUrl: "http://api.test",
    fetch: fetchImpl,
    ...(options.headers ? { headers: options.headers } : {}),
  });
  return { client, calls };
}

const sampleEvent: RecordedEvent = {
  event_id: "evt-1",
  tenant_id: "tenant-1",
  aggregate_id: "req-1",
  aggregate_type: "ServiceRequest",
  sequence: 1,
  occurred_at: "2026-07-24T00:00:00Z",
  actor_type: "system",
  actor_id: "system",
  event_type: "recommendation",
  payload: { assigned_vehicle_id: "veh-9" },
  reason_codes: [],
  idempotency_key: null,
  prev_hash: null,
  hash: "abc123",
};

test("health() issues GET /health with no body", async () => {
  const { client, calls } = stubClient({ body: { status: "ok" } });
  const result = await client.health();

  assert.equal(calls.length, 1);
  const call = calls[0]!;
  assert.equal(call.url, "http://api.test/health");
  assert.equal(call.init.method, "GET");
  assert.equal(call.init.body, undefined);
  assert.equal(call.init.headers?.accept, "application/json");
  assert.equal(call.init.headers?.["content-type"], undefined);
  assert.deepEqual(result, { status: "ok" });
});

test("version() issues GET /version", async () => {
  const { client, calls } = stubClient({
    body: { api_version: "0.1.0", sdk_version: "0.1.0", contract_version: "0.1" },
  });
  const result = await client.version();

  assert.equal(calls[0]!.url, "http://api.test/version");
  assert.equal(calls[0]!.init.method, "GET");
  assert.equal(result.api_version, "0.1.0");
});

test("recordDecision() POSTs /decisions with JSON body and content-type", async () => {
  const { client, calls } = stubClient({ status: 201, body: sampleEvent });
  const result = await client.recordDecision({
    aggregate_id: "req-1",
    payload: { assigned_vehicle_id: "veh-9" },
  });

  const call = calls[0]!;
  assert.equal(call.url, "http://api.test/decisions");
  assert.equal(call.init.method, "POST");
  assert.equal(call.init.headers?.["content-type"], "application/json");
  assert.deepEqual(JSON.parse(call.init.body!), {
    aggregate_id: "req-1",
    payload: { assigned_vehicle_id: "veh-9" },
  });
  assert.deepEqual(result, sampleEvent);
});

test("recordDecision() forwards optional fields verbatim when provided", async () => {
  const { client, calls } = stubClient({ status: 201, body: sampleEvent });
  await client.recordDecision({
    aggregate_id: "req-1",
    payload: { x: 1 },
    actor_id: "planner-svc",
    reason_codes: ["PICKUP_WINDOW"],
    idempotency_key: "key-1",
  });

  assert.deepEqual(JSON.parse(calls[0]!.init.body!), {
    aggregate_id: "req-1",
    payload: { x: 1 },
    actor_id: "planner-svc",
    reason_codes: ["PICKUP_WINDOW"],
    idempotency_key: "key-1",
  });
});

test("recordOverride() puts aggregateId in the path and body carries the rest", async () => {
  const { client, calls } = stubClient({ status: 201, body: sampleEvent });
  await client.recordOverride("req-1", {
    payload: { assigned_vehicle_id: "veh-2" },
    actor_id: "dispatcher-jane",
  });

  const call = calls[0]!;
  assert.equal(call.url, "http://api.test/decisions/req-1/overrides");
  assert.equal(call.init.method, "POST");
  assert.deepEqual(JSON.parse(call.init.body!), {
    payload: { assigned_vehicle_id: "veh-2" },
    actor_id: "dispatcher-jane",
  });
});

test("evidence() issues GET .../evidence", async () => {
  const { client, calls } = stubClient({ body: { aggregate_id: "req-1" } });
  await client.evidence("req-1");
  assert.equal(calls[0]!.url, "http://api.test/decisions/req-1/evidence");
  assert.equal(calls[0]!.init.method, "GET");
});

test("evidencePack() issues GET .../evidence-pack", async () => {
  const { client, calls } = stubClient({ body: { manifest: {} } });
  await client.evidencePack("req-1");
  assert.equal(calls[0]!.url, "http://api.test/decisions/req-1/evidence-pack");
  assert.equal(calls[0]!.init.method, "GET");
});

test("verify() issues GET .../verify and returns the parsed result", async () => {
  const body: VerifyResponse = {
    aggregate_id: "req-1",
    verified: true,
    violations: [],
  };
  const { client, calls } = stubClient({ body });
  const result = await client.verify("req-1");
  assert.equal(calls[0]!.url, "http://api.test/decisions/req-1/verify");
  assert.equal(result.verified, true);
});

test("aggregate ids are URL-encoded into the path", async () => {
  const { client, calls } = stubClient({ body: { aggregate_id: "a/b c" } });
  await client.evidence("a/b c");
  assert.equal(calls[0]!.url, "http://api.test/decisions/a%2Fb%20c/evidence");
});

test("a trailing slash on baseUrl is normalised away", async () => {
  const calls: Captured[] = [];
  const fetchImpl = (async (input: unknown) => {
    calls.push({ url: String(input), init: {} });
    return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
  }) as unknown as typeof fetch;
  const client = new MilexiumClient({ baseUrl: "http://api.test/", fetch: fetchImpl });
  await client.health();
  assert.equal(calls[0]!.url, "http://api.test/health");
});

test("custom headers are sent on every request", async () => {
  const { client, calls } = stubClient(
    { body: { status: "ok" } },
    { headers: { authorization: "Bearer t0ken" } },
  );
  await client.health();
  assert.equal(calls[0]!.init.headers?.authorization, "Bearer t0ken");
});

test("a non-2xx response throws MilexiumApiError with status and parsed body", async () => {
  const errorBody = { detail: [{ loc: ["body", "payload"], msg: "field required", type: "missing" }] };
  const { client } = stubClient({ status: 422, body: errorBody });

  await assert.rejects(
    () => client.recordDecision({ aggregate_id: "req-1", payload: {} }),
    (err: unknown) => {
      assert.ok(err instanceof MilexiumApiError);
      assert.equal(err.status, 422);
      assert.equal(err.url, "http://api.test/decisions");
      assert.deepEqual(err.body, errorBody);
      return true;
    },
  );
});

test("constructing without any fetch throws a clear error", () => {
  const original = globalThis.fetch;
  try {
    // @ts-expect-error -- deliberately remove the global to simulate an old runtime
    globalThis.fetch = undefined;
    assert.throws(() => new MilexiumClient({ baseUrl: "http://api.test" }), TypeError);
  } finally {
    globalThis.fetch = original;
  }
});
