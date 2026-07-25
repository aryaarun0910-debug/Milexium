"""SQLite-backed canonical store (dev/demo engine).

Loads `packages/canonical/sql/schema_v0_1.sql` unmodified -- see
architecture/decisions/0004-sqlite-now-postgres-production.md. A
PostgreSQL-backed store implementing the same method contract is Specified,
not Exists: it is added only once Program C actually connects to the
PostgreSQL 17 instance installed on 2026-07-23 (same ADR).

Every query in this module takes `tenant_id` and filters by it in SQL --
never in Python after an unfiltered fetch -- so a cross-tenant read is a
missing WHERE clause away from being impossible to write by accident, not
just unlikely.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from packages.canonical.entities import (
    Block,
    DeadheadSegment,
    DecisionAlternative,
    DecisionEvent,
    Outcome,
    RunPiece,
    Tenant,
    platform_tenant,
)
from packages.canonical.events import DuplicateEventError, canonical_json, compute_hash
from packages.canonical.ids import BlockId, DecisionEventId, ScheduleRunId, TenantId, new_id
from packages.canonical.vocab import DecisionEventType, ReasonCode

_SCHEMA_PATH = Path(__file__).parent / "sql" / "schema_v0_1.sql"


class CrossTenantWriteError(Exception):
    """A write named a parent aggregate that does not belong to the acting tenant.

    `decision_alternatives` carries no `tenant_id` column of its own -- it is
    tenant-scoped transitively through `schedule_runs`. Both stores therefore
    resolve the parent run *under the acting tenant* before inserting, and raise
    this if it is not there, so "which tenant owns this alternative" is never
    inferred from the caller's word alone. Defined here (not per-engine) so the
    SQLite and PostgreSQL stores raise the identical error type, per the mirrored
    method contract in architecture/decisions/0004-sqlite-now-postgres-production.md.
    """


class SqliteCanonicalStore:
    """Reference storage implementation for the canonical contract, v0.1."""

    def __init__(self, connection: sqlite3.Connection | None = None) -> None:
        self._conn = connection or sqlite3.connect(":memory:")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        self._seed_platform_tenant()

    @classmethod
    def open(cls, path: str) -> "SqliteCanonicalStore":
        return cls(connection=sqlite3.connect(path))

    def close(self) -> None:
        self._conn.close()

    def _seed_platform_tenant(self) -> None:
        """Register the reserved platform tenant (ADR-0040), idempotently.

        Records that belong to no customer -- the models in this repository are
        trained on public data -- still carry a mandatory `tenant_id`, and every
        tenant-scoped table has a FOREIGN KEY to `tenants`. So the reserved id
        has to be a real row or the first platform-owned insert fails on the FK.
        Seeding it is part of store setup, not a caller's responsibility.

        `INSERT OR IGNORE` (Postgres: `ON CONFLICT DO NOTHING`) makes this a
        no-op on a store whose database already has the row; `platform_tenant()`
        pins a fixed `created_at`, so a re-seed cannot even change the value.
        """
        tenant = platform_tenant()
        self._conn.execute(
            "INSERT OR IGNORE INTO tenants (tenant_id, name, created_at) VALUES (?, ?, ?)",
            (str(tenant.tenant_id), tenant.name, tenant.created_at.isoformat()),
        )
        self._conn.commit()

    def create_tenant(self, tenant: Tenant) -> None:
        self._conn.execute(
            "INSERT INTO tenants (tenant_id, name, created_at) VALUES (?, ?, ?)",
            (str(tenant.tenant_id), tenant.name, tenant.created_at.isoformat()),
        )
        self._conn.commit()

    def append_event(
        self,
        *,
        tenant_id: TenantId,
        aggregate_id: str,
        aggregate_type: str,
        occurred_at: datetime,
        actor_type: str,
        actor_id: str,
        event_type: DecisionEventType,
        payload: dict,
        reason_codes: tuple[ReasonCode, ...] = (),
        idempotency_key: str | None = None,
    ) -> DecisionEvent:
        cur = self._conn.cursor()

        if idempotency_key is not None:
            cur.execute(
                "SELECT event_id, sequence, prev_hash, hash, payload_json, occurred_at, "
                "actor_type, actor_id, event_type, reason_codes "
                "FROM decision_events WHERE tenant_id = ? AND aggregate_id = ? AND idempotency_key = ?",
                (str(tenant_id), aggregate_id, idempotency_key),
            )
            row = cur.fetchone()
            if row is not None:
                stored_payload = json.loads(row[4])
                if stored_payload != payload:
                    raise DuplicateEventError(
                        f"idempotency key {idempotency_key!r} already used with a different payload"
                    )
                return DecisionEvent(
                    event_id=row[0],
                    tenant_id=tenant_id,
                    aggregate_id=aggregate_id,
                    aggregate_type=aggregate_type,
                    sequence=row[1],
                    occurred_at=datetime.fromisoformat(row[5]),
                    actor_type=row[6],
                    actor_id=row[7],
                    event_type=DecisionEventType(row[8]),
                    payload=stored_payload,
                    reason_codes=tuple(ReasonCode(x) for x in json.loads(row[9])),
                    idempotency_key=idempotency_key,
                    prev_hash=row[2],
                    hash=row[3],
                )

        cur.execute(
            "SELECT sequence, hash FROM decision_events WHERE tenant_id = ? AND aggregate_id = ? "
            "ORDER BY sequence DESC LIMIT 1",
            (str(tenant_id), aggregate_id),
        )
        last = cur.fetchone()
        sequence = (last[0] + 1) if last else 1
        prev_hash = last[1] if last else None
        event_hash = compute_hash(prev_hash, payload, sequence, aggregate_id, idempotency_key)
        event_id = str(new_id(DecisionEventId))

        cur.execute(
            "INSERT INTO decision_events (event_id, tenant_id, aggregate_id, aggregate_type, "
            "sequence, occurred_at, actor_type, actor_id, event_type, payload_json, reason_codes, "
            "idempotency_key, prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                str(tenant_id),
                aggregate_id,
                aggregate_type,
                sequence,
                occurred_at.isoformat(),
                actor_type,
                actor_id,
                event_type.value,
                canonical_json(payload),
                canonical_json([rc.value for rc in reason_codes]),
                idempotency_key,
                prev_hash,
                event_hash,
            ),
        )
        self._conn.commit()
        return DecisionEvent(
            event_id=event_id,
            tenant_id=tenant_id,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            sequence=sequence,
            occurred_at=occurred_at,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=event_type,
            payload=payload,
            reason_codes=reason_codes,
            idempotency_key=idempotency_key,
            prev_hash=prev_hash,
            hash=event_hash,
        )

    def history(self, tenant_id: TenantId, aggregate_id: str) -> tuple[DecisionEvent, ...]:
        """Tenant-scoped read: the WHERE clause is the isolation boundary."""
        cur = self._conn.execute(
            "SELECT event_id, aggregate_type, sequence, occurred_at, actor_type, actor_id, "
            "event_type, payload_json, reason_codes, idempotency_key, prev_hash, hash "
            "FROM decision_events "
            "WHERE tenant_id = ? AND aggregate_id = ? ORDER BY sequence ASC",
            (str(tenant_id), aggregate_id),
        )
        events = []
        for row in cur.fetchall():
            events.append(
                DecisionEvent(
                    event_id=row[0],
                    tenant_id=tenant_id,
                    aggregate_id=aggregate_id,
                    aggregate_type=row[1],
                    sequence=row[2],
                    occurred_at=datetime.fromisoformat(row[3]),
                    actor_type=row[4],
                    actor_id=row[5],
                    event_type=DecisionEventType(row[6]),
                    payload=json.loads(row[7]),
                    reason_codes=tuple(ReasonCode(x) for x in json.loads(row[8])),
                    idempotency_key=row[9],
                    prev_hash=row[10],
                    hash=row[11],
                )
            )
        return tuple(events)

    def append_decision_alternative(
        self, *, tenant_id: TenantId, alternative: DecisionAlternative
    ) -> None:
        """Persist one considered-and-usually-rejected candidate assignment.

        `decision_alternatives` has existed in schema_v0_1.sql since v0.1 but had
        no store behind it, so "why not the alternatives?" -- a load-bearing
        explainability claim -- had nowhere to live. This does NOT replace the
        v0.1 convention of embedding alternatives in a RECOMMENDATION event
        payload (architecture/decisions/0009-...): both coexist, and nothing here
        migrates or invalidates an existing embedded payload.

        The table has no `tenant_id` of its own, so the acting tenant is resolved
        against the parent `schedule_runs` row FIRST; a run belonging to another
        tenant (or to no one) is a `CrossTenantWriteError`, never a silently
        accepted row.
        """
        cur = self._conn.cursor()
        cur.execute(
            "SELECT 1 FROM schedule_runs WHERE schedule_run_id = ? AND tenant_id = ?",
            (str(alternative.schedule_run_id), str(tenant_id)),
        )
        if cur.fetchone() is None:
            raise CrossTenantWriteError(
                f"schedule run {alternative.schedule_run_id!s} does not belong to "
                f"tenant {tenant_id!s}"
            )
        cur.execute(
            "INSERT INTO decision_alternatives (schedule_run_id, request_id, "
            "candidate_vehicle_id, feasible, failed_constraints, objective_delta) "
            "VALUES (?,?,?,?,?,?)",
            (
                str(alternative.schedule_run_id),
                str(alternative.request_id),
                str(alternative.candidate_vehicle_id)
                if alternative.candidate_vehicle_id is not None
                else None,
                1 if alternative.feasible else 0,
                canonical_json([rc.value for rc in alternative.failed_constraints]),
                alternative.objective_delta,
            ),
        )
        self._conn.commit()

    def decision_alternatives(
        self, tenant_id: TenantId, schedule_run_id: ScheduleRunId
    ) -> tuple[DecisionAlternative, ...]:
        """Tenant-scoped read of the alternatives considered by one schedule run.

        The JOIN to `schedule_runs` is the isolation boundary: the tenant filter
        is applied in SQL against the parent run, never in Python after an
        unfiltered fetch. Ordered by `request_id`, then candidates before the
        no-vehicle alternative -- expressed portably (`IS NULL` sorts as 0/1 on
        SQLite and false/true on PostgreSQL, both non-null first) so both stores
        return the same sequence, not merely the same set.
        """
        cur = self._conn.execute(
            "SELECT a.schedule_run_id, a.request_id, a.candidate_vehicle_id, a.feasible, "
            "a.failed_constraints, a.objective_delta "
            "FROM decision_alternatives a "
            "JOIN schedule_runs r ON r.schedule_run_id = a.schedule_run_id "
            "WHERE r.tenant_id = ? AND a.schedule_run_id = ? "
            "ORDER BY a.request_id, (a.candidate_vehicle_id IS NULL), a.candidate_vehicle_id",
            (str(tenant_id), str(schedule_run_id)),
        )
        return tuple(
            DecisionAlternative(
                schedule_run_id=row[0],
                request_id=row[1],
                candidate_vehicle_id=row[2],
                feasible=bool(row[3]),
                failed_constraints=tuple(ReasonCode(x) for x in json.loads(row[4])),
                objective_delta=row[5],
            )
            for row in cur.fetchall()
        )

    def record_outcome(self, outcome: Outcome) -> None:
        """Persist what actually happened to one request, INCLUDING the vehicle
        and run that performed it.

        This is the write ADR-0038 had no home for: `vehicle_ref`/`run_ref` were
        carried on the Connect-layer `OperatorTripRecord` only, so the field the
        deadhead teardown chains on could not survive a write to MilexiumDB. It
        now round-trips, in both stores (see
        `conformance/property-tests/test_run_reference.py`).

        The row's own `tenant_id` is the acting tenant -- an `Outcome` cannot
        exist without one, so there is no separate `tenant_id` argument to
        disagree with it. `(tenant_id, request_id)` is the primary key, so
        recording an outcome twice for the same request raises rather than
        silently overwriting the first answer.
        """
        self._conn.execute(
            "INSERT INTO outcomes (tenant_id, request_id, served, actual_pickup_at, on_time, "
            "excess_ride_time_minutes, deadhead_minutes, vehicle_ref, run_ref) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                str(outcome.tenant_id),
                str(outcome.request_id),
                1 if outcome.served else 0,
                outcome.actual_pickup_at.isoformat() if outcome.actual_pickup_at else None,
                None if outcome.on_time is None else (1 if outcome.on_time else 0),
                outcome.excess_ride_time_minutes,
                outcome.deadhead_minutes,
                outcome.vehicle_ref,
                outcome.run_ref,
            ),
        )
        self._conn.commit()

    def outcomes(self, tenant_id: TenantId) -> tuple[Outcome, ...]:
        """Tenant-scoped read of recorded outcomes, ordered by `request_id`.

        The WHERE clause is the isolation boundary, as everywhere else in this
        module. Reconstructing an `Outcome` on read means the stored columns must
        still validate as one -- a `run_ref` that came back as `''` or `'None'`
        rather than NULL would be a round-trip failure, not a cosmetic one.
        """
        cur = self._conn.execute(
            "SELECT request_id, served, actual_pickup_at, on_time, excess_ride_time_minutes, "
            "deadhead_minutes, vehicle_ref, run_ref FROM outcomes "
            "WHERE tenant_id = ? ORDER BY request_id",
            (str(tenant_id),),
        )
        return tuple(
            Outcome(
                tenant_id=tenant_id,
                request_id=row[0],
                served=bool(row[1]),
                actual_pickup_at=datetime.fromisoformat(row[2]) if row[2] is not None else None,
                on_time=None if row[3] is None else bool(row[3]),
                excess_ride_time_minutes=row[4],
                deadhead_minutes=row[5],
                vehicle_ref=row[6],
                run_ref=row[7],
            )
            for row in cur.fetchall()
        )

    # -- scheduling family (request-independent) ---------------------------
    #
    # Blocks, run pieces and deadhead segments are the canonical home TODS needs
    # (MX-A-SCHEDULING-FAMILY-006), the counterpart to the telemetry family
    # ADR-0035 landed. Each write takes the entity alone: every one of them
    # carries its own mandatory `tenant_id`, so there is no separate argument
    # that could disagree with the row -- the same contract `record_outcome`
    # already has. Each read takes the acting tenant and filters in SQL.
    #
    # `PostgresCanonicalStore` exposes these three pairs with identical
    # signatures and identical ordering (ADR-0004's mirrored-contract claim,
    # asserted structurally in the conformance suite).

    def _resolve_block_for_tenant(self, tenant_id: TenantId, block_id: BlockId | None) -> None:
        """Raise unless `block_id` is absent or names a block of `tenant_id`.

        `run_pieces.block_id` and `deadhead_segments.block_id` are real foreign
        keys to `blocks`, and a foreign key alone does NOT keep them inside the
        tenant: PostgreSQL evaluates referential integrity with RLS bypassed by
        design (see the note in sql/rls_postgres.sql), so the database would
        happily let tenant B's run piece point at tenant A's block. The parent is
        therefore resolved UNDER the acting tenant first, exactly as
        `append_decision_alternative` resolves its parent schedule run, so
        "which tenant owns this block" is never inferred from the caller's word.
        """
        if block_id is None:
            return
        cur = self._conn.execute(
            "SELECT 1 FROM blocks WHERE block_id = ? AND tenant_id = ?",
            (str(block_id), str(tenant_id)),
        )
        if cur.fetchone() is None:
            raise CrossTenantWriteError(
                f"block {block_id!s} does not belong to tenant {tenant_id!s}"
            )

    def record_block(self, block: Block) -> None:
        """Persist one vehicle's continuous work between pull-out and pull-in."""
        self._conn.execute(
            "INSERT INTO blocks (block_id, tenant_id, block_ref, service_ref, vehicle_ref, "
            "garage_ref, pull_out_at, pull_in_at, recorded_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                str(block.block_id),
                str(block.tenant_id),
                block.block_ref,
                block.service_ref,
                block.vehicle_ref,
                block.garage_ref,
                block.pull_out_at.isoformat(),
                block.pull_in_at.isoformat(),
                block.recorded_at.isoformat(),
            ),
        )
        self._conn.commit()

    def blocks(self, tenant_id: TenantId) -> tuple[Block, ...]:
        """Tenant-scoped read, ordered by valid time then by the surrogate key.

        Reconstructing a `Block` on read means the stored columns must still
        validate as one -- a `garage_ref` that came back as `''` rather than NULL,
        or a pull-in that read back before its pull-out, fails here rather than in
        whatever consumer trusted it."""
        cur = self._conn.execute(
            "SELECT block_id, block_ref, service_ref, vehicle_ref, garage_ref, pull_out_at, "
            "pull_in_at, recorded_at FROM blocks "
            "WHERE tenant_id = ? ORDER BY pull_out_at, block_id",
            (str(tenant_id),),
        )
        return tuple(
            Block(
                block_id=row[0],
                tenant_id=tenant_id,
                block_ref=row[1],
                service_ref=row[2],
                vehicle_ref=row[3],
                garage_ref=row[4],
                pull_out_at=datetime.fromisoformat(row[5]),
                pull_in_at=datetime.fromisoformat(row[6]),
                recorded_at=datetime.fromisoformat(row[7]),
            )
            for row in cur.fetchall()
        )

    def record_run_piece(self, piece: RunPiece) -> None:
        """Persist one continuous piece of an operator's run.

        A `block_id` naming another tenant's block is a `CrossTenantWriteError`,
        never a silently accepted row -- see `_resolve_block_for_tenant`."""
        self._resolve_block_for_tenant(piece.tenant_id, piece.block_id)
        self._conn.execute(
            "INSERT INTO run_pieces (run_piece_id, tenant_id, run_ref, piece_ref, piece_sequence, "
            "operator_ref, block_id, block_ref, vehicle_ref, start_type, end_type, started_at, "
            "ended_at, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(piece.run_piece_id),
                str(piece.tenant_id),
                piece.run_ref,
                piece.piece_ref,
                piece.piece_sequence,
                piece.operator_ref,
                None if piece.block_id is None else str(piece.block_id),
                piece.block_ref,
                piece.vehicle_ref,
                piece.start_type,
                piece.end_type,
                piece.started_at.isoformat(),
                piece.ended_at.isoformat(),
                piece.recorded_at.isoformat(),
            ),
        )
        self._conn.commit()

    def run_pieces(self, tenant_id: TenantId) -> tuple[RunPiece, ...]:
        """Tenant-scoped read, ordered by valid time then by the surrogate key."""
        cur = self._conn.execute(
            "SELECT run_piece_id, run_ref, piece_ref, piece_sequence, operator_ref, block_id, "
            "block_ref, vehicle_ref, start_type, end_type, started_at, ended_at, recorded_at "
            "FROM run_pieces WHERE tenant_id = ? ORDER BY started_at, run_piece_id",
            (str(tenant_id),),
        )
        return tuple(
            RunPiece(
                run_piece_id=row[0],
                tenant_id=tenant_id,
                run_ref=row[1],
                piece_ref=row[2],
                piece_sequence=row[3],
                operator_ref=row[4],
                block_id=row[5],
                block_ref=row[6],
                vehicle_ref=row[7],
                start_type=row[8],
                end_type=row[9],
                started_at=datetime.fromisoformat(row[10]),
                ended_at=datetime.fromisoformat(row[11]),
                recorded_at=datetime.fromisoformat(row[12]),
            )
            for row in cur.fetchall()
        )

    def record_deadhead_segment(self, segment: DeadheadSegment) -> None:
        """Persist one non-revenue vehicle movement.

        This is what makes a deadhead teardown re-derivable from stored state
        rather than only from an in-memory Connect handoff: `packages/replay/
        teardown.py` measures exactly these segments, and until now they had no
        canonical home to be read back out of."""
        self._resolve_block_for_tenant(segment.tenant_id, segment.block_id)
        self._conn.execute(
            "INSERT INTO deadhead_segments (deadhead_segment_id, tenant_id, deadhead_ref, "
            "block_id, block_ref, run_ref, vehicle_ref, deadhead_type, from_stop_ref, "
            "to_stop_ref, started_at, ended_at, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(segment.deadhead_segment_id),
                str(segment.tenant_id),
                segment.deadhead_ref,
                None if segment.block_id is None else str(segment.block_id),
                segment.block_ref,
                segment.run_ref,
                segment.vehicle_ref,
                segment.deadhead_type,
                segment.from_stop_ref,
                segment.to_stop_ref,
                segment.started_at.isoformat(),
                segment.ended_at.isoformat(),
                segment.recorded_at.isoformat(),
            ),
        )
        self._conn.commit()

    def deadhead_segments(self, tenant_id: TenantId) -> tuple[DeadheadSegment, ...]:
        """Tenant-scoped read, ordered by valid time then by the surrogate key --
        which is also the order a teardown wants to consume them in."""
        cur = self._conn.execute(
            "SELECT deadhead_segment_id, deadhead_ref, block_id, block_ref, run_ref, vehicle_ref, "
            "deadhead_type, from_stop_ref, to_stop_ref, started_at, ended_at, recorded_at "
            "FROM deadhead_segments WHERE tenant_id = ? ORDER BY started_at, deadhead_segment_id",
            (str(tenant_id),),
        )
        return tuple(
            DeadheadSegment(
                deadhead_segment_id=row[0],
                tenant_id=tenant_id,
                deadhead_ref=row[1],
                block_id=row[2],
                block_ref=row[3],
                run_ref=row[4],
                vehicle_ref=row[5],
                deadhead_type=row[6],
                from_stop_ref=row[7],
                to_stop_ref=row[8],
                started_at=datetime.fromisoformat(row[9]),
                ended_at=datetime.fromisoformat(row[10]),
                recorded_at=datetime.fromisoformat(row[11]),
            )
            for row in cur.fetchall()
        )

    def raw_rows_for_tenant(self, tenant_id: TenantId) -> list[dict]:
        """Unmapped raw rows for the independent verifier (packages/verify) and
        adversarial tampering fixtures -- deliberately bypasses the
        `DecisionEvent` reconstruction path above so the verifier is checking
        actual stored bytes, not trusting this class's own round-trip."""
        cur = self._conn.execute(
            "SELECT * FROM decision_events WHERE tenant_id = ? ORDER BY aggregate_id, sequence",
            (str(tenant_id),),
        )
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    def tamper_with_row(self, event_id: str, **column_overrides: object) -> None:
        """Test-only helper: directly corrupts a stored row to prove the
        verifier (not this class) is what catches it. Never called from
        non-test code."""
        assignments = ", ".join(f"{col} = ?" for col in column_overrides)
        self._conn.execute(
            f"UPDATE decision_events SET {assignments} WHERE event_id = ?",
            (*column_overrides.values(), event_id),
        )
        self._conn.commit()
