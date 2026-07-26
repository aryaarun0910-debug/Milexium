# ADR-0074: Making the lifecycle claim true — and naming what is still not

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-A-LIFECYCLE-IMMUTABILITY-012
- **Closes:** both P0 defects in `MILEXIUM_INTERNAL_AUDIT_2026-07-26.md`
- **Repairs:** ADR-0063, which overclaimed twice

## Context

An external audit found that the record we describe as answering *"what happened,
who decided, and when?"* enforced neither half of that claim: both clocks were
caller-supplied, and "append-only" was a coding convention a direct SQL `UPDATE`
walked straight through.

**This has been described in writing to an industry expert**, which is why it was
treated as the highest-priority work in the repo.

## Decision

### Transaction time

`record_transition` **no longer has a `recorded_at` parameter**, and no `**kwargs`
to smuggle one through — both asserted. The writer stamps it from a new
`transaction_clock.py`, which exists so `lifecycle.py`, `storage.py` and
`postgres_storage.py` stay *literally* clock-free and the AST assertion guarding
`decided_at` keeps its full strength.

**The load-bearing judgement: a DEFAULT alone would not have closed the finding.**
A column default only fires when the column is omitted, and the auditor's insert
*supplied* it. So PostgreSQL gets `clock_timestamp()` as DEFAULT **plus** a BEFORE
INSERT trigger refusing any value more than 60 s from the server clock (`MX002`);
SQLite gets the same bound via `julianday('now')`. A trigger that *overwrote* the
value was rejected too — it would force the writer to hash something it cannot
know until after the insert, putting `recorded_at` outside the chain.

**Late arrival is explicit.** `ingest_lag_seconds` is stored and re-derived on
read (disagreement raises). Past 300 s a row must name a `LateRecordingReason`
from a **closed five-member vocabulary** — deliberately not free text with a
length rule, which is precisely the vacuity the audit found in the rights
assertions. A *prompt* row may not declare one, or the field would mean nothing.

### Immutability, three layers

1. **Triggers** rejecting UPDATE/DELETE/TRUNCATE (`MX001`).
2. **Credential** — the table is owned by `milexium_ledger_owner`
   (NOLOGIN/NOSUPERUSER/NOBYPASSRLS), which is a member of the app roles and
   **never the reverse**, so the application cannot `SET ROLE` into it. The
   deployment credential holds exactly `{INSERT, SELECT}`.
3. **Hash chain** — `prev_hash`/`hash` per row using the same normative
   `compute_hash` ADR-0003 made canonical, so anything evading (1) and (2) is
   detectable on read. This also closes the audit's separate P1: the event ledger
   was chained while the lifecycle record was not, letting the ledger's
   credibility bleed onto it.

## Consequences

**Baseline first.** The auditor's three probes were re-run against *unmodified*
code as the application credential: backdated insert **accepted**, forged actor
**read back**, delete **removed the row**. After: backdate → `MX002`; forged
UPDATE → `42501` with the actor unchanged and the chain still verifying;
DELETE/TRUNCATE → `42501`. Also refused: erasing reason codes, backdating
`decided_at`, DROP/DISABLE TRIGGER, ALTER OWNER, CREATE OR REPLACE of the guard
function, NO FORCE / DISABLE RLS / DROP POLICY. Every probe asserts `rolsuper`,
`rolbypassrls` and ledger-owner membership false **inline** first.

**186 tests across the lifecycle suites, 75 in the immutability file alone**, both
PostgreSQL instances. Repository suite 2539 passed, 1 skipped.

**11 mutations, all RED — after two came back GREEN.** M1b's mutation was wrong
(it renamed a trigger rather than disabling it). **M12 was a real gap the packet
introduced**: stamping `recorded_at` as NOW moved the two timestamps into
different *dates*, so the collation trap a test guards was no longer reachable and
reverting fixed-width timestamps passed. Rebuilt so the pair shares a second by
construction.

**Six existing tests only passed under the weak guarantee** and were fixed with
the reasoning written into them — most tellingly, the one asserting `recorded_at`
had *no* database default now asserts it **has** one, and the round-trip test that
"proved" the store stores what it is given now asserts the stamp falls inside the
write window.

## What an attacker with the application credential can still do

**They cannot alter one field of one row. They can destroy the whole table.**

`DROP TABLE` succeeds, because PostgreSQL permits DROP to the **schema** owner as
well as the table owner, and the application credential owns the schema. There is
a test asserting this by name —
`test_the_credential_CAN_still_destroy_the_table_and_this_is_the_residual_risk` —
so nobody reads "immutable" as "indestructible". The fix (schema owned by a
migration role) is **Specified, not implemented.**

They can also **append a well-formed forged transition**: INSERT is granted by
design and there is no secret in the hash, so a forger with this source can
compute a valid one. Appending to a *terminal or discontinuous* chain is detected;
a plausible transition on an in-flight request is not. They can still lie about
`decided_at`, place `recorded_at` anywhere inside the 60 s window by controlling
the writer's clock, and insert rows illegal as history but legal as SQL — readable
by an analyst querying directly, refused through the store.

**On SQLite they can do all of it.** No roles exist, so that engine is never
evidence for the credential boundary.

Two probes behaved unexpectedly and are recorded rather than smoothed:
`GRANT UPDATE ... TO CURRENT_USER` **succeeds** with a warning and grants nothing
— so a naive `pytest.raises` there would read as "the credential can grant itself
UPDATE", which is false.
