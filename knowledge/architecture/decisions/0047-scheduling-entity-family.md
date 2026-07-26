# ADR-0047: The canonical scheduling family — Block, RunPiece, DeadheadSegment

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-A-SCHEDULING-FAMILY-006

## Context

ADR-0031 found that TODS and NeTEx remained Specified **not** because the adapter
work was hard, but because the canonical model had no home for what they
describe: runs, blocks, pieces-of-work and deadhead segments. ADR-0035 landed the
*telemetry* family (`VehicleObservation`/`StopTimeObservation`). The *scheduling*
family was still missing, and it is what stands between Program B and two major
open standards.

## Decision

Three request-independent entities, following ADR-0035's shape.

**`Block`** — one vehicle's continuous work between pull-out and pull-in. The
vehicle's unit of work, and the parent the other two hang off.

**`RunPiece`** — one continuous piece of an operator's run. **One row per
(run, piece), not per run.** TODS gives a run no attribute of its own — the run
*is* the grouping key its pieces share — so a separate `runs` table would be an
aggregate holding nothing but an id, and a second place for the same fact to
disagree. The run's identity lives on every piece as `run_ref`; a piece whose
export named no run is unattributable and says so.

**`DeadheadSegment`** — non-revenue movement, shaped for its waiting consumer.
`started_at`/`ended_at`/`run_ref` are deliberately
`app.replay.teardown.VehicleSegment`'s own field names, so a stored segment
maps onto a teardown **field-for-field with no translation**, and `run_ref=None`
preserves the teardown's absence semantics exactly.

**Design calls worth recording:**

- **Request-independence is structural, not documentary.** `extra="forbid"` means
  a `request_id` cannot be attached, and no field named `request*` exists.
- **Three typed ids, not one shared `SchedulingId`** — a deliberate divergence
  from `ObservationId`. This family *references itself* (`block_id`), so one
  opaque type would let a deadhead id sit where a block id belongs.
- **`deadhead_type` is a closed `Literal`, not a source string** (unlike
  `current_status` in ADR-0035) because it is the field a consumer *branches* on.
  `other` is an honest landing place rather than a guess at `interline`.
- **Reversed time ordering is rejected at construction** — a negative duration
  would *subtract* from a teardown's headline total.
- `operator_ref` is a person reference and follows `rider_ref`'s
  tokenised-never-a-name rule.

**Cross-tenant guard.** A foreign key to `blocks` does **not** keep the reference
inside the tenant: PostgreSQL evaluates referential integrity with RLS bypassed,
and `WITH CHECK` constrains only `tenant_id`. So both stores resolve the parent
block under the acting tenant first and raise the existing
`CrossTenantWriteError`, mirroring `append_decision_alternative` (ADR-0037).

**RLS landed in the same packet as the tables.** The observation tables sat
unguarded for two packets and ADR-0037 had to fix it retroactively. Not repeated.

## Consequences

- **101 tests, 0 skipped.** The Postgres/RLS tests **ran** against native PG17.
  All six adversarial tests are parametrised across all three new tables: `ENABLE`
  **and** `FORCE` asserted from `pg_class`; cross-tenant raw scan with no WHERE
  clause; positive control; RESET-GUC deny-all; foreign-tenant write rejected;
  and FORCE lifted → boundary collapses → restored.
- The RESET test asserts the **empty-string case explicitly** — it checks
  `current_setting(...) == ''` *first*, then that zero rows return. Otherwise it
  would be proving the NULL branch, which is not the branch a reset session
  takes (ADR-0043's trap). These policies survive it only because
  `tenant_id = ''` is false for any real UUID, which is incidental and therefore
  pinned by test.
- **Both SQL files verified 0 deletions** — 128 insertions, purely
  additive/append-only, no existing table, column or policy touched.
- **SQLite portability proved** by running `schema_v0_1.sql`'s actual bytes
  through a bare `sqlite3.connect(":memory:")` with no store class involved,
  backed by an additivity check, the Postgres-construct regression guard, and a
  two-way drift test pinning the SQL `CHECK ... IN (...)` vocabulary equal to the
  Python `Literal`.

## Scope: this is the home, not a TODS adapter

No `app/connect` code was touched, no TODS file parsed, no TODS fixture
acquired. **TODS and NeTEx remain Specified**; these entities are **Demonstrated**
at most, on synthetic fixtures.

A TODS adapter would still need: a multi-file zip reader with GTFS-companion
resolution (every existing adapter reads one table or one protobuf); a
`SourceAdapter` under ADR-0007 with quarantine/semantic-loss discipline; **block
boundary derivation** — TODS does not state pull-out/pull-in directly, they are
implied by first/last associated trip times, so the rule must be recorded rather
than assumed; a classification map onto `DeadheadKind` with ambiguity → `other`;
and **GTFS calendar + timezone resolution including the >24:00:00 rollover**,
which is the single largest fidelity risk and lives entirely in the adapter.

Deliberately unmodelled, each needing its own decision: deadhead shapes/geometry,
sub-piece run events, and operator labour-rule constraints.
