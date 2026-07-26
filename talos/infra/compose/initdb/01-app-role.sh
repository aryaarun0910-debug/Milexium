#!/bin/bash
# Provision the UNPRIVILEGED application role for the containerized PostGIS.
# See forge/knowledge/architecture/decisions/0052-container-app-role.md (and 0046, which found
# the problem this file exists to fix).
#
# WHY THIS FILE EXISTS
# The postgres/postgis image bootstraps POSTGRES_USER as the CLUSTER SUPERUSER.
# ADR-0046 verified it directly: that role holds both `rolsuper` and
# `rolbypassrls`. Superuser bypass is checked BEFORE `FORCE ROW LEVEL SECURITY`,
# so any connection using that credential ignores every tenant policy in the
# database -- policies present, tests green, data unprotected. ADR-0046 bound the
# *store* by having it SET ROLE to an unprivileged role, but the credential
# itself stayed all-powerful: anything else connecting with it still bypassed.
#
# `milexium_app` is a LOGIN role that is explicitly NOSUPERUSER and NOBYPASSRLS,
# so RLS binds it at the CONNECTION level rather than depending on the
# application remembering to demote itself.
#
# WHEN THIS RUNS
# /docker-entrypoint-initdb.d/* runs ONLY on first initialisation of an EMPTY
# data directory. An existing volume will NOT pick it up -- the same statements
# were applied by hand to the already-running container when this landed
# (recorded in ADR-0052). This file is what makes a FRESH container reproduce
# that state without anyone having to remember.
#
# PRIVILEGES, AND WHY EACH IS NEEDED
#   LOGIN                  -- a connection identity, unlike the NOLOGIN
#                             `milexium_rls` role ADR-0046 introduced.
#   NOSUPERUSER            -- the whole point.
#   NOBYPASSRLS            -- stated explicitly rather than left to the default,
#                             because it is the property under test.
#   CREATE on the database -- PostgisObservationStore creates a disposable
#                             mx_<uuid> schema per run (ADR-0008 isolation).
#   USAGE on public        -- PostGIS types and ST_* functions live there.
# Deliberately NOT granted CREATEDB or CREATEROLE.
#
# PostGIS is already installed by the image into `public`, so the
# `CREATE EXTENSION IF NOT EXISTS postgis` in sql/postgis_postgres.sql is a
# privilege-free no-op for this role. If that ever stops being true, the
# extension must be created by the superuser at init -- NOT by granting this
# role superuser to work around it.
set -euo pipefail

APP_USER="${MILEXIUM_APP_USER:-milexium_app}"
if [ -z "${MILEXIUM_APP_PASSWORD:-}" ]; then
  echo "01-app-role: MILEXIUM_APP_PASSWORD is not set -- refusing to create a" >&2
  echo "             passwordless application role. Set it in talos/infra/compose/.env." >&2
  exit 1
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${APP_USER}') THEN
        CREATE ROLE "${APP_USER}" LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
            PASSWORD '${MILEXIUM_APP_PASSWORD}';
    ELSE
        -- Idempotent, and re-asserts the security-relevant attributes so a role
        -- created by hand in an earlier setup cannot silently retain superuser.
        ALTER ROLE "${APP_USER}" LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
            PASSWORD '${MILEXIUM_APP_PASSWORD}';
    END IF;
END
\$\$;

GRANT CREATE ON DATABASE "${POSTGRES_DB}" TO "${APP_USER}";
GRANT USAGE ON SCHEMA public TO "${APP_USER}";
EOSQL

echo "01-app-role: provisioned unprivileged application role '${APP_USER}'"
