"""Evidence IR / Experience IR conformance (Program I, v0.1 slice):
proves build_evidence_packet faithfully reconstructs the full narrative --
what was known, proposed, verified, approved/overridden, executed, and
observed -- from a real recommendation -> override -> outcome_recorded
chain, and that build_experience_packet derives a correct, guarded precedent
record from it. Tampering/integrity-failure cases live in
conformance/adversarial/test_evidence_tamper.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from packages.canonical import DecisionEventType, Outcome, ReasonCode
from packages.evidence import build_evidence_packet, build_experience_packet

from conformance.fixtures.evidence_builders import (
    build_recommendation_only_chain,
    build_recommendation_override_outcome_chain,
)


def test_evidence_packet_captures_the_full_narrative() -> None:
    store, tenant_id, aggregate_id, outcome = build_recommendation_override_outcome_chain()
    events = store.history(tenant_id, aggregate_id)
    raw_rows = store.raw_rows_for_tenant(tenant_id)

    packet = build_evidence_packet(events, raw_rows, outcome=outcome)

    # what was known
    assert len(packet.known_inputs) == 1
    assert packet.known_inputs[0].payload["recommended_vehicle_id"] == events[0].payload["recommended_vehicle_id"]

    # what was proposed
    assert [e.event_type for e in packet.proposed] == [DecisionEventType.RECOMMENDATION]
    assert len(packet.alternatives_considered) == 3
    feasible_flags = {alt.candidate_vehicle_id: alt.feasible for alt in packet.alternatives_considered}
    assert sum(feasible_flags.values()) == 1  # exactly one feasible candidate
    infeasible = [alt for alt in packet.alternatives_considered if not alt.feasible]
    assert {code for alt in infeasible for code in alt.failed_constraints} == {
        ReasonCode.NO_ACCESSIBLE_CAPACITY,
        ReasonCode.PICKUP_WINDOW,
    }

    # what was approved or overridden
    assert len(packet.approved_or_overridden) == 1
    override_event = packet.approved_or_overridden[0]
    assert override_event.actor_type == "human"
    assert override_event.actor_id == "dispatcher-7"
    assert "note" in override_event.payload

    # what was executed -- the override supersedes the recommendation
    assert packet.executed is not None
    assert packet.executed.event_id == override_event.event_id

    # what was observed
    assert len(packet.outcome_events) == 1
    assert packet.observed == outcome

    # what was verified -- a real, untampered chain
    assert packet.integrity_verified is True
    assert packet.chain_violations == ()


def test_evidence_packet_without_override_falls_back_to_the_recommendation() -> None:
    store, tenant_id, aggregate_id = build_recommendation_only_chain()
    events = store.history(tenant_id, aggregate_id)
    raw_rows = store.raw_rows_for_tenant(tenant_id)

    packet = build_evidence_packet(events, raw_rows)

    assert packet.approved_or_overridden == ()
    assert packet.executed is not None
    assert packet.executed.event_type == DecisionEventType.RECOMMENDATION
    assert packet.observed is None
    assert packet.integrity_verified is True


def test_evidence_packet_is_a_pure_function_of_its_inputs() -> None:
    store, tenant_id, aggregate_id, outcome = build_recommendation_override_outcome_chain()
    events = store.history(tenant_id, aggregate_id)
    raw_rows = store.raw_rows_for_tenant(tenant_id)

    first = build_evidence_packet(events, raw_rows, outcome=outcome)
    second = build_evidence_packet(events, raw_rows, outcome=outcome)
    assert first == second


def test_evidence_packet_ignores_violations_in_other_aggregates_raw_rows() -> None:
    """raw_rows may legitimately be a whole tenant's rows (e.g.
    raw_rows_for_tenant); a corruption in an unrelated aggregate elsewhere in
    the same tenant must not leak into this packet's chain_violations --
    proves build_evidence_packet actually filters by aggregate_id before
    verifying, rather than just happening to see a clean tenant in the other
    tests."""
    store, tenant_id, aggregate_id, outcome = build_recommendation_override_outcome_chain()
    other_aggregate_id = "req-some-other-aggregate"
    other_event = store.append_event(
        tenant_id=tenant_id,
        aggregate_id=other_aggregate_id,
        aggregate_type="ServiceRequest",
        occurred_at=datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc),
        actor_type="system",
        actor_id="scheduler-v1",
        event_type=DecisionEventType.RECOMMENDATION,
        payload={"unrelated": True},
    )
    store.tamper_with_row(other_event.event_id, payload_json='{"unrelated": "tampered"}')

    events = store.history(tenant_id, aggregate_id)
    raw_rows = store.raw_rows_for_tenant(tenant_id)
    assert any(row["aggregate_id"] == other_aggregate_id for row in raw_rows)

    packet = build_evidence_packet(events, raw_rows, outcome=outcome)
    assert packet.integrity_verified is True
    assert packet.chain_violations == ()


def test_build_evidence_packet_rejects_empty_history() -> None:
    with pytest.raises(ValueError):
        build_evidence_packet((), [])


def test_build_evidence_packet_rejects_events_from_different_aggregates() -> None:
    store, tenant_id, aggregate_id, outcome = build_recommendation_override_outcome_chain()
    other_store, other_tenant_id, other_aggregate_id = build_recommendation_only_chain()

    mixed = store.history(tenant_id, aggregate_id) + other_store.history(other_tenant_id, other_aggregate_id)
    with pytest.raises(ValueError):
        build_evidence_packet(mixed, [])


def test_experience_packet_derives_a_compact_precedent_record() -> None:
    store, tenant_id, aggregate_id, outcome = build_recommendation_override_outcome_chain()
    events = store.history(tenant_id, aggregate_id)
    raw_rows = store.raw_rows_for_tenant(tenant_id)
    packet = build_evidence_packet(events, raw_rows, outcome=outcome)

    experience = build_experience_packet(packet, outcome)

    assert experience.tenant_id == tenant_id
    assert experience.aggregate_id == aggregate_id
    assert experience.situation_features == packet.known_inputs[0].payload
    assert experience.decision_event_id == packet.executed.event_id
    assert experience.decision_type == DecisionEventType.OVERRIDE
    assert experience.decision_actor_id == "dispatcher-7"
    assert experience.outcome == outcome
    assert experience.policy_version == "policy-42-v3"


def test_experience_packet_rejects_an_outcome_that_disagrees_with_the_packet() -> None:
    store, tenant_id, aggregate_id, outcome = build_recommendation_override_outcome_chain()
    events = store.history(tenant_id, aggregate_id)
    raw_rows = store.raw_rows_for_tenant(tenant_id)
    packet = build_evidence_packet(events, raw_rows, outcome=outcome)

    conflicting_outcome = Outcome(
        tenant_id=tenant_id,
        request_id=outcome.request_id,
        served=False,
    )
    with pytest.raises(ValueError):
        build_experience_packet(packet, conflicting_outcome)


def test_experience_packet_requires_an_executed_decision() -> None:
    store, tenant_id, aggregate_id, outcome = build_recommendation_override_outcome_chain()
    events = store.history(tenant_id, aggregate_id)
    raw_rows = store.raw_rows_for_tenant(tenant_id)
    packet = build_evidence_packet(events, raw_rows, outcome=outcome)
    empty_packet = packet.model_copy(update={"executed": None})

    with pytest.raises(ValueError):
        build_experience_packet(empty_packet, outcome)
