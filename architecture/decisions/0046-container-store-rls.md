# ADR-0046: RLS on the containerized PostGIS store — and the superuser that would have faked it

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-C-CONTAINER-RLS-005
- **Closes:** the scope gap recorded in ADR-0037's consequences

## Context

ADR-0037 extended RLS to the observation tables but recorded an honest limit:
`rls_postgres.sql` is applied **only** by `PostgresCanonicalStore` against the
native PostgreSQL 17 on 5432. `PostgisObservationStore` targets the
containerized PostGIS on 5433 and applied the portable schema plus
`postgis_postgres.sql` — **not** the RLS file. Its reads were filtered by a
`tenant_id` in the SQL text, which is application code, not a boundary.

That store holds vehicle position and occupancy — the most sensitive operational
data in the schema.

## The finding: applying the policies would have been a false green

**The container credential is a superuser.** The `postgis` image bootstraps
`POSTGRES_USER` as the cluster superuser, so the `.env` credential holds both
`rolsuper` and `rolbypassrls` (verified directly against `pg_roles`:
`rolsuper: True, rolbypassrls: True`).

**Superuser bypass is checked before FORCE.** So simply running
`ENABLE`/`FORCE` + policies as that credential would have installed a boundary
that binds nobody — and every isolation test would have passed for the wrong
reason. This is precisely the false green `rls_postgres.sql`'s header warns
about for table owners, one privilege level up, and it would have been
invisible: the policies exist, the tests are green, the data is not protected.

## Decision

**Provision an unprivileged role and act as it.** Construction creates
`milexium_rls` (`NOSUPERUSER`, `NOBYPASSRLS`, `NOLOGIN` — never a login
identity, so it needs no password), creates the disposable schema
`AUTHORIZATION` that role, and `SET ROLE`s to it per operation. **Owner**, not
merely grantee, so FORCE remains load-bearing rather than a privilege error
masking an absent policy.

**Apply `rls_postgres.sql` itself, not a copy.** The container store cannot drift
from the native store's policies. This is also why the RLS DDL did *not* go into
`postgis_postgres.sql` despite that being an owned path — duplicating policy text
is exactly the drift this avoids.

The store sets the `milexium.tenant_id` GUC per operation, as
`PostgresCanonicalStore` does, so the policies have an acting tenant to evaluate.

## Consequences

- **21 new tests (42 with the neighbouring suites), 0 skipped** — they **ran**
  against the live PostgreSQL 16.4 + PostGIS 3.4 on 5433.
- **The `ST_DWithin` spatial path is confirmed tenant-scoped.** Two tenants each
  have a vehicle at the *same* corridor point; running the store's real
  geography predicate **with the `tenant_id` filter deleted**, acting as A
  returns only A's vehicle, acting as B only B's, unscoped returns neither, and
  lifting FORCE returns both. Geometry is not a way around the policy — which
  matters most, because that path is the reason this store exists.
- **The tests are proven non-vacuous by mutation.** Monkeypatching the role
  switch to a no-op — i.e. applying the policies as the superuser, the exact
  false green above — **fails 16 of the 21 tests**, including all three spatial
  ones. The 5 survivors are `pg_class`/ownership preconditions and a store-method
  test that legitimately don't depend on it.
- Coverage includes a positive control on every denial, the RESET-GUC case
  asserted **as an empty string** (not NULL — see ADR-0043's empty-string trap),
  and a separate never-set-GUC connection covering the NULL case.
- `test_stop_time_observation_store.py` passes unchanged; nothing had to be
  weakened, because the store sets the GUC itself.

**Honest limitations:**

- **The container credential is still a superuser.** Re-provisioning it means
  editing `docker-compose.yml`/`.env`, outside this packet. Anything else
  connecting with that credential still bypasses RLS. **What is proven is that
  this store is bound — not that the container cannot be bypassed.**
- `milexium_rls` is **cluster-wide**, so unlike the `mx_<uuid>` schema it
  survives teardown. Inert (`NOLOGIN`, owns nothing after the drop), but it is a
  side effect outside the disposable namespace.
- The GUC is the identity, as everywhere in this file: a session that sets it
  *is* that tenant. This is a database-layer boundary against a missing filter or
  a compromised code path, not authentication.

Also corrected here: a stale comment block above the `model_versions` policy
still described platform rows as visible to an unset session, contradicting the
ADR-0043 tightening directly below it. Fixed rather than left to mislead.
