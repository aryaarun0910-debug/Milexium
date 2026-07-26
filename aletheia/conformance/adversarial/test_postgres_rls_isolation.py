"""Adversarial proof that tenant isolation is enforced at the DATABASE layer by
PostgreSQL row-level security -- not merely by the `tenant_id` WHERE-clauses in
`themis/canonical/postgres_storage.py`.

The distinction is the whole point of the packet. `test_postgres_tamper_and_
isolation.py` already proves the *application* refuses cross-tenant reads. These
tests go beneath the store's Python and issue RAW SQL on the connection with no
WHERE clause at all, after setting the RLS session key (`milexium.tenant_id`) to
a foreign tenant. If isolation lived only in the app's WHERE-clauses, these
queries would return other tenants' rows. They must return zero, because the
`tenant_isolation` policies in `sql/rls_postgres.sql` -- ENABLEd and, critically,
FORCEd -- are the boundary.

FORCE matters: `milexium_dev` OWNS these tables, and a table owner bypasses RLS
by default. `test_force_row_level_security_is_load_bearing` demonstrates the
boundary collapsing the instant FORCE is lifted, proving it is load-bearing and
that a naive ENABLE-only setup would be a false green against the owning role.

Skips cleanly (not a failure) if PostgreSQL is unreachable, so this suite stays
green on a machine where `milexium_dev` was never provisioned.
"""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg
import pytest

from themis.canonical import DecisionEventType, TenantId, new_id
from themis.canonical.postgres_storage import PostgresCanonicalStore, is_reachable

from conformance.fixtures.builders import example_tenant

if not is_reachable():
    pytest.skip(
        "PostgreSQL (milexium_dev) is not reachable on this machine; "
        "skipping Postgres RLS conformance tests",
        allow_module_level=True,
    )


def _utc(*args, **kwargs) -> datetime:
    return datetime(*args, tzinfo=timezone.utc, **kwargs)


@pytest.fixture
def pg_store():
    store = PostgresCanonicalStore.connect()
    try:
        yield store
    finally:
        store.drop_schema()
        store.close()


def _seed_tenant_with_events(store: PostgresCanonicalStore, n: int = 3) -> tuple[TenantId, str]:
    """Create a tenant and append `n` events; return (tenant_id, aggregate_id)."""
    tenant = example_tenant()
    store.create_tenant(tenant)
    aggregate_id = "req-rls-0001"
    for i in range(n):
        store.append_event(
            tenant_id=tenant.tenant_id,
            aggregate_id=aggregate_id,
            aggregate_type="ServiceRequest",
            occurred_at=_utc(2026, 7, 24, 8, i),
            actor_type="system",
            actor_id="scheduler",
            event_type=DecisionEventType.RECOMMENDATION,
            payload={"i": i},
        )
    return tenant.tenant_id, aggregate_id


def _set_session_tenant(store: PostgresCanonicalStore, tenant_id: object) -> None:
    """Set the RLS session key directly on the connection -- exactly what an
    attacker with the app credential, or a bug, could do -- so the raw reads
    below are governed only by the policy, not by any Python-side filter."""
    store._conn.execute(
        "SELECT set_config('milexium.tenant_id', %s, false)", (str(tenant_id),)
    )


def test_database_layer_blocks_cross_tenant_read(pg_store) -> None:
    """Core proof: with the session set to tenant B, a raw `SELECT` over the
    whole `decision_events` table -- no WHERE clause -- returns ZERO of tenant
    A's rows. The policy, not the application, is the boundary."""
    tenant_a, aggregate_id = _seed_tenant_with_events(pg_store, n=3)

    tenant_b = example_tenant()
    pg_store.create_tenant(tenant_b)
    pg_store.append_event(
        tenant_id=tenant_b.tenant_id,
        aggregate_id=aggregate_id,  # same aggregate_id, different tenant
        aggregate_type="ServiceRequest",
        occurred_at=_utc(2026, 7, 24, 9, 0),
        actor_type="system",
        actor_id="scheduler",
        event_type=DecisionEventType.RECOMMENDATION,
        payload={"i": "b-only"},
    )

    # Act as tenant B, then read the raw table with NO Python WHERE-clause.
    _set_session_tenant(pg_store, tenant_b.tenant_id)
    cur = pg_store._conn.execute("SELECT event_id, tenant_id, payload_json FROM decision_events")
    rows = cur.fetchall()
    pg_store._conn.commit()

    visible_tenants = {r[1] for r in rows}
    assert visible_tenants == {str(tenant_b.tenant_id)}, (
        "a raw table scan as tenant B leaked another tenant's rows -- RLS is not "
        "the boundary"
    )
    assert len(rows) == 1
    # And specifically: none of tenant A's rows are present.
    assert str(tenant_a) not in visible_tenants


