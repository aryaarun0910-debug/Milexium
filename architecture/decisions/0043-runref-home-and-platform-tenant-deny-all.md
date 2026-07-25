# ADR-0043: A canonical home for the run reference, and tightening ADR-0040 to preserve deny-all

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-A-RUNREF-PLATFORM-TENANT-004
- **Amends:** ADR-0040 (the `model_versions` USING clause)

## Context

Two Program A gaps, landed together because they share files.

**1. The run reference had no canonical home.** ADR-0038 surfaced that
`vehicle_ref`/`run_ref` lived only on the Connect-layer record and was a
`dropped` semantic loss on every row. Deadhead is measurable *only* by chaining
one vehicle's consecutive trips (ADR-0039), so the single field the entire
teardown depends on could not survive a write to MilexiumDB.

**2. ADR-0040's platform-tenant convention was decided but not implemented.**

## Decision

### Run reference → `outcomes`

Two additive nullable `TEXT` columns on the existing `outcomes` table, not a new
aggregate. Which vehicle performed a trip is a fact about **what happened**, and
it belongs beside `deadhead_minutes` — the field chaining it produces.
Deliberately **not** duplicated onto `ServiceRequest`: one fact, one home.
`record_outcome()`/`outcomes()` are mirrored on both stores (neither had an
outcomes method before, so the round-trip required one).

`schema_v0_1.sql` stays portable — verified by executing the file's own bytes
against a bare `sqlite3.connect(":memory:")` with no store class involved,
plus a parametrised scan for Postgres-only constructs over the comment-stripped
DDL.

### `PLATFORM_TENANT_ID`

`00000000-0000-7000-8000-000000000000` — a real UUIDv7, so it needs no
validation exemption, with an all-zero timestamp prefix so `new_id(TenantId)`
can never collide with it. Seeded idempotently into `tenants` by both stores.
`ModelRegistry._is_visible_to` is the single predicate all resolution routes
through, rather than a special case repeated at each call site.

### The amendment: deny-all is restored

ADR-0040 specified `USING (tenant_id = GUC OR tenant_id = PLATFORM)`. Implemented
literally, that second branch is true **whatever the GUC says**, so an unset
session could read platform rows — contradicting the deny-all default
`rls_postgres.sql` advertises in its own header.

The implementing packet did the right thing: it built ADR-0040 as written,
refused to redesign it unilaterally, and pinned the exposure in a test whose
docstring said tightening it "belongs in a new ADR, and this test is what will
fail and force the conversation." This is that ADR.

**Decision: require the session to be scoped for the platform-read branch.**

```sql
USING (tenant_id = current_setting('milexium.tenant_id', true)
       OR (tenant_id = '<PLATFORM>'
           AND coalesce(current_setting('milexium.tenant_id', true), '') <> ''))
```

It costs nothing — any acting tenant still reads platform models — and restores
the invariant that an unset GUC returns zero rows from this table, as from every
other. The exposure leaked no customer data, but "the rows we judged harmless"
is a judgement that would have to keep holding for every column and join added
later, and an unset GUC almost always means a connection nobody scoped.

**The empty-string trap, recorded because it cost a failed attempt.** The first
fix used `IS NOT NULL` and did **not** work. `current_setting(name, true)`
returns NULL only when the GUC was *never* set in the session; after `RESET`
(or `SET x = ''`) it returns the **empty string**, which `IS NOT NULL` accepts.
The other policies in this file survive that only *incidentally*, because
`tenant_id = ''` is false for any real UUID — this branch has no such accident
protecting it, so it tests for non-empty explicitly. The test caught this; the
prose would not have.

## Consequences

- **59 tests, 0 skipped.** 23 of them ran against native PostgreSQL 17,
  including every adversarial case: forged-platform write rejected, platform
  read allowed for an acting tenant, deny-all for an unset session (now
  including platform rows), FORCE-lift boundary collapse, and
  `pg_class.relforcerowsecurity` asserted directly.
- The teardown's key field can now be persisted and read back — the handoff
  adapter → `Outcome.vehicle_ref` → store → read-back is proven by test.
- `tenant_id` remains `NOT NULL` everywhere.

**Honest limitations:**

- **The GUC is the identity.** A session that sets `milexium.tenant_id` to the
  platform id *is* acting as the platform and may write platform rows — that is
  how the platform seeds its own models. What is proven impossible is a session
  acting as a **customer** forging one.
- `ModelRegistry.get(model_version_id)` remains un-scoped (pre-existing); only
  `champion`/`list_for_task` gained tenant awareness, via an optional kwarg, so
  existing call sites are unchanged.
- The Connect adapter still emits its `dropped` semantic-loss record for the run
  reference; `packages/connect` was outside this packet's owned paths. Wiring
  the adapter through to the new column is a small follow-up.
