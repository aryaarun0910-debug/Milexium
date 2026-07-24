"""PostgreSQL-backed canonical store -- Program C's first real slice.

Mirrors `SqliteCanonicalStore`'s method contract (architecture/decisions/
0004-sqlite-now-postgres-production.md) against the PostgreSQL 17 instance
provisioned for local dev (architecture/decisions/0006-dedicated-postgres-dev-role.md).
Loads `packages/canonical/sql/schema_v0_1.sql` unmodified -- the same
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
architecture/decisions/0018-postgres-row-level-security-tenant-isolation.md and
conformance/adversarial/test_postgres_rls_isolation.py.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import sql

from packages.canonical.entities import DecisionAlternative, DecisionEvent, Tenant
from packages.canonical.events import DuplicateEventError, canonical_json, compute_hash
from packages.canonical.ids import DecisionEventId, ScheduleRunId, TenantId, new_id
from packages.canonical.storage import CrossTenantWriteError
from packages.canonical.vocab import DecisionEventType, ReasonCode

_SCHEMA_PATH = Path(__file__).parent / "sql" / "schema_v0_1.sql"
_RLS_PATH = Path(__file__).parent / "sql" / "rls_postgres.sql"
_DEFAULT_PASSWORD_FILE = Path.home() / ".milexium_pg_app_password.txt"


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

    def __init__(self, connection: psycopg.Connection, *, schema: str | None = None) -> None:
        self._conn = connection
        self._schema = schema or f"mx_{uuid.uuid4().hex}"
        self._create_schema_and_apply_ddl()

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
    ) -> "PostgresCanonicalStore":
        if password is None:
            password = _read_dev_password()
        connection = psycopg.connect(host=host, port=port, dbname=dbname, user=user, password=password)
        return cls(connection, schema=schema)

    def _create_schema_and_apply_ddl(self) -> None:
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

    def raw_rows_for_tenant(self, tenant_id: TenantId) -> list[dict]:
        """Unmapped raw rows for the independent verifier (packages/verify) and
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
