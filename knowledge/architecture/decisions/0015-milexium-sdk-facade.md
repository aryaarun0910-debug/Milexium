# ADR-0015: MilexiumClient SDK facade (Program M v0.1)

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

The repositioning — a transport decision runtime *other software integrates* —
is meaningless without an integration surface. Blueprint 08's "unavoidable"
signal is "a developer can adopt in ten minutes" and "external installation and
retained use." Until now every capability lived in a separate internal package
(`app/canonical`, `connect`, `verify`, `evidence`, `core`) with no single
ergonomic entry point. Program M was the largest gap on the strategic path.

## Decision

Ship `app/sdk/` — a small v0.1 **facade** (`MilexiumClient`) that composes
the existing packages behind one stable public surface. It is pure composition;
it adds ergonomics, not domain logic. Public API:

- `MilexiumClient.in_memory(tenant_name)` — in-memory `SqliteCanonicalStore` +
  one fresh tenant, zero external infra (the ten-minute path).
- `client.ingest(adapter, rows) -> IngestSummary` — runs any `SourceAdapter`
  via `parse_batch`; summary carries records, quarantined rows, and semantic
  loss with `accepted`/`quarantined` counts.
- `client.record_decision(...)` (fixes `actor_type="system"`) /
  `client.record_override(...)` (fixes `actor_type="human"`, requires
  `actor_id`) — ergonomic `append_event` wrappers encoding the repo's
  recommendation=system / override=human convention so callers can't get it
  wrong.
- `client.evidence_for(aggregate_id, outcome=None) -> EvidencePacket` — history
  + raw rows → `build_evidence_packet` in one call.
- `client.verify(aggregate_id)` — independent hash-chain check (empty =
  verified); the fuller chain+schema result stays on
  `evidence_for(...).integrity_verified`, two intentionally distinct surfaces.
- `.store` / `.tenant_id` — documented escape hatch and identity.

Design decisions:

1. **Decoupled from concrete adapters**: the SDK core imports only
   `parse_batch` from `app.connect.adapter` (the generic contract), never
   a concrete adapter. `ingest` accepts anything structurally satisfying
   `SourceAdapter`. A new adapter needs zero SDK change. Concrete adapters
   appear only in the example and tests.
2. **`IngestSummary` is a frozen dataclass, not Pydantic** — it aggregates
   already-validated, heterogeneous canonical records and does no validation
   of its own; re-wrapping in Pydantic would add re-coercion risk without
   modeling new data.
3. **Runnable quickstart** (`app/sdk/example.py`, run as
   `py -3 -m app.sdk.example`) exercising the full loop end-to-end, with a
   test that executes it.

## Consequences

- Exists (Demonstrated on fictional reference-agency data): the `MilexiumClient`
  v0.1 facade + executable quickstart.
- Still Specified (deliberately out of scope, per blueprint 08): HTTP/OpenAPI
  server, CLI, plugin certification, auth, multi-tenant API gateway, and the
  TypeScript/Rust SDKs. This slice is the local Python surface — the "ten
  minute" on-ramp — not the hosted API.
- `app.sdk` is the documented public entry point (`from app.sdk
  import MilexiumClient`); the internal packages remain internal.
- There is no installed console entry point yet, so the example runs as a
  module, not a bare script — noted in its docstring. A packaged console
  script is future Program M work.
