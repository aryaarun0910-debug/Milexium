"""Adversarial fixtures for `PostgresCanonicalStore` -- the same tampering
and cross-tenant-isolation properties already proven against
`SqliteCanonicalStore` in
`evidence/conformance/adversarial/test_tamper_and_isolation.py`, now proven against
the real PostgreSQL 17 instance. These tests only ever call into
`app.canonical.postgres_storage` and `app.verify`, never patch or
weaken them to make a scenario pass.

Skips cleanly (not a failure) if PostgreSQL is unreachable, so this suite
stays green on a machine where `milexium_dev` was never provisioned.
"""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg
import pytest

from app.canonical import DecisionEventType, TenantId, new_id
from app.canonical.postgres_storage import PostgresCanonicalStore, is_reachable
from app.verify import verify_chain

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


def _seed(store: PostgresCanonicalStore) -> tuple[TenantId, str]:
    tenant = example_tenant()
    store.create_tenant(tenant)
    aggregate_id = "req-tamper-0001"
    for i in range(3):
        store.append_event(
            tenant_id=tenant.tenant_id,
            aggregate_id=aggregate_id,
            aggregate_type="ServiceRequest",
            occurred_at=_utc(2026, 7, 23, 8, i),
            actor_type="system",
            actor_id="scheduler",
            event_type=DecisionEventType.RECOMMENDATION,
            payload={"i": i},
        )
    return tenant.tenant_id, aggregate_id


def test_verifier_detects_payload_tampering(pg_store) -> None:
    tenant_id, aggregate_id = _seed(pg_store)
    history = pg_store.history(tenant_id, aggregate_id)
    target_event_id = history[1].event_id

    # Attack: modify a stored payload after the fact (e.g. a compromised
    # credential rewriting an inconvenient recommendation) without
    # recomputing the hash -- exactly the threat model in
    # blueprint/10-security-privacy-and-ai-governance.md ("Replay or
    # evidence manipulation").
    pg_store.tamper_with_row(target_event_id, payload_json='{"i": 999}')

    violations = verify_chain(pg_store.raw_rows_for_tenant(tenant_id))
    assert any(v.kind == "hash_mismatch" for v in violations)


def test_verifier_detects_a_deleted_middle_event_as_a_gap(pg_store) -> None:
    tenant_id, aggregate_id = _seed(pg_store)
    history = pg_store.history(tenant_id, aggregate_id)
    middle_event_id = history[1].event_id

    pg_store._conn.execute("DELETE FROM decision_events WHERE event_id = %s", (middle_event_id,))
    pg_store._conn.commit()

    violations = verify_chain(pg_store.raw_rows_for_tenant(tenant_id))
    kinds = {v.kind for v in violations}
    assert "sequence_gap" in kinds or "prev_hash_mismatch" in kinds


def test_verifier_detects_hash_forged_to_match_tampered_payload(pg_store) -> None:
    """A more sophisticated attacker recomputes *a* hash after tampering, but
    if they don't also chain-update every downstream event's prev_hash, the
    verifier still catches the break -- this proves the chain, not just a
    single hash, is what is being checked."""
    tenant_id, aggregate_id = _seed(pg_store)
    history = pg_store.history(tenant_id, aggregate_id)
    target = history[1]

    from app.canonical.events import compute_hash

    forged_payload = {"i": 999}
    forged_hash = compute_hash(target.prev_hash, forged_payload, target.sequence, aggregate_id)
    pg_store.tamper_with_row(target.event_id, payload_json='{"i": 999}', hash=forged_hash)

    violations = verify_chain(pg_store.raw_rows_for_tenant(tenant_id))
    # The forged event's own hash now matches its (tampered) payload, but the
    # *next* event's prev_hash was computed against the original hash, so the
    # chain link breaks there.
    assert any(v.kind == "prev_hash_mismatch" for v in violations)


def test_cross_tenant_history_read_returns_nothing(pg_store) -> None:
    tenant_id, aggregate_id = _seed(pg_store)
    other_tenant = new_id(TenantId)

    # Attack: a second tenant (or a compromised query missing its WHERE
    # clause upstream) asks for the same aggregate_id -- collisions are
    # plausible because aggregate_id is caller-chosen, not globally unique
    # across tenants by construction.
    result = pg_store.history(other_tenant, aggregate_id)
    assert result == ()


def test_cross_tenant_raw_rows_are_disjoint(pg_store) -> None:
    tenant_id, aggregate_id = _seed(pg_store)
    other_tenant = example_tenant()
    pg_store.create_tenant(other_tenant)
    pg_store.append_event(
        tenant_id=other_tenant.tenant_id,
        aggregate_id=aggregate_id,  # same aggregate_id, different tenant
        aggregate_type="ServiceRequest",
        occurred_at=_utc(2026, 7, 23, 9, 0),
        actor_type="system",
        actor_id="scheduler",
        event_type=DecisionEventType.RECOMMENDATION,
        payload={"i": "other-tenant-event"},
    )

    rows_a = pg_store.raw_rows_for_tenant(tenant_id)
    rows_b = pg_store.raw_rows_for_tenant(other_tenant.tenant_id)
    assert len(rows_a) == 3
    assert len(rows_b) == 1
    assert {r["event_id"] for r in rows_a}.isdisjoint({r["event_id"] for r in rows_b})


def test_duplicate_sequence_is_rejected_by_the_database_constraint(pg_store) -> None:
    """Defense in depth: even if application logic had a bug and tried to
    insert a second event at an already-used sequence, the UNIQUE constraint
    in schema_v0_1.sql rejects it at the database layer."""
    tenant_id, aggregate_id = _seed(pg_store)
    with pytest.raises(psycopg.errors.UniqueViolation):
        pg_store._conn.execute(
            "INSERT INTO decision_events (event_id, tenant_id, aggregate_id, aggregate_type, "
            "sequence, occurred_at, actor_type, actor_id, event_type, payload_json, reason_codes, "
            "idempotency_key, prev_hash, hash) VALUES "
            "('forged-event-id', %s, %s, 'ServiceRequest', 1, '2026-07-23T08:00:00+00:00', "
            "'system', 'attacker', 'recommendation', '{}', '[]', NULL, NULL, 'forged')",
            (str(tenant_id), aggregate_id),
        )
    pg_store._conn.rollback()
