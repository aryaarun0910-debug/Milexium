# ADR-0003: Append-only, hash-chained event log for decision evidence

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

Both `forge/knowledge/docs/MASTER_ROADMAP.md` (the `decision_events` table: "Every decision
event has `event_id`, `tenant_id`, `aggregate_id`, `sequence`, UTC timestamp,
actor type/id, event type, canonical JSON payload, previous hash, and current
SHA-256 hash. The database rejects sequence gaps and duplicate idempotency
keys.") and the expansion plan's Program A/I (`blueprint/04-...md`,
`blueprint/07-explain-replay-and-evidence.md`) require the same underlying
mechanism: an immutable, tamper-evident, per-tenant, per-aggregate event
history that supports bitemporal correction (a correction is a new event,
never a mutation of a prior one) and exact replay.

The expansion plan is explicit that a hash chain is "tamper-evident, not
immutable and not a compliance certificate" (`blueprint/01-...md`) — this
must be stated exactly that way anywhere the mechanism is described publicly.

## Decision

Implement one canonical event-log mechanism in `themis/canonical`, used by
both the YC-demo `decision_events` table and the expansion's Evidence IR
foundation, rather than two parallel implementations:

- Every event carries `event_id` (UUIDv7), `tenant_id`, `aggregate_id`,
  `aggregate_type`, `sequence` (monotonic per aggregate), `occurred_at` (UTC),
  `actor_type`/`actor_id`, `event_type`, a canonical (sorted-key, no
  floating-point ambiguity) JSON payload, `prev_hash`, and `hash` =
  `SHA-256(prev_hash || canonical_json(payload) || sequence || aggregate_id)`.
- The append operation is the only way to write; it rejects a duplicate
  `(aggregate_id, sequence)`, a sequence gap, and a `prev_hash` that does not
  match the last accepted event for that aggregate.
- A **separate, independent verifier module** (not the appender) walks the
  chain and recomputes hashes to detect tampering or gaps — per the
  expansion's non-negotiable that "candidate generators and independent
  verifiers must remain separate," the same component that writes events must
  not be the sole checker of their integrity.
- Corrections to a `ServiceRequest` (or any bitemporal entity) are new events
  referencing the corrected aggregate's prior version; the original decision
  horizon (what was known/predicted at the time) is preserved, never
  overwritten, per the expansion's bitemporal-replay invariant.

## Consequences

- One implementation serves the roadmap's `decision_events` table and the
  expansion's Evidence IR event history — no duplicated logic to keep in
  sync.
- Every public or investor-facing description of this mechanism must say
  "tamper-evident," never "immutable" or "a compliance certificate," per
  `blueprint/01-north-star-and-boundaries.md`.
- This ADR covers the mechanism only; it does not cover storage engine
  choice (SQLite now, Postgres later — ADR-0004), retention/deletion policy,
  or signed periodic checkpoints (`blueprint/10-...md`), which remain
  "Specified" until built.
