# ADR-0006: Dedicated non-superuser Postgres role/database for application connections

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

ADR-0004 installed PostgreSQL 17 using the EDB installer's default
superuser (`postgres`) account. `blueprint/10-security-privacy-and-ai-
governance.md` requires "default-deny roles and least privilege" and
"separate service identities for import, model, solver, export, and
support" -- the application code that Program C is about to write
(`themis/canonical/postgres_storage.py`, Packet MX-C-POSTGRES-STORE-001)
should not connect as the database superuser even in local dev.

## Decision

- Created a dedicated role `milexium_dev` (`LOGIN`, password-authenticated,
  no superuser/createdb/createrole privileges) and a database `milexium_dev`
  owned by that role.
- The role's password is generated locally and stored at
  `%USERPROFILE%\.milexium_pg_app_password.txt` -- outside the repository,
  never committed, read by application code at connection time only.
- Connectivity confirmed via `psycopg` (installed as the `postgres` extra
  already declared in `pyproject.toml`, ADR-0002): `psycopg.connect(host=
  "localhost", dbname="milexium_dev", user="milexium_dev", password=...)`
  succeeds and returns `PostgreSQL 17.10`.
- Note for future sessions on this machine: the first attempt to write this
  password file with PowerShell's `Out-File -Encoding utf8` silently
  prepended a UTF-8 BOM, which broke password comparison when read back by
  Python's default `open(...).read()`. Both password files were rewritten
  with `[System.IO.File]::WriteAllText(..., [System.Text.UTF8Encoding]::new($false))`
  to avoid the BOM. Anything that writes a credential file with PowerShell
  on this machine should do the same.

## Consequences

- `themis/canonical/postgres_storage.py` connects as `milexium_dev`, never
  as `postgres`. Schema migrations that require elevated privileges (e.g.
  installing the PostGIS extension, once that happens) are a separate,
  explicitly superuser-run step, not something application code does at
  runtime.
- Row-level security (RLS) is not yet configured on `milexium_dev` -- the
  expansion plan notes "database owners can bypass typical RLS behavior;
  deployment roles and migration processes must account for this," so RLS
  setup happens once Program C actually needs tenant-scoped Postgres access
  control, not before.
- This ADR does not cover backup, replication, or production credential
  rotation -- those remain "Specified" per `IMPLEMENTATION_STATUS.md`.
