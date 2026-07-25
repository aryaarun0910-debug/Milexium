# ADR-0061: Measuring the surface moved the defect

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-M-INTERACTIVE-LATENCY-009
- **Corrects:** ADR-0056's characterisation of the interactive-latency defect

## Context, and the correction

ADR-0056 recorded: *"46 s synchronous on the interactive surface — broken today,
at current volume, with no growth required."* **That is not what `POST /teardowns`
does.** `MAX_TEARDOWN_SEGMENTS = 20_000` already bounded the accepted path to
~0.6–2.0 s.

The defect is real but it is in the **refusal**, not the acceptance. The count
guard sits *inside* the handler, so FastAPI validates every segment before the
ceiling is consulted. A 600,000-segment body — the top of ADR-0056's own
operator-year band, and precisely the request that ADR invites a reader to
send — burnt **7.4–31.3 s of CPU to compute nothing and answer 413**.

ADR-0056 reasoned from the analysis benchmark to the surface without measuring
the surface. The lesson is narrow and worth keeping: **a latency claim about a
component you did not instrument is a hypothesis.**

## Decision

Four changes, all on a `_TeardownRoute(APIRoute)` wrapper — not middleware, not a
bare `Request` handler, because the declared body model *is* the OpenAPI refusal
surface (`additionalProperties: false`, no `is_guaranteed_saving`, no
`causal_proof`). The contract diff is description-only.

1. `MAX_TEARDOWN_BODY_BYTES` (8 MiB), refused from `content-length` **before the
   body is read**.
2. A bounded LRU of serialised responses keyed on the **raw request bytes**.
3. Honest 413 text naming the actual limit hit.
4. `MilexiumClient.estimate_teardown_seconds(n)`, so the SDK's unbounded path
   states its cost rather than hanging silently.

**Rejected, with reasons:** *async job + poll* — needs auth the app documents it
lacks (a job id is a bearer handle to operator data), and a GIL-bound teardown in
a `BackgroundTask` blocks every other request, which is strictly worse.
*Streaming* — a teardown produces its answer only at the end. *Keying the cache
on `segment_sha256`* — semantically stronger, but it costs the parse plus ~50% of
the runtime (ADR-0056), saving half instead of ~98%.

## Consequences

| request | before (busy/quiet) | after (busy/quiet) |
|---|---:|---:|
| 20,000 segments, 2.37 MB | 1.530 / 0.607 s | 1.984 / 0.542 s |
| same body again | 1.530 / 0.607 s | 0.046 / 0.011 s |
| 25,000 → 413 (count guard) | 0.595 / 0.221 s | 0.620 / 0.241 s |
| 600,000, 71 MB → 413 | 31.269 / 7.378 s | 0.076 / 0.025 s |

**The absolute seconds describe the laptop.** ADR-0056 warned of a 2.8× thermal
swing; between these two runs it was **4.2×**. So the defensible claims are
ratios: refusal **295–411×**, warm repeat **33–55×**, and **cold path unchanged**
(1.30× slower busy, 0.89× *faster* quiet — the bracket around 1.0 is what settles
it).

**The cold path is not fixed and is not claimed to be.** A first 20k teardown
still costs 0.54–1.98 s; a first operator-year teardown on the SDK still costs
~46–55 s.

### The drift gate has a hole, found rather than assumed

Bumping `API_VERSION` changes the contract JSON and produces a **byte-identical**
`openapi.ts` — `openapi-typescript` emits only `paths`/`components`/`operations`,
never `info`. **Gate B is a "types moved" detector, not a "spec moved"
detector**; the chain holds only because gate A covers upstream. Local halves
were added in both languages, since CI-only gates are what let the drift happen
in the first place.

### A fifth test that proved nothing

11 mutations, all GREEN→RED→restored. **Two came back NOT PROVEN on the first
pass and both were real.** One mutation was a no-op. The other exposed that
`test_a_refusal_is_never_cached` asserted an **unreachable branch** — refusals are
*raised*, and Starlette's exception middleware sits outside the wrapper, so they
never reach the store branch at all. It now asserts the mechanism (no cache
header on any refusal), and the code comment says so rather than implying the
`if` is what holds the line.

**28 new pytest, 6 new node.** Full tree 1832 passed; TS 19/19; typecheck clean.

## Honest limitations

- **The cache key is byte-exact, not semantic.** Identical segments with
  different JSON key order, whitespace, or `+00:00` vs `Z` will miss. Deliberate:
  a miss is merely slow.
- **Refusal is only cheap above 8 MiB.** Bodies between 20,001 and ~70,788
  segments still pay full validation — 0.24–0.62 s at 25k, 3.88 s at 70,788.
  Bounded at a few seconds, not eliminated. Closing that band means refusing
  legal 20k bodies.
- **The byte ceiling can refuse a legal request.** `run_ref` is unbounded, so 20k
  segments with >~400-byte run_refs are refused on size. The 413 says exactly
  that.
- **The cache is process-local** and dies on restart; an N-worker deployment gets
  ≤1/N hit rate.
- **Timing side channel**, judged negligible: a fast response reveals that
  someone submitted the identical body, but you must already hold those exact
  bytes to observe it. Named because the app has no auth at all.
- **Measured on a loopback TestClient** — no network or TLS, so the real-world
  ratio will be smaller than 55×.
- **`POST /operator-exports/validate` has the same shape of defect, unfixed** —
  its row guard is also post-parse. Smaller (`list[dict]` vs Pydantic models), so
  named in the code rather than fixed unmeasured.
- **The TS client still cannot call the teardown.** `/teardowns` and
  `/operator-exports/validate` exist in the generated *types* but have no
  `client.ts` method. Now the most visible gap on that SDK.
- Synthetic fixtures only. Status stays **Demonstrated**.
