"""Property tests for the append-only hash-chained event log, run against
`PostgresCanonicalStore` -- the same contract already exercised in
`conformance/property-tests/test_event_log_properties.py` against
`HashChainAppender` and `SqliteCanonicalStore`, now proven against the real
PostgreSQL 17 instance (architecture/decisions/0004-sqlite-now-postgres-production.md,
architecture/decisions/0006-dedicated-postgres-dev-role.md).

Skips cleanly (not a failure) if PostgreSQL is unreachable, so this suite
stays green on a machine where `milexium_dev` was never provisioned.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from packages.canonical import DecisionEventType, TenantId, new_id
from packages.canonical.events import DuplicateEventError
from packages.canonical.postgres_storage import PostgresCanonicalStore, is_reachable
from packages.verify import verify_chain

from conformance.fixtures.builders import example_tenant

if not is_reachable():
    pytest.skip(
        "PostgreSQL (milexium_dev) is not reachable on this machine; "
        "skipping Postgres conformance tests",
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


def test_sequence_is_gapless_and_starts_at_one(pg_store) -> None:
    tenant = example_tenant()
    pg_store.create_tenant(tenant)
    aggregate_id = "req-0001"
    for i in range(3):
        event = pg_store.append_event(
            tenant_id=tenant.tenant_id,
            aggregate_id=aggregate_id,
            aggregate_type="ServiceRequest",
            occurred_at=_utc(2026, 7, 23, 8, i),
            actor_type="system",
            actor_id="scheduler",
            event_type=DecisionEventType.RECOMMENDATION,
            payload={"i": i},
        )
        assert event.sequence == i + 1
    history = pg_store.history(tenant.tenant_id, aggregate_id)
    assert [e.sequence for e in history] == [1, 2, 3]
    assert history[0].prev_hash is None
    assert history[1].prev_hash == history[0].hash
    assert history[2].prev_hash == history[1].hash


def test_idempotency_key_replay_returns_same_event_not_a_new_one(pg_store) -> None:
    tenant = example_tenant()
    pg_store.create_tenant(tenant)
    aggregate_id = "req-0002"
    kwargs = dict(
        tenant_id=tenant.tenant_id,
        aggregate_id=aggregate_id,
        aggregate_type="ServiceRequest",
        occurred_at=_utc(2026, 7, 23, 9, 0),
        actor_type="human",
        actor_id="dispatcher-1",
        event_type=DecisionEventType.OVERRIDE,
        payload={"override_reason": "family request"},
        idempotency_key="override-cmd-abc123",
    )
    first = pg_store.append_event(**kwargs)
    second = pg_store.append_event(**kwargs)
    assert first.event_id == second.event_id
    assert len(pg_store.history(tenant.tenant_id, aggregate_id)) == 1


def test_idempotency_key_reuse_with_different_payload_is_rejected(pg_store) -> None:
    tenant = example_tenant()
    pg_store.create_tenant(tenant)
    aggregate_id = "req-0003"
    pg_store.append_event(
        tenant_id=tenant.tenant_id,
        aggregate_id=aggregate_id,
        aggregate_type="ServiceRequest",
        occurred_at=_utc(2026, 7, 23, 9, 0),
        actor_type="human",
        actor_id="dispatcher-1",
        event_type=DecisionEventType.OVERRIDE,
        payload={"override_reason": "family request"},
        idempotency_key="override-cmd-xyz",
    )
    with pytest.raises(DuplicateEventError):
        pg_store.append_event(
            tenant_id=tenant.tenant_id,
            aggregate_id=aggregate_id,
            aggregate_type="ServiceRequest",
            occurred_at=_utc(2026, 7, 23, 9, 0),
            actor_type="human",
            actor_id="dispatcher-1",
            event_type=DecisionEventType.OVERRIDE,
            payload={"override_reason": "DIFFERENT reason"},
            idempotency_key="override-cmd-xyz",
        )


def test_verifier_accepts_an_untampered_chain(pg_store) -> None:
    tenant = example_tenant()
    pg_store.create_tenant(tenant)
    aggregate_id = "req-0004"
    for i in range(4):
        pg_store.append_event(
            tenant_id=tenant.tenant_id,
            aggregate_id=aggregate_id,
            aggregate_type="ServiceRequest",
            occurred_at=_utc(2026, 7, 23, 8, i),
            actor_type="system",
            actor_id="scheduler",
            event_type=DecisionEventType.RECOMMENDATION,
            payload={"i": i},
        )
    violations = verify_chain(pg_store.raw_rows_for_tenant(tenant.tenant_id))
    assert violations == []
