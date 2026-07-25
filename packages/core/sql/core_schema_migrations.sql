-- The Program D schema-version ledger (MX-D-MIGRATIONS-008).
-- Companion to packages/core/sql/core_v0_1.sql and packages/core/migrations.py.
--
-- WHY THIS TABLE EXISTS AT ALL.
-- ADR-0048 recorded the gap this closes in its own limitations: "Every CREATE is
-- IF NOT EXISTS, so a pre-tenant ADR-0041 database is not upgraded by reopening.
-- Acceptable ONLY because these tables have never held operator data -- and that
-- ceases to be true the moment they do." `IF NOT EXISTS` is not a migration
-- mechanism; it is the ABSENCE of one. It makes reopening an out-of-date
-- database succeed QUIETLY, with the code running against a shape it was not
-- written for. A database that cannot state which version it is at cannot be
-- migrated safely, because every decision a migration makes is a decision about
-- WHERE IT IS STARTING FROM. This table is that statement.
--
-- ONE ROW PER APPLIED VERSION, not one row holding "the" version. The current
-- version is MAX(version), but the individual rows are the audit trail: when the
-- database reached each version, and -- for version 2 -- WHOSE DATA the
-- pre-tenant rows were declared to be. An overwritten single-row "version = 2"
-- would answer the first question and destroy the second.
--
-- THIS TABLE IS DELIBERATELY *NOT* TENANT-SCOPED AND DELIBERATELY CARRIES NO RLS
-- POLICY (see the note at the foot of core_rls_postgres.sql). It is schema
-- metadata, not operator data. The reason is not stylistic and is worth stating
-- plainly, because doing the "consistent" thing here would be actively
-- dangerous: under a tenant policy, a session that has not set
-- `milexium.tenant_id` -- which is exactly the state a connection is in at the
-- instant it is opened, BEFORE any store has scoped it -- would read ZERO rows
-- from this table. Zero rows is indistinguishable from "never stamped", so the
-- migration runner would conclude the database is unversioned and try to
-- migrate an already-migrated database. Deny-all is the right default for
-- operator rows and the wrong default for the record that says what shape those
-- rows are in.
--
-- PORTABLE SUBSET ONLY (ADR-0002), as everywhere else: INTEGER and TEXT, a
-- CHECK instead of an ENUM, no SERIAL, no engine-specific default. This file
-- runs unmodified on SQLite and PostgreSQL 17, and is applied FIRST -- before
-- any version can be read, the place the version is recorded must exist.

CREATE TABLE IF NOT EXISTS core_schema_migrations (
    -- The schema version this row records the database reaching. PRIMARY KEY, so
    -- a version cannot be recorded twice: re-running a migration that has already
    -- been applied is refused by the DATABASE, not merely skipped by Python.
    version     INTEGER NOT NULL PRIMARY KEY CHECK (version >= 1),
    -- The migration's stable name, e.g. 'adr_0048_tenant_isolation'. Version
    -- numbers order; names identify. A stack trace quoting version 2 is far less
    -- useful than one quoting the change it refers to.
    name        TEXT NOT NULL,
    -- Fixed-width canonical ISO-8601 UTC (packages/core/feature_store.py
    -- `_iso_utc`), the same storage form as every other timestamp in the Program
    -- D schema, so lexicographic order is chronological order here too.
    applied_at  TEXT NOT NULL,
    -- HOW the database arrived at this version. The three cases are genuinely
    -- different and conflating them would lose the only evidence that
    -- distinguishes them:
    --   'created'  -- the database was created empty AT this version; no earlier
    --                 shape ever existed and no data was moved.
    --   'migrated' -- the database was at an EARLIER version and this migration
    --                 transformed it. Data may have been rewritten.
    --   'adopted'  -- the database already HAD this version's shape but carried
    --                 no ledger (it predates this table). Its shape was
    --                 recognised and stamped; nothing was changed.
    applied_by  TEXT NOT NULL CHECK (applied_by IN ('created', 'migrated', 'adopted')),
    -- Free text recording the decisions this migration had to make. For version 2
    -- this is where the pre-tenant rows' declared tenant is written down: the
    -- migration cannot know whose those rows are, so a caller must say, and what
    -- the caller said is recorded here permanently rather than inferred later
    -- from the data it produced.
    note        TEXT NOT NULL
);
