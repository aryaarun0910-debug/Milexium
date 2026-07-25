# ADR-0042: Exposing the teardown and export validation over HTTP/SDK

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-M-TEARDOWN-SURFACE-004

## Context

Program M exists so other software integrates Milexium **without writing
Python** (ADR-0015/0021). But the two capabilities a design partner would
actually want — the deadhead teardown (ADR-0039) and the operator-export intake
(ADR-0038) — were reachable only by importing Python.

ADR-0021 deliberately excluded ingestion and forecast from HTTP because their
inputs are Python objects and on-disk model files, which do not belong as JSON.
That reasoning had to be applied honestly here rather than assumed to extend.

## Decision

**`POST /teardowns` — JSON body, not a file upload.** ADR-0021's objection does
not apply: a `VehicleSegment` is four scalars, so it already *is* a JSON object.
The endpoint uses `packages.replay`'s own `VehicleSegment`/`CostBasis` as the
body types rather than API-local copies, so the domain's construction rules
(UTC-aware, end-not-before-start, 48h ceiling, `extra="forbid"` blocking a rider
field) are enforced on the wire and cannot drift from the module. Bounded at
20,000 segments → **413 pointing at the SDK**, never a silently truncated
teardown, because truncation understates every total it reports.

**`POST /operator-exports/validate` — JSON rows + JSON `column_map`.** Lets an
agency check their extract *before* sending real data — directly the friction
`docs/OPERATOR_DATA_INTAKE.md` describes. No Python object crosses the boundary
and nothing is ingested, so ADR-0021's objection has nothing to bite on.

**`MilexiumClient.teardown_deadhead()`** — a pass-through, so one import drives
it.

### Deliberately not built

- **No multipart/CSV upload.** It would pull CSV parsing and header handling
  into the API (Connect adapter work with an owner), and Starlette spools
  uploads to a temp *file* — an endpoint whose headline promise is "persists
  nothing" must not begin by writing the operator's export to disk. JSON stays
  in memory, which is what makes the claim checkable rather than merely stated.
- **No "tear down my raw export" endpoint.** That requires deciding which rows
  are revenue versus deadhead, and `teardown.py` explicitly refuses to infer it.
  An endpoint that guessed would invent the one judgment the module declines to
  make.
- Generic ingestion and forecast stay SDK-only, unchanged.

The API names `OperatorExportAdapter` directly while the SDK stays generic over
`SourceAdapter` — a caller cannot hand a URL a Python class, but an SDK that
named adapters would need changing for every new one.

## Consequences

**21 new tests (33 with the existing API suite).** Each invariant is proved
rather than asserted in prose:

- **The refusals survive the boundary.** `TeardownRequest` is `extra="forbid"`,
  so `is_guaranteed_saving`, `causal_proof`, `guaranteed_saving_usd`,
  `is_modelled:false`, and `is_guaranteed_saving` nested inside `cost_basis` all
  return **422 — refused, not ignored**. The published OpenAPI carries
  `additionalProperties: false` and no such fields, so a generated client in any
  language sees they do not exist. The `data_provenance` enum in the artifact is
  exactly `["real_public","synthetic"]` — there is still no "operator" value.
- **The hedged wording reaches the response** because the endpoint returns
  `DeadheadTeardown` *itself*, not a projection; re-projecting would create a
  second place `interpretation`/`hedge`/`envelope_basis` could be dropped.
  Asserted verbatim against `DEADHEAD_TEARDOWN_NOTE` and `FIXED_COST_HEDGE`.
- **PII fail-closed, tightened.** The validation response returns offending
  **column names**, derived from the adapter's own `REDACTION_MARKER`
  substitution rather than a re-implemented check, and never the quarantine
  record. Asserted against the **raw response text**, not a parsed subset.
  Semantic-loss notes are projected **without `source_value`**, so the guarantee
  does not depend on the adapter's field policy staying as it is.
- **Nothing persisted** — proved by counting every row in every table of the
  app's store before and after the request; `persisted` is fixed `False` and
  *raises* if set true.

**Honest limitations:**

- **One file outside owned paths:** `test_api_endpoints.py` asserts the exact
  set of served OpenAPI paths, so adding endpoints necessarily breaks it. Two
  path strings were added and no assertion was weakened. Flagged rather than
  quietly absorbed.
- **`packages/sdk-typescript/src/generated/openapi.ts` is now stale** — outside
  owned paths and not covered by the contract-drift check. Follow-up.
- The 20k segment ceiling is a judgment, not a measured limit.
- **Residual echo, stated not hidden:** a *non-PII* quarantine reason quotes the
  offending value from a mapped operational column (e.g. `unknown outcome value
  'FOO'`). The PII check returns early, so no row with a detected identifier
  reaches that path; the residue is an operator putting personal data in the
  outcome column — their own submitted value, returned on the same connection
  and stored nowhere.

Status: **Demonstrated**; every fixture is synthetic.
