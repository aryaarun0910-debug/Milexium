-- SQLite-only immutability + transaction-time triggers for the lifecycle record.
-- MX-A-LIFECYCLE-IMMUTABILITY-012.
--
-- WHY THIS IS A SEPARATE FILE, exactly as sql/rls_postgres.sql is. schema_v0_1.sql
-- is the PORTABLE DDL (ADR-0002): it must execute unmodified on both engines, so
-- it may contain no engine-specific construct. SQLite's `CREATE TRIGGER ... BEGIN
-- SELECT RAISE(ABORT, ...); END` is not valid PostgreSQL and PostgreSQL's plpgsql
-- trigger functions are not valid SQLite, so each engine's version of the same
-- guarantee lives beside its own dialect. `SqliteCanonicalStore` applies this file
-- immediately after the portable schema; the PostgreSQL half is
-- platform/infra/compose/initdb/02-lifecycle-ledger-bootstrap.sql (privileged, once per
-- cluster) with
-- sql/lifecycle_immutability_postgres.sql as the unprivileged fallback.
--
-- WHAT THIS ENGINE CAN AND CANNOT ENFORCE, stated plainly because the honest
-- answer is uncomfortable. SQLite has NO ROLES AND NO PRIVILEGES. Whatever process
-- can open the database file can `DROP TRIGGER` and then do as it likes, and there
-- is no owner-separation to hide behind. So on this engine the triggers below are a
-- guard against the application and its bugs -- a stray UPDATE, a cleanup script, a
-- migration, an ORM's "upsert" -- and NOT a boundary against an attacker who
-- already holds the file. The boundary claim in ADR/packet terms belongs to the
-- PostgreSQL deployment path only; SQLite is the dev/demo engine (ADR-0004) and
-- must not be cited as evidence of the credential boundary.
--
-- The hash chain is what still bites here: a row edited after the triggers were
-- dropped no longer matches its own hash, and `lifecycle_verify.py` says so.
-- Evidence, not prevention.

-- Refuse every UPDATE. BEFORE, so nothing is written even transiently. The message
-- names the remedy, because the person who trips this is usually trying to fix a
-- wrong record and needs to be told the fix is another transition, not an edit.
CREATE TRIGGER request_state_transitions_reject_update
BEFORE UPDATE ON request_state_transitions
BEGIN
    -- One string literal on one line: SQLite has no adjacent-literal
    -- concatenation (that is a C/Python convention), and splitting this message
    -- across quoted fragments is a syntax error rather than a long line.
    SELECT RAISE(ABORT, 'request_state_transitions is append-only: UPDATE is refused. A correction is a further transition, never an edit to a recorded one.');
END;

-- Refuse every DELETE.
--
-- NOTE ON SQLite's TRUNCATE OPTIMIZATION, which is the trap here: `DELETE FROM t`
-- with no WHERE clause normally bypasses the per-row machinery entirely and drops
-- the table's pages -- which would bypass a row trigger too. SQLite disables that
-- optimization for any table carrying a DELETE trigger, so the existence of THIS
-- trigger is what makes the unqualified case fire. The conformance suite issues
-- the unqualified form explicitly rather than assuming the qualified case covers
-- it.
CREATE TRIGGER request_state_transitions_reject_delete
BEFORE DELETE ON request_state_transitions
BEGIN
    SELECT RAISE(ABORT, 'request_state_transitions is append-only: DELETE is refused. History is not corrected by removing rows from it.');
END;

-- TRANSACTION TIME IS BOUNDED BY THE DATABASE, not merely by the writer.
--
-- This is the trigger that closes the audit finding on this engine. `recorded_at`
-- is stamped by app/canonical/transaction_clock.py, but a raw INSERT that
-- never goes through the writer could state anything -- which is exactly what the
-- audit did, inserting a 2020-01-01 decision "recorded" one second later. Any row
-- whose recorded_at is more than 60 seconds from the DATABASE's own clock is
-- refused, so a stored transaction time is within a minute of the truth or the row
-- does not exist. 60s is RECORDED_AT_TOLERANCE_SECONDS in lifecycle.py and a
-- conformance test pins the two literals together.
--
-- Both directions: backwards is the forgery, forwards is a row claiming to have
-- been written at a time nobody can check yet. julianday() parses the fixed-width
-- ISO-8601 form including its +00:00 offset, and julianday('now') is UTC, so the
-- difference is in days -- hence the * 86400.
CREATE TRIGGER request_state_transitions_bound_recorded_at
BEFORE INSERT ON request_state_transitions
WHEN abs(julianday(NEW.recorded_at) - julianday('now')) * 86400.0 > 60.0
BEGIN
    SELECT RAISE(ABORT, 'recorded_at is not this database''s transaction time: it differs from the server clock by more than 60 seconds. recorded_at is stamped by the writer and bounded here; it is not a value a caller may assert.');
END;