def test_tenant_scoped_read_still_returns_own_rows(pg_store) -> None:
    """Positive control: RLS must not over-block. Acting as tenant A, a raw
    table scan returns exactly A's own rows."""
    tenant_a, _ = _seed_tenant_with_events(pg_store, n=3)

    _set_session_tenant(pg_store, tenant_a)
    cur = pg_store._conn.execute("SELECT count(*), array_agg(DISTINCT tenant_id) FROM decision_events")
    count, tenants = cur.fetchone()
    pg_store._conn.commit()

    assert count == 3
    assert tenants == [str(tenant_a)]


def test_unset_session_tenant_denies_all_rows(pg_store) -> None:
    """Default-deny: with the session key reset (no tenant named), the policy
    grants nothing -- even to the owning role. `current_setting(..., true)`
    yields no match, so `tenant_id = <nothing>` is never true."""
    _seed_tenant_with_events(pg_store, n=3)

    pg_store._conn.execute("RESET milexium.tenant_id")
    cur = pg_store._conn.execute("SELECT count(*) FROM decision_events")
    (count,) = cur.fetchone()
    pg_store._conn.commit()

    assert count == 0


def test_write_stamped_with_foreign_tenant_is_rejected_by_with_check(pg_store) -> None:
    """The WITH CHECK half of the policy: acting as tenant B, an INSERT that
    stamps a row with tenant A's id is rejected at the database layer -- a
    session cannot smuggle rows into another tenant even on the write path."""
    tenant_a, aggregate_id = _seed_tenant_with_events(pg_store, n=3)

    tenant_b = new_id(TenantId)
    _set_session_tenant(pg_store, tenant_b)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        pg_store._conn.execute(
            "INSERT INTO decision_events (event_id, tenant_id, aggregate_id, aggregate_type, "
            "sequence, occurred_at, actor_type, actor_id, event_type, payload_json, reason_codes, "
            "idempotency_key, prev_hash, hash) VALUES "
            "('rls-forged-event', %s, %s, 'ServiceRequest', 99, '2026-07-24T08:00:00+00:00', "
            "'system', 'attacker', 'recommendation', '{}', '[]', NULL, NULL, 'forged')",
            (str(tenant_a), aggregate_id),  # stamp it as tenant A while acting as B
        )
    pg_store._conn.rollback()


def test_force_row_level_security_is_load_bearing(pg_store) -> None:
    """Proves FORCE -- not ENABLE alone -- is what binds the owning role.

    `milexium_dev` owns `decision_events`; a table owner bypasses RLS by
    default. With FORCE on, acting as an empty tenant B sees zero of tenant A's
    rows. The moment FORCE is lifted (an owner-only DDL), the owner bypasses the
    policy entirely and A's rows reappear through the very same GUC=B session --
    demonstrating that a naive ENABLE-only configuration would silently fail to
    isolate the owning credential (a false green). FORCE is restored after."""
    tenant_a, _ = _seed_tenant_with_events(pg_store, n=3)
    empty_tenant_b = new_id(TenantId)
    _set_session_tenant(pg_store, empty_tenant_b)

    # FORCE is on (applied by the store): the owner is bound by the policy.
    cur = pg_store._conn.execute("SELECT count(*) FROM decision_events")
    assert cur.fetchone()[0] == 0, "FORCE RLS should hide tenant A's rows from a GUC=B session"

    # Lift FORCE: the owner now bypasses RLS and A's rows become visible again,
    # despite the session still naming tenant B. This is the false green a
    # naive ENABLE-only setup would produce against the owning role.
    pg_store._conn.execute("ALTER TABLE decision_events NO FORCE ROW LEVEL SECURITY")
    cur = pg_store._conn.execute("SELECT count(*) FROM decision_events")
    assert cur.fetchone()[0] == 3, (
        "without FORCE, the owning role bypasses RLS -- this is exactly why FORCE "
        "is required"
    )

    # Restore the guarantee and confirm the boundary is back.
    pg_store._conn.execute("ALTER TABLE decision_events FORCE ROW LEVEL SECURITY")
    cur = pg_store._conn.execute("SELECT count(*) FROM decision_events")
    assert cur.fetchone()[0] == 0
    pg_store._conn.commit()


def test_tenants_boundary_table_is_itself_scoped(pg_store) -> None:
    """The tenants table is the boundary table -- its own primary key is the
    tenant id, so its policy scopes it to itself. Acting as an unrelated tenant
    B, tenant A's registration row is invisible; acting as A, it is visible."""
    tenant_a, _ = _seed_tenant_with_events(pg_store, n=1)

    _set_session_tenant(pg_store, new_id(TenantId))
    cur = pg_store._conn.execute("SELECT count(*) FROM tenants")
    assert cur.fetchone()[0] == 0

    _set_session_tenant(pg_store, tenant_a)
    cur = pg_store._conn.execute("SELECT count(*) FROM tenants WHERE tenant_id = %s", (str(tenant_a),))
    assert cur.fetchone()[0] == 1
    pg_store._conn.commit()
