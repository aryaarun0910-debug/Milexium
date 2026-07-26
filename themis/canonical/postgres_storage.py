"""PostgreSQL-backed canonical store -- Program C's first real slice.

Mirrors `SqliteCanonicalStore`'s method contract (forge/knowledge/architecture/decisions/
0004-sqlite-now-postgres-production.md) against the PostgreSQL 17 instance
provisioned for local dev (forge/knowledge/architecture/decisions/0006-dedicated-postgres-dev-role.md).
Loads `themis/canonical/sql/schema_v0_1.sql` unmodified -- the same
portable DDL that already runs on SQLite runs here without edits.

Every query in this module takes `tenant_id` and filters by it in SQL --
never in Python after an unfiltered fetch -- for the same reason
`storage.py` does: a cross-tenant read is a missing WHERE clause away from
being impossible to write by accident, not just unlikely.

Each store instance owns a dedicated PostgreSQL schema (namespace), created
at construction time and torn down via `drop_schema()`. This is the
test-isolation strategy: a real Postgres server is a shared, persistent
process, not SQLite's ":memory:" default, so tests need an explicit,
disposable namespace rather than relying on process-exit cleanup. Random
per-instance schema names make parallel test runs safe from collision;
`DROP SCHEMA ... CASCADE` guarantees no cruft survives in `milexium_dev`
even if a test fails mid-way, as long as the caller's teardown runs it.

Connects only as the `milexium_dev` role (never the Postgres superuser) --
ADR-0006. The password is read from `%USERPROFILE%\\.milexium_pg_app_password.txt`
at connection time; it is never hardcoded or logged by this module.

Tenant isolation is enforced at the DATABASE layer, not just by the tenant_id
WHERE-clauses above. After the portable schema, this store applies
`sql/rls_postgres.sql`, which ENABLEs and FORCEs row-level security on every
tenant-scoped table with policies keyed on the `milexium.tenant_id` session
setting (a GUC). FORCE is essential: `milexium_dev` owns these tables and a
table owner bypasses RLS by default, so without FORCE the policies would not
constrain this store's own connection at all. Every operation calls
`_use_tenant()` to set that GUC (session scope) before it reads or writes, so
the policy -- not the application code -- is the tenant boundary. See
forge/knowledge/architecture/decisions/0018-postgres-row-level-security-tenant-isolation.md and
aletheia/conformance/adversarial/test_postgres_rls_isolation.py.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import sql

from themis.canonical.entities import (
    Block,
    DeadheadSegment,
    DecisionAlternative,
    DecisionEvent,
    Outcome,
    RunPiece,
    Tenant,
    platform_tenant,
)
from themis.canonical.events import DuplicateEventError, canonical_json, compute_hash
from themis.canonical.ids import (
    BlockId,
    DecisionEventId,
    RequestId,
    ScheduleRunId,
    TenantId,
    new_id,
)
from themis.canonical.lifecycle import (
    LateRecordingReason,
    OutcomeExplanation,
    RequestTransition,
    TimeWindow,
    explain,
    next_transition,
)
from themis.canonical.lifecycle_verify import (
    LifecycleChainVerification,
    verify_lifecycle_chain,
)
from themis.canonical.state_machine import ServiceRequestState
from themis.canonical.storage import (
    LIFECYCLE_COLUMNS,
    CrossTenantWriteError,
    _TRANSITION_SELECT,
    _transition_from_row,
    _transition_row_values,
)
from themis.canonical.transaction_clock import transaction_time
from themis.canonical.vocab import DecisionEventType, ReasonCode

_SCHEMA_PATH = Path(__file__).parent / "sql" / "schema_v0_1.sql"
_RLS_PATH = Path(__file__).parent / "sql" / "rls_postgres.sql"
# The unprivileged fallback, applied only when the cluster has never had
# talos/infra/compose/initdb/02-lifecycle-ledger-bootstrap.sql run against it. See that file for why
# the fallback is strictly weaker and must not be described as a boundary.
_LIFECYCLE_FALLBACK_PATH = Path(__file__).parent / "sql" / "lifecycle_immutability_postgres.sql"
_DEFAULT_PASSWORD_FILE = Path.home() / ".milexium_pg_app_password.txt"

#: What `_seal_lifecycle_ledger` achieved, exposed as `store.lifecycle_immutability`.
#: `owner_separated` is the deployment claim: the table is owned by
#: `milexium_ledger_owner`, this connection holds INSERT + SELECT only, and the
#: triggers call functions this connection cannot rewrite. `trigger_only` means the
#: cluster bootstrap has not been run, the acting role still OWNS the table, and the
#: guard is therefore removable by the credential it is meant to constrain.
LIFECYCLE_OWNER_SEPARATED = "owner_separated"
LIFECYCLE_TRIGGER_ONLY = "trigger_only"


def _read_dev_password() -> str:
    return _DEFAULT_PASSWORD_FILE.read_text(encoding="utf-8").strip()


def is_reachable(
    *,
    host: str = "localhost",
    port: int = 5432,
    dbname: str = "milexium_dev",
    user: str = "milexium_dev",
    password: str | None = None,
    connect_timeout: float = 2.0,
) -> bool:
    """Best-effort connectivity probe. Lets test suites skip cleanly (not
    fail) on a machine with no reachable PostgreSQL instance -- this repo
    may be cloned somewhere `milexium_dev` was never provisioned."""
    try:
        if password is None:
            password = _read_dev_password()
        conn = psycopg.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            connect_timeout=connect_timeout,
        )
        conn.close()
        return True
    except Exception:
        return False


class PostgresCanonicalStore:
    """PostgreSQL-backed storage implementation for the canonical contract, v0.1."""

    def __init__(
        self,
        connection: psycopg.Connection,
        *,
        schema: str | None = None,
        _leave_lifecycle_unsealed: bool = False,
    ) -> None:
        """`_leave_lifecycle_unsealed` EXISTS FOR ONE CONFORMANCE TEST and is
        underscored so nobody reaches for it by accident.

        Sealing the ledger takes the table's ownership away from this connection,
        which is the point -- and which also removes this connection's ability to
        `ALTER TABLE ... NO FORCE ROW LEVEL SECURITY`. The RLS suite proves FORCE is
        load-bearing by lifting it and watching the tenant boundary collapse, and
        that demonstration needs ownership. So one test constructs an explicitly
        UNSEALED store to run it, and a companion test asserts that the DEFAULT
        store cannot lift FORCE at all. Both facts are stronger stated together
        than either would be alone.
        """
        self._conn = connection
        self._schema = schema or f"mx_{uuid.uuid4().hex}"
        #: See LIFECYCLE_OWNER_SEPARATED / LIFECYCLE_TRIGGER_ONLY.
        self.lifecycle_immutability = LIFECYCLE_TRIGGER_ONLY
        self._create_schema_and_apply_ddl(seal_lifecycle=not _leave_lifecycle_unsealed)

    @classmethod
    def connect(
        cls,
        *,
        host: str = "localhost",
        port: int = 5432,
        dbname: str = "milexium_dev",
        user: str = "milexium_dev",
        password: str | None = None,
        schema: str | None = None,
        _leave_lifecycle_unsealed: bool = False,
    ) -> "PostgresCanonicalStore":
        if password is None:
            password = _read_dev_password()
        connection = psycopg.connect(host=host, port=port, dbname=dbname, user=user, password=password)
        return cls(
            connection, schema=schema, _leave_lifecycle_unsealed=_leave_lifecycle_unsealed
        )

    def _create_schema_and_apply_ddl(self, *, seal_lifecycle: bool = True) -> None:
        ident = sql.Identifier(self._schema)
        with self._conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(ident))
            cur.execute(sql.SQL("SET search_path TO {}").format(ident))
            cur.execute(_SCHEMA_PATH.read_text(encoding="utf-8"))
            # RLS is Postgres-only, so it is a separate file applied only here --
            # never in the portable schema_v0_1.sql (which must also run on
            # SQLite). Applied inside the same schema (search_path already set),
            # so unqualified table names in rls_postgres.sql resolve to it.
            cur.execute(_RLS_PATH.read_text(encoding="utf-8"))
        self._conn.commit()
        if seal_lifecycle:
            self.lifecycle_immutability = self._seal_lifecycle_ledger()
        else:
            # NOT "no guards at all". `_leave_lifecycle_unsealed` chooses between
            # the two REAL configurations -- sealed, and the unprivileged fallback
            # a cluster without the bootstrap gets -- so the conformance test that
            # uses it is measuring a configuration this code can actually be in.
            # An earlier revision skipped immutability entirely here, which made
            # the trigger tests pass vacuously by asserting a trigger that was
            # never installed.
            self._apply_lifecycle_fallback()
            self.lifecycle_immutability = LIFECYCLE_TRIGGER_ONLY
        self._seed_platform_tenant()

    def _apply_lifecycle_fallback(self) -> None:
        """Install the triggers an ordinary table-owning role can install itself."""
        with self._conn.cursor() as cur:
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self._schema)))
            cur.execute(_LIFECYCLE_FALLBACK_PATH.read_text(encoding="utf-8"))
        self._conn.commit()

    def _seal_lifecycle_ledger(self) -> str:
        """Make the lifecycle table immutable, and say honestly how immutable.

        Prefers `public.milexium_seal_lifecycle_ledger`, installed once per cluster
        by a superuser from talos/infra/compose/initdb/02-lifecycle-ledger-bootstrap.sql.
        That function transfers the table to `milexium_ledger_owner` -- a role this
        connection cannot assume -- installs triggers calling ledger-owned
        functions, and reduces this connection to INSERT + SELECT. After it runs,
        the credential this store connects with can append to the record and read
        it, and can do NOTHING ELSE to it.

        Where that bootstrap has never been run (a fresh clone, someone else's
        laptop), it falls back to sql/lifecycle_immutability_postgres.sql, which
        installs the same triggers owned by this role -- real protection against an
        accidental UPDATE, and no protection at all against a determined holder of
        this credential, who can simply drop them. The two are NOT presented as
        equivalent: the store records which it got, and the conformance suite
        asserts the sealed properties rather than accepting what it finds.

        `UndefinedFunction` is caught NARROWLY -- only the bootstrap being absent
        falls back. A seal that exists and FAILS propagates, because a half-sealed
        ledger reported as sealed is the failure mode this whole packet is about.
        """
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT public.milexium_seal_lifecycle_ledger(%s)", (self._schema,)
                )
                cur.fetchone()
            self._conn.commit()
            return LIFECYCLE_OWNER_SEPARATED
        except psycopg.errors.UndefinedFunction:
            self._conn.rollback()

        self._apply_lifecycle_fallback()
        return LIFECYCLE_TRIGGER_ONLY

    def _seed_platform_tenant(self) -> None:
        """Register the reserved platform tenant (ADR-0040), idempotently.

        Same contract and same reason as
        `SqliteCanonicalStore._seed_platform_tenant`: the reserved id has to be a
        real `tenants` row or the foreign key rejects the first platform-owned
        insert, so seeding it is part of store setup rather than a caller's job.

        It runs AFTER rls_postgres.sql, under the policy it just installed, so it
        must set the GUC to the platform id first -- the `tenants` policy's
        WITH CHECK is `tenant_id = GUC`, and this row registers the platform as
        itself, exactly as `create_tenant()` has every other tenant register
        itself. `ON CONFLICT DO NOTHING` is the idempotency; `platform_tenant()`
        pins a fixed `created_at`, so a re-seed cannot change the value either.
        """
        tenant = platform_tenant()
        self._use_tenant(tenant.tenant_id)
        self._conn.execute(
            "INSERT INTO tenants (tenant_id, name, created_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (tenant_id) DO NOTHING",
            (str(tenant.tenant_id), tenant.name, tenant.created_at.isoformat()),
        )
        self._conn.commit()

    def _use_tenant(self, tenant_id: object) -> None:
        """Set the session's RLS key (`milexium.tenant_id`) to `tenant_id`.

        Every read/write below runs under the `tenant_isolation` policies in
        sql/rls_postgres.sql, which key on this GUC. Session scope
        (`is_local=false`) means the value survives the per-operation commits
        this store issues -- but each operation re-sets it first, so no
        operation ever depends on a value left by a previous one, and a wrong or
        unset GUC denies all rows (the policy's default is deny, not allow).
        `set_config` takes `tenant_id` as a bound parameter, so the value is
        never string-interpolated into SQL."""
        self._conn.execute(
            "SELECT set_config('milexium.tenant_id', %s, false)", (str(tenant_id),)
        )

    def drop_schema(self) -> None:
        """Test/teardown helper: drops this instance's dedicated schema and
        everything in it. Never called from non-test code."""
        ident = sql.Identifier(self._schema)
        with self._conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(ident))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def create_tenant(self, tenant: Tenant) -> None:
        # A tenant registers itself: the GUC is the new tenant's own id, so the
        # tenants-table WITH CHECK (tenant_id = GUC) permits exactly this row.
        self._use_tenant(tenant.tenant_id)
        self._conn.execute(
            "INSERT INTO tenants (tenant_id, name, created_at) VALUES (%s, %s, %s)",
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
        # Set the RLS key before any read or write: the SELECTs below and the
        # INSERT are all governed by the decision_events policy keyed on it.
        self._use_tenant(tenant_id)
        cur = self._conn.cursor()

        if idempotency_key is not None:
            cur.execute(
                "SELECT event_id, sequence, prev_hash, hash, payload_json, occurred_at, "
                "actor_type, actor_id, event_type, reason_codes "
                "FROM decision_events WHERE tenant_id = %s AND aggregate_id = %s AND idempotency_key = %s",
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
            "SELECT sequence, hash FROM decision_events WHERE tenant_id = %s AND aggregate_id = %s "
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
            "idempotency_key, prev_hash, hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
        """Tenant-scoped read. Two independent boundaries now hold: the RLS
        policy (keyed on the GUC set here) enforced by the database, and the
        WHERE clause below -- defense in depth, either alone sufficient."""
        self._use_tenant(tenant_id)
        cur = self._conn.execute(
            "SELECT event_id, aggregate_type, sequence, occurred_at, actor_type, actor_id, "
            "event_type, payload_json, reason_codes, idempotency_key, prev_hash, hash "
            "FROM decision_events "
            "WHERE tenant_id = %s AND aggregate_id = %s ORDER BY sequence ASC",
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

        Same contract, same error type, same semantics as
        `SqliteCanonicalStore.append_decision_alternative` -- including that it
        does NOT replace the ADR-0009 embedded-payload convention; both coexist.

        Two independent boundaries hold here. The parent-run lookup below runs
        under the acting GUC, so RLS has already hidden other tenants' runs
        before the Python check sees them; and `decision_alternatives`' own
        `tenant_isolation` WITH CHECK (keyed on the parent run's tenant, see
        sql/rls_postgres.sql) would reject the INSERT at the database layer even
        if this method's check were removed.
        """
        self._use_tenant(tenant_id)
        cur = self._conn.cursor()
        cur.execute(
            "SELECT 1 FROM schedule_runs WHERE schedule_run_id = %s AND tenant_id = %s",
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
            "VALUES (%s,%s,%s,%s,%s,%s)",
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

        Defense in depth, as `history()` above: the RLS policy (keyed on the GUC
        set here) and the JOIN's `tenant_id` filter are both boundaries, either
        alone sufficient. The ORDER BY is written identically to the SQLite
        store's so both engines return the same sequence, not merely the same set.
        """
        self._use_tenant(tenant_id)
        cur = self._conn.execute(
            "SELECT a.schedule_run_id, a.request_id, a.candidate_vehicle_id, a.feasible, "
            "a.failed_constraints, a.objective_delta "
            "FROM decision_alternatives a "
            "JOIN schedule_runs r ON r.schedule_run_id = a.schedule_run_id "
            "WHERE r.tenant_id = %s AND a.schedule_run_id = %s "
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

        Identical contract and semantics to
        `SqliteCanonicalStore.record_outcome` -- the canonical home ADR-0038
        found missing for `vehicle_ref`/`run_ref`, now durable on both engines.

        Two boundaries hold, as everywhere else in this store: the `outcomes`
        `tenant_isolation` policy's WITH CHECK (keyed on the GUC set here) would
        reject a row stamped with another tenant, and the row's own `tenant_id`
        is what the GUC is set from, so the two cannot disagree.
        """
        self._use_tenant(outcome.tenant_id)
        self._conn.execute(
            "INSERT INTO outcomes (tenant_id, request_id, served, actual_pickup_at, on_time, "
            "excess_ride_time_minutes, deadhead_minutes, vehicle_ref, run_ref) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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

        Defense in depth as elsewhere: the RLS policy (keyed on the GUC set here)
        and the WHERE clause are both boundaries, either alone sufficient. The
        ORDER BY is written identically to the SQLite store's so both engines
        return the same sequence, not merely the same set.
        """
        self._use_tenant(tenant_id)
        cur = self._conn.execute(
            "SELECT request_id, served, actual_pickup_at, on_time, excess_ride_time_minutes, "
            "deadhead_minutes, vehicle_ref, run_ref FROM outcomes "
            "WHERE tenant_id = %s ORDER BY request_id",
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
    # The same three pairs `SqliteCanonicalStore` exposes, with the same names,
    # the same signatures, the same ORDER BY clauses and the same error types --
    # so the two engines return the same SEQUENCE, not merely the same set
    # (ADR-0004's mirrored-contract claim).
    #
    # Two independent boundaries hold on every one of them, as everywhere else in
    # this store: the `tenant_isolation` policy on blocks / run_pieces /
    # deadhead_segments (keyed on the GUC set here, ENABLE + FORCE in
    # sql/rls_postgres.sql) and the tenant filter in the SQL itself.

    def _resolve_block_for_tenant(self, tenant_id: TenantId, block_id: BlockId | None) -> None:
        """Raise unless `block_id` is absent or names a block of `tenant_id`.

        THIS CHECK IS NOT REDUNDANT WITH RLS, and this store is where that
        matters most. The `run_pieces.block_id` / `deadhead_segments.block_id`
        foreign keys are evaluated by PostgreSQL with RLS BYPASSED by design (the
        note near the top of sql/rls_postgres.sql), and the tables' own WITH CHECK
        clauses only constrain `tenant_id` -- so nothing in the database stops
        tenant B's run piece from pointing at tenant A's block. The parent is
        resolved under the acting GUC first, which is also why the lookup below is
        itself policy-filtered: another tenant's block is invisible here, so it
        cannot be confirmed and the write is refused.
        """
        if block_id is None:
            return
        cur = self._conn.execute(
            "SELECT 1 FROM blocks WHERE block_id = %s AND tenant_id = %s",
            (str(block_id), str(tenant_id)),
        )
        if cur.fetchone() is None:
            raise CrossTenantWriteError(
                f"block {block_id!s} does not belong to tenant {tenant_id!s}"
            )

    def record_block(self, block: Block) -> None:
        """Persist one vehicle's continuous work between pull-out and pull-in."""
        self._use_tenant(block.tenant_id)
        self._conn.execute(
            "INSERT INTO blocks (block_id, tenant_id, block_ref, service_ref, vehicle_ref, "
            "garage_ref, pull_out_at, pull_in_at, recorded_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
        """Tenant-scoped read, ordered by valid time then by the surrogate key."""
        self._use_tenant(tenant_id)
        cur = self._conn.execute(
            "SELECT block_id, block_ref, service_ref, vehicle_ref, garage_ref, pull_out_at, "
            "pull_in_at, recorded_at FROM blocks "
            "WHERE tenant_id = %s ORDER BY pull_out_at, block_id",
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

        A `block_id` naming another tenant's block is a `CrossTenantWriteError` --
        the identical error type the SQLite store raises, for the identical
        reason. See `_resolve_block_for_tenant`."""
        self._use_tenant(piece.tenant_id)
        self._resolve_block_for_tenant(piece.tenant_id, piece.block_id)
        self._conn.execute(
            "INSERT INTO run_pieces (run_piece_id, tenant_id, run_ref, piece_ref, piece_sequence, "
            "operator_ref, block_id, block_ref, vehicle_ref, start_type, end_type, started_at, "
            "ended_at, recorded_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
        self._use_tenant(tenant_id)
        cur = self._conn.execute(
            "SELECT run_piece_id, run_ref, piece_ref, piece_sequence, operator_ref, block_id, "
            "block_ref, vehicle_ref, start_type, end_type, started_at, ended_at, recorded_at "
            "FROM run_pieces WHERE tenant_id = %s ORDER BY started_at, run_piece_id",
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
        """Persist one non-revenue vehicle movement -- the canonical home a
        deadhead teardown can now be re-derived from."""
        self._use_tenant(segment.tenant_id)
        self._resolve_block_for_tenant(segment.tenant_id, segment.block_id)
        self._conn.execute(
            "INSERT INTO deadhead_segments (deadhead_segment_id, tenant_id, deadhead_ref, "
            "block_id, block_ref, run_ref, vehicle_ref, deadhead_type, from_stop_ref, "
            "to_stop_ref, started_at, ended_at, recorded_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
        """Tenant-scoped read, ordered by valid time then by the surrogate key."""
        self._use_tenant(tenant_id)
        cur = self._conn.execute(
            "SELECT deadhead_segment_id, deadhead_ref, block_id, block_ref, run_ref, vehicle_ref, "
            "deadhead_type, from_stop_ref, to_stop_ref, started_at, ended_at, recorded_at "
            "FROM deadhead_segments WHERE tenant_id = %s ORDER BY started_at, deadhead_segment_id",
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

    # -- the durable lifecycle record ---------------------------------------
    #
    # The same three methods `SqliteCanonicalStore` exposes, with the same names,
    # the same signatures, the same ORDER BY and the same error types -- and both
    # engines delegate the chain rules and the explain view to the pure functions
    # in `lifecycle.py`, so neither the legality rules nor the view a regulator
    # would be shown can differ by engine.
    #
    # Two independent boundaries hold, as everywhere else in this store: the
    # `request_state_transitions` tenant_isolation policy (ENABLE + FORCE, keyed
    # on the GUC set here) and the tenant filter in the SQL itself.
    #
    # NO CLOCK IS READ IN THIS MODULE. `decided_at` is a required argument, the
    # column carries no SQL DEFAULT, and there is no `datetime.now()` here -- all
    # three asserted in the conformance suite. `recorded_at` is no longer an
    # argument: the writer stamps it via `transaction_clock.transaction_time()` and
    # a BEFORE INSERT trigger refuses any value more than
    # RECORDED_AT_TOLERANCE_SECONDS from this server's own clock, so a raw-SQL path
    # that never touches Python cannot assert a transaction time either.

    def _lifecycle_head(
        self, tenant_id: TenantId, request_id: RequestId
    ) -> RequestTransition | None:
        """The request's last recorded transition, or None. Runs under the acting
        GUC, so another tenant's chain is invisible here rather than merely
        filtered out."""
        cur = self._conn.execute(
            f"SELECT {_TRANSITION_SELECT} "  # noqa: S608 -- a fixed column list, no input
            "FROM request_state_transitions WHERE tenant_id = %s AND request_id = %s "
            "ORDER BY sequence DESC LIMIT 1",
            (str(tenant_id), str(request_id)),
        )
        row = cur.fetchone()
        return None if row is None else _transition_from_row(tenant_id, request_id, row)

    def record_transition(
        self,
        *,
        tenant_id: TenantId,
        request_id: RequestId,
        from_state: ServiceRequestState,
        to_state: ServiceRequestState,
        decided_at: datetime,
        actor_type: str,
        actor_id: str,
        reason_codes: tuple[ReasonCode, ...] = (),
        requested_window: TimeWindow | None = None,
        negotiated_window: TimeWindow | None = None,
        late_reason: LateRecordingReason | None = None,
    ) -> RequestTransition:
        """Append one transition to a request's lifecycle record.

        Identical contract, identical error types and identical refusal order to
        `SqliteCanonicalStore.record_transition` -- `BackdatedRecordError`,
        `LifecycleOrderError`, `TransitionError`, `UndeclaredLateRecordError` --
        because both call the same `next_transition`.

        `decided_at` is a REQUIRED keyword argument with no default and no SQL
        DEFAULT on its column, so neither this method nor the database can stamp a
        decision time. There is no `recorded_at` argument: transaction time is
        stamped by the writer and then BOUNDED BY THIS DATABASE -- the column
        carries a server-clock DEFAULT and a BEFORE INSERT trigger refuses any
        value far from `clock_timestamp()`. That trigger is what closes the audit
        finding against raw SQL, because a DEFAULT alone fires only when the column
        is omitted and the audit's insert supplied it.
        """
        self._use_tenant(tenant_id)
        head = self._lifecycle_head(tenant_id, request_id)
        transition = next_transition(
            tenant_id=tenant_id,
            request_id=request_id,
            head=head,
            from_state=from_state,
            to_state=to_state,
            decided_at=decided_at,
            recorded_at=transaction_time(),
            actor_type=actor_type,
            actor_id=actor_id,
            reason_codes=reason_codes,
            requested_window=requested_window,
            negotiated_window=negotiated_window,
            late_reason=late_reason,
        )
        self._conn.execute(
            "INSERT INTO request_state_transitions (transition_id, tenant_id, request_id, "
            "sequence, from_state, to_state, decided_at, recorded_at, actor_type, actor_id, "
            "reason_codes, requested_window_start, requested_window_end, "
            "negotiated_window_start, negotiated_window_end, ingest_lag_seconds, "
            "late_recording_reason, prev_hash, hash) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            _transition_row_values(transition),
        )
        self._conn.commit()
        return transition

    def request_lifecycle(
        self, tenant_id: TenantId, request_id: RequestId
    ) -> tuple[RequestTransition, ...]:
        """The ordered transition history for one request.

        Ordered by `sequence`, an INTEGER. That is not a stylistic match with the
        SQLite store: ordering by `decided_at` would order by the DATABASE
        COLLATION here, which for the fractional-second case is demonstrably not
        chronological order (see the note in schema_v0_1.sql)."""
        self._use_tenant(tenant_id)
        cur = self._conn.execute(
            f"SELECT {_TRANSITION_SELECT} "  # noqa: S608 -- a fixed column list, no input
            "FROM request_state_transitions WHERE tenant_id = %s AND request_id = %s "
            "ORDER BY sequence ASC",
            (str(tenant_id), str(request_id)),
        )
        return tuple(
            _transition_from_row(tenant_id, request_id, row) for row in cur.fetchall()
        )

    def raw_lifecycle_rows(self, tenant_id: TenantId, request_id: RequestId) -> list[dict]:
        """UNMAPPED lifecycle rows for the chain verifier -- the same contract, the
        same column order and the same reasoning as the SQLite store's: the
        verifier checks stored bytes, not this class's own round-trip."""
        self._use_tenant(tenant_id)
        cur = self._conn.execute(
            f"SELECT {', '.join(LIFECYCLE_COLUMNS)} "  # noqa: S608 -- fixed column list
            "FROM request_state_transitions WHERE tenant_id = %s AND request_id = %s "
            "ORDER BY sequence ASC",
            (str(tenant_id), str(request_id)),
        )
        return [dict(zip(LIFECYCLE_COLUMNS, row)) for row in cur.fetchall()]

    def verify_request_lifecycle(
        self, tenant_id: TenantId, request_id: RequestId
    ) -> LifecycleChainVerification:
        """Re-derive this request's hash chain from stored rows. Reports, never
        raises -- identical to the SQLite store."""
        return verify_lifecycle_chain(self.raw_lifecycle_rows(tenant_id, request_id))

    def explain_outcome(
        self, tenant_id: TenantId, request_id: RequestId
    ) -> OutcomeExplanation | None:
        """Why this request ended the way it did -- the same view the SQLite store
        returns, built by the same pure function from the same ordered history."""
        return explain(
            tenant_id=tenant_id,
            request_id=request_id,
            transitions=self.request_lifecycle(tenant_id, request_id),
        )

    def raw_rows_for_tenant(self, tenant_id: TenantId) -> list[dict]:
        """Unmapped raw rows for the independent verifier (aletheia/verify) and
        adversarial tampering fixtures -- deliberately bypasses the
        `DecisionEvent` reconstruction path above so the verifier is checking
        actual stored bytes, not trusting this class's own round-trip."""
        self._use_tenant(tenant_id)
        cur = self._conn.execute(
            "SELECT * FROM decision_events WHERE tenant_id = %s ORDER BY aggregate_id, sequence",
            (str(tenant_id),),
        )
        columns = [d.name for d in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    def tamper_with_row(self, event_id: str, **column_overrides: object) -> None:
        """Test-only helper: directly corrupts a stored row to prove the
        verifier (not this class) is what catches it. Never called from
        non-test code.

        Takes no tenant_id, so this UPDATE runs under whatever tenant the
        session GUC currently names (FORCE RLS applies to this owning role too).
        Every caller reaches this after a store read for the target tenant, so
        the GUC already names that tenant and the row is in scope. If it did
        not, the UPDATE would simply affect zero rows and the asserting test
        would fail loudly -- never silently pass."""
        assignments = ", ".join(f"{col} = %s" for col in column_overrides)
        self._conn.execute(
            f"UPDATE decision_events SET {assignments} WHERE event_id = %s",
            (*column_overrides.values(), event_id),
        )
        self._conn.commit()
