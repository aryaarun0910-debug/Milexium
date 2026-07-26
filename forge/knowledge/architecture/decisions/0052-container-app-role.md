# ADR-0052: An unprivileged application role — binding RLS at the connection, not by convention

- **Status:** Accepted
- **Date:** 2026-07-25
- **Closes:** the open item recorded in ADR-0046's limitations

## Context

ADR-0046 found that the containerized PostGIS credential is a **cluster
superuser** — the `postgis` image bootstraps `POSTGRES_USER` that way, and it
holds both `rolsuper` and `rolbypassrls`. Superuser bypass is evaluated **before**
`FORCE ROW LEVEL SECURITY`, so any connection using that credential ignores every
tenant policy in the database: policies present, tests green, data unprotected.

ADR-0046 bound the *store* by provisioning a `NOLOGIN` role and having the store
`SET ROLE` to it. That worked, but left the honest limitation it recorded:
**the credential itself was still all-powerful.** Anything else connecting with
it — a script, a migration, a future service, a developer with `psql` — bypassed
RLS entirely. The boundary depended on the application remembering to demote
itself.

## Decision

Provision `milexium_app`: a **LOGIN** role that is explicitly `NOSUPERUSER`,
`NOBYPASSRLS`, `NOCREATEDB`, `NOCREATEROLE`, and have the stores connect as it.
RLS now binds **at the connection level** rather than by convention.

- `talos/infra/compose/initdb/01-app-role.sh` provisions it. `docker-entrypoint-initdb.d`
  runs **only on first initialisation of an empty data directory**, so an existing
  volume will not pick it up — the same statements were applied by hand to the
  already-running container when this landed, and the script is what makes a
  **fresh** container reproduce that state without anyone remembering to.
  It is idempotent and *re-asserts* the security attributes on an existing role,
  so a role hand-created in an earlier setup cannot silently retain superuser.
- Privileges are the minimum that keeps the store working: `CREATE` on the
  database (it creates a disposable `mx_<uuid>` schema per run, ADR-0008) and
  `USAGE` on `public` (PostGIS types and `ST_*` live there). PostGIS is already
  installed by the image, so `CREATE EXTENSION IF NOT EXISTS postgis` is a
  privilege-free no-op. **If that ever stops being true, the extension must be
  created by the superuser at init — not by granting this role superuser to work
  around it.**
- `_application_credential()` prefers the app role and falls back to the
  bootstrap superuser only when the new keys are absent, so a checkout whose
  `.env` predates this ADR keeps working rather than failing mysteriously.

**The fallback is not a security position, and a test makes that true rather
than asserted:** `test_the_connecting_credential_is_not_a_superuser` fails loudly
if a run silently fell back to the superuser — which is exactly the
passing-for-the-wrong-reason failure ADR-0046 was written about.

## Consequences

- **24 tests pass** against the live container. The store now connects as
  `milexium_app` (`rolsuper=False`, `rolbypassrls=False`), and
  `_acting_role` is `None` — the `SET ROLE` demotion is no longer *needed*,
  because the credential is already bound. The mechanism ADR-0046 built remains
  as defence in depth for any credential that still needs it.
- **A test was found to be out-privileging the thing it tested.** The
  never-set-GUC case opened its *own* connection hardcoded to `POSTGRES_USER`
  and demoted it only when the store had an acting role. Once the store's
  credential became unprivileged there was nothing to demote, so that connection
  ran as a raw superuser and read a row — surfacing as a boundary failure that
  was really the test's own privilege. It now uses the same application
  credential the store uses. Worth recording: the change did not break the
  boundary, it broke a test that had been quietly relying on a superuser being
  demoted for it.
- `.env.example` documents both credentials and which is for what;
  `docker-compose.yml` passes the app credential and mounts the init directory
  read-only.

**Honest limitations:**

- **The superuser still exists**, as it must — it is the bootstrap identity and
  the only role that can administer the cluster. What changed is that the
  *application* no longer uses it. A developer who connects with
  `POSTGRES_PASSWORD` still bypasses RLS, by design.
- The password is generated locally into the gitignored `talos/infra/compose/.env`.
  There is no secrets manager; blueprint/10's centralized secret handling remains
  Specified.
- `milexium_rls` (ADR-0046) is now redundant for this store but is left in place:
  removing it would change behaviour for any credential that is still privileged,
  and it costs nothing.
- This is a **dev** stack. A production deployment needs per-tenant credentials,
  TLS, and rotation — none of which exist.
