"""Extended integrity-check conformance for Evidence IR (Program I follow-up
slice, see architecture/decisions/0009-evidence-ir-v0-1-conventions.md's
"Consequences"): proves integrity_verified aggregates all three independent
checks -- hash-chain (verify_chain), schema (verify_against_schema), and
state-transition (verify_state_sequence) -- rather than only the hash chain,
and that each check's own violation list stays independent of the others.
The schema-tamper case (a DecisionEvent built via a path that bypasses normal
Pydantic construction) lives in
conformance/adversarial/test_evidence_schema_tamper.py; this file covers the
happy path and combined-failure aggregation.
"""

from __future__ import annotations

from packages.canonical.entities import DecisionEvent
from packages.evidence import build_evidence_packet

from conformance.fixtures.evidence_builders import (
    build_recommendation_only_chain,
    build_recommendation_override_outcome_chain,
)


def _malformed_actor_type_clone(valid: DecisionEvent) -> DecisionEvent:
    """model_construct bypasses __init__ validation entirely -- the only way
    to produce a DecisionEvent whose actor_type fails its own pattern, since
    every real construction path in this repository (HashChainAppender,
    SqliteCanonicalStore.append_event/history) validates via DecisionEvent(...)."""
    return DecisionEvent.model_construct(
        event_id=valid.event_id,
        tenant_id=valid.tenant_id,
        aggregate_id=valid.aggregate_id,
        aggregate_type=valid.aggregate_type,
        sequence=valid.sequence,
        occurred_at=valid.occurred_at,
        actor_type="not-system-or-human",
        actor_id=valid.actor_id,
        event_type=valid.event_type,
        payload=valid.payload,
        reason_codes=valid.reason_codes,
        idempotency_key=valid.idempotency_key,
        prev_hash=valid.prev_hash,
        hash=valid.hash,
    )


def test_clean_chain_passes_schema_check_and_leaves_state_check_inapplicable() -> None:
    """The state-transition check has nothing to run against for a typical
    DecisionEvent chain -- DecisionEvent payloads carry no recorded
    ServiceRequestState by any convention this repository has established --
    so it must honestly report itself as not applicable rather than silently
    "passing"."""
    store, tenant_id, aggregate_id, outcome = build_recommendation_override_outcome_chain()
    events = store.history(tenant_id, aggregate_id)
    raw_rows = store.raw_rows_for_tenant(tenant_id)

    packet = build_evidence_packet(events, raw_rows, outcome=outcome)

    assert packet.chain_violations == ()
    assert packet.schema_violations == ()
    assert packet.state_check_applicable is False
    assert packet.state_violations == ()
    assert packet.integrity_verified is True


def test_schema_violation_alone_flips_integrity_verified_without_a_chain_violation() -> None:
    """A schema-invalid event with an untouched, hash-consistent raw chain
    proves the schema check is independent of (not a proxy for) the hash
    chain check -- integrity_verified must go False on the schema check alone."""
    store, tenant_id, aggregate_id = build_recommendation_only_chain()
    events = store.history(tenant_id, aggregate_id)
    raw_rows = store.raw_rows_for_tenant(tenant_id)
    malformed = _malformed_actor_type_clone(events[0])

    packet = build_evidence_packet((malformed,), raw_rows)

    assert packet.chain_violations == ()
    assert packet.schema_violations != ()
    assert any("actor_type" in violation for violation in packet.schema_violations)
    assert packet.integrity_verified is False


def test_chain_violation_and_schema_violation_both_surface_independently() -> None:
    """A packet with both a tampered hash chain and a schema-invalid event
    must report both violation kinds, not just whichever check runs first --
    proving the aggregation genuinely combines independent results rather
    than short-circuiting on the first failure it finds."""
    store, tenant_id, aggregate_id, outcome = build_recommendation_override_outcome_chain()
    history = store.history(tenant_id, aggregate_id)
    store.tamper_with_row(history[0].event_id, payload_json='{"recommended_vehicle_id": "attacker-installed"}')

    events = store.history(tenant_id, aggregate_id)
    raw_rows = store.raw_rows_for_tenant(tenant_id)
    malformed_last = _malformed_actor_type_clone(events[-1])
    tampered_events = events[:-1] + (malformed_last,)

    packet = build_evidence_packet(tampered_events, raw_rows, outcome=outcome)

    assert packet.chain_violations != ()
    assert any(v.kind == "hash_mismatch" for v in packet.chain_violations)
    assert packet.schema_violations != ()
    assert packet.integrity_verified is False
