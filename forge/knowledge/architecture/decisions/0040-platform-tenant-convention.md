# ADR-0040: A reserved platform tenant for models that belong to no customer

- **Status:** Accepted (decision made; implementation scoped as a follow-up packet)
- **Date:** 2026-07-24

## Context

`ModelVersion.tenant_id` has had no honest answer since ADR-0010 for
**platform-trained models** — the five real models in this repository are trained
on *public* data (NYC TLC, Chicago TNP, MTA, NTD) and belong to no customer. The
registry fixtures use a placeholder tenant id with no meaning, and
`IMPLEMENTATION_STATUS.md` has carried this as an open decision between two
options: a reserved "platform" tenant convention, or making `tenant_id` optional
specifically for this entity.

It stopped being cosmetic when RLS landed. `rls_postgres.sql` already guards
`model_versions` with `tenant_id = current_setting('milexium.tenant_id', true)`,
and its own header flags that the policy is only correct "once a 'platform
tenant' convention is chosen." Right now no store method reads or writes that
table, so nothing is broken — but the moment one does, an unresolved convention
becomes either a broken lookup or a silent cross-tenant read.

## Decision

**Adopt a reserved platform tenant. Reject the optional-`tenant_id` option.**

A single well-known `TenantId` constant identifies models owned by the platform
rather than by a customer.

**Why not optional `tenant_id`:** a nullable tenant column is corrosive to the
whole isolation story. `tenant_id = current_setting(...)` is never true for
`NULL`, so nullable rows are invisible under the existing policy and every
consumer would need a special case — and the first consumer that forgets the
special case gets a silently wrong answer rather than an error. It also breaks
the invariant that makes the schema auditable at a glance: *every operational
record carries a tenant.* One nullable column costs more than the convention it
saves.

**The consequence that must not be missed:** platform models have to be
**readable by every tenant and writable by none of them**. A strict
`tenant_id = GUC` policy would make the platform's own models invisible to the
customers who need to run them. So the `model_versions` policy becomes:

```sql
USING      (tenant_id = current_setting('milexium.tenant_id', true)
            OR tenant_id = '<PLATFORM_TENANT_ID>')
WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true))
```

Asymmetric on purpose: the `USING` clause lets any tenant *read* platform
models; the `WITH CHECK` clause omits the platform id, so **no tenant session can
write a row stamped as platform-owned**. A customer can use a platform model and
cannot forge one.

## Consequences

- `tenant_id` stays `NOT NULL` everywhere; the "every record carries a tenant"
  invariant survives, and the schema stays portable (this is a convention plus a
  policy clause, not a schema change).
- Model resolution works for both platform-trained and customer-trained models
  without a special case at every call site.
- The reserved id must be a real row in `tenants` to satisfy the foreign key, and
  seeding it becomes part of store setup.

**Not implemented by this ADR.** The decision is the deliverable here; the change
touches `themis/canonical` (the constant + seeding), `rls_postgres.sql` (the
asymmetric policy), and `themis/core/model_registry.py` (resolution), and it is
security-relevant, so it lands as its own reviewed packet with an adversarial
test proving a tenant session **cannot** write a platform-stamped row. Landing
half of it — the constant without the policy, or the policy without the test —
would be worse than the current honest placeholder, because it would look
finished.

**Related open item:** ADR-0038 surfaced that `vehicle_ref`/`run_ref` has no
canonical home. That is a different Program A gap and is tracked separately.
