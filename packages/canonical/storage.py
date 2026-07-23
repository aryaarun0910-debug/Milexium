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

from packages.canonical.entities import DecisionEvent, Tenant
from packages.canonical.events import DuplicateEventError, canonical_json, compute_hash
from packages.canonical.ids import DecisionEventId, TenantId, new_id
from packages.canonical.vocab import DecisionEventType, ReasonCode

_SCHEMA_PATH = Path(__file__).parent / "sql" / "schema_v0_1.sql"


class SqliteCanonicalStore:
    """Reference storage implementation for the canonical contract, v0.1."""

    def __init__(self, connection: sqlite3.Connection | None = None) -> None:
        self._conn = connection or sqlite3.connect(":memory:")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))

    @classmethod
    def open(cls, path: str) -> "SqliteCanonicalStore":
        return cls(connection=sqlite3.connect(path))

    def close(self) -> None:
        self._conn.close()

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
