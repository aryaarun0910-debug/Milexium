"""Property tests for the append-only hash-chained event log, run against
*both* implementations of the same contract (the in-memory
`HashChainAppender` and the SQLite-backed `SqliteCanonicalStore`) so neither
one is trusted by construction -- this is the "behavior dependency"
(executable conformance fixtures) the expansion plan's dependency rules
describe.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from themis.canonical import DecisionEventType, HashChainAppender, SqliteCanonicalStore, TenantId, new_id
from themis.canonical.events import DuplicateEventError
from aletheia.verify import verify_chain

from conformance.fixtures.builders import example_tenant


def _utc(*args, **kwargs) -> datetime:
    return datetime(*args, tzinfo=timezone.utc, **kwargs)


class _InMemoryAdapter:
    """Adapts HashChainAppender to look like SqliteCanonicalStore for the
    parametrized tests below, so both backends run the identical assertions."""

    def __init__(self) -> None:
        self._appender = HashChainAppender()

    def append_event(self, **kwargs):
        return self._appender.append(**kwargs)

    def history(self, tenant_id, aggregate_id):
        return self._appender.history(tenant_id, aggregate_id)

    def raw_rows_for_tenant(self, tenant_id):
        rows = []
        for (t, agg), events in self._appender._chains.items():  # test-only introspection
            if t != tenant_id:
                continue
            for e in events:
                rows.append(
                    {
                        "aggregate_id": e.aggregate_id,
                        "sequence": e.sequence,
                        "prev_hash": e.prev_hash,
                        "hash": e.hash,
                        "idempotency_key": e.idempotency_key,
                        "payload_json": __import__("json").dumps(e.payload),
                    }
                )
        return rows


def _backends():
    store = SqliteCanonicalStore()
    tenant = example_tenant()
    store.create_tenant(tenant)
    yield "sqlite", store, tenant.tenant_id

    memory = _InMemoryAdapter()
    yield "memory", memory, new_id(TenantId)


@pytest.mark.parametrize("name,backend,tenant_id", list(_backends()))
def test_sequence_is_gapless_and_starts_at_one(name, backend, tenant_id) -> None:
    aggregate_id = "req-0001"
    for i in range(3):
        event = backend.append_event(
            tenant_id=tenant_id,
            aggregate_id=aggregate_id,
            aggregate_type="ServiceRequest",
            occurred_at=_utc(2026, 7, 23, 8, i),
            actor_type="system",
            actor_id="scheduler",
            event_type=DecisionEventType.RECOMMENDATION,
            payload={"i": i},
        )
        assert event.sequence == i + 1
    history = backend.history(tenant_id, aggregate_id)
    assert [e.sequence for e in history] == [1, 2, 3]
    assert history[0].prev_hash is None
    assert history[1].prev_hash == history[0].hash
    assert history[2].prev_hash == history[1].hash


@pytest.mark.parametrize("name,backend,tenant_id", list(_backends()))
def test_idempotency_key_replay_returns_same_event_not_a_new_one(name, backend, tenant_id) -> None:
    aggregate_id = "req-0002"
    kwargs = dict(
        tenant_id=tenant_id,
        aggregate_id=aggregate_id,
        aggregate_type="ServiceRequest",
        occurred_at=_utc(2026, 7, 23, 9, 0),
        actor_type="human",
        actor_id="dispatcher-1",
        event_type=DecisionEventType.OVERRIDE,
        payload={"override_reason": "family request"},
        idempotency_key="override-cmd-abc123",
    )
    first = backend.append_event(**kwargs)
    second = backend.append_event(**kwargs)
    assert first.event_id == second.event_id
    assert len(backend.history(tenant_id, aggregate_id)) == 1


@pytest.mark.parametrize("name,backend,tenant_id", list(_backends()))
def test_idempotency_key_reuse_with_different_payload_is_rejected(name, backend, tenant_id) -> None:
    aggregate_id = "req-0003"
    backend.append_event(
        tenant_id=tenant_id,
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
        backend.append_event(
            tenant_id=tenant_id,
            aggregate_id=aggregate_id,
            aggregate_type="ServiceRequest",
            occurred_at=_utc(2026, 7, 23, 9, 0),
            actor_type="human",
            actor_id="dispatcher-1",
            event_type=DecisionEventType.OVERRIDE,
            payload={"override_reason": "DIFFERENT reason"},
            idempotency_key="override-cmd-xyz",
        )


@pytest.mark.parametrize("name,backend,tenant_id", list(_backends()))
def test_verifier_accepts_an_untampered_chain(name, backend, tenant_id) -> None:
    aggregate_id = "req-0004"
    for i in range(4):
        backend.append_event(
            tenant_id=tenant_id,
            aggregate_id=aggregate_id,
            aggregate_type="ServiceRequest",
            occurred_at=_utc(2026, 7, 23, 8, i),
            actor_type="system",
            actor_id="scheduler",
            event_type=DecisionEventType.RECOMMENDATION,
            payload={"i": i},
        )
    violations = verify_chain(backend.raw_rows_for_tenant(tenant_id))
    assert violations == []
