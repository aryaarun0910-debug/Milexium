# ADR-0029: TypeScript SDK generated from the OpenAPI contract

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

"Other software integrates Milexium" (ADR-0026) requires a language-neutral HTTP
surface *and* a TypeScript client, since JS/web shops won't call a Python SDK.
The rule (from the polyglot brief): TypeScript must **not** hand-duplicate
canonical domain semantics — generate from the contract.

## Decision

`argus/sdk-typescript/` (`@milexium/sdk`) — a strict-mode TS client whose
types are **generated** from `talos/contracts/openapi/milexium-api-v0.1.json` via
`openapi-typescript` (`npm run generate` → `src/generated/openapi.ts`,
committed; regeneration is byte-stable). `src/types.ts` only *aliases*
`components["schemas"][...]`; the sole derivation is `Pick`/`Partial` to relax
server-defaulted request fields to the contract's actual `required` set — no
field shapes are hand-redeclared. A `MilexiumClient` wraps `fetch` with one
method per endpoint (`health`, `version`, `recordDecision`, `recordOverride`,
`evidence`, `evidencePack`, `verify`); non-2xx throws `MilexiumApiError`.

Toolchain decisions (environment/ecosystem constraints, recorded because future
packets will hit them again):

- **npm, not pnpm**: `corepack enable pnpm` fails with EPERM (needs admin to
  write the shim into `Program Files\nodejs`). npm 11 with native workspaces is
  used instead — root `package.json` `workspaces: ["app/*"]` +
  `package-lock.json`. (npm ignores the Python `app/*` dirs — no
  `package.json` there.) The CI TypeScript job uses npm accordingly.
- **TypeScript pinned to 5.9, not 7.0**: `openapi-typescript@7` peer-requires
  `typescript@^5`; the new native TS 7 compiler isn't adopted by the ecosystem
  yet and breaks install.
- **Test runner = `node:test` + Node 24 native TS type-stripping** (zero runtime
  test deps); 13 tests against a mocked `fetch`, no server required.

## Consequences

- A web/JS developer can integrate Milexium against a typed client whose types
  provably match the API contract; regenerating from a new contract version
  surfaces breaking changes at compile time.
- Known dev-only issue: 2 high-severity `npm audit` warnings for `js-yaml`
  (quadratic-CPU DoS on untrusted YAML), transitive under the `openapi-typescript`
  codegen tool — never shipped in the SDK, and the input is a trusted committed
  JSON contract. Left as-is rather than `npm audit fix --force` (which would
  break the codegen pin); revisit when the upstream tool updates.
- Auth, retries, pagination, streaming, and a published npm release are
  Specified follow-ups; this is the typed-client v0.1.
- Node build output (`dist/`, `node_modules/`) is gitignored; the generated
  `src/generated/openapi.ts` is committed as part of the contract-bound source.
