"""SDK facade conformance (Program M, v0.1 slice): the happy path of the
MilexiumClient facade -- in-memory setup, ingest through a Connect adapter,
record a recommendation and a human override, and reconstruct a verified
evidence packet in one call. The concrete adapter is imported here (a test),
never in the SDK core. Tamper/integrity-failure cases live in
aletheia/conformance/property-tests/test_sdk_loop.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

from themis.canonical import DecisionEventType, ServiceRequest, TenantId
from themis.connect import ReferenceAgencyTripsAdapter
from argus.sdk import MilexiumClient

_ROWS = [
    {"date": "2026-07-24", "hour": "8", "req_minute": "3", "rider_id": "rider-001",
     "origin_zone": "zone-12", "dest_zone": "zone-04", "wheelchair": "true", "purpose": "dialysis"},
    {"date": "2026-07-24", "hour": "99", "req_minute": "10", "rider_id": "rider-002",
     "origin_zone": "zone-07", "dest_zone": "zone-01", "wheelchair": "false"},  # hour out of range
    {"date": "2026-07-24", "hour": "9", "req_minute": "15", "rider_id": "rider-003",
     "origin_zone": "zone-03", "dest_zone": "zone-09", "wheelchair": "false"},
]


def _adapter(client: MilexiumClient) -> ReferenceAgencyTripsAdapter:
    return ReferenceAgencyTripsAdapter(client.tenant_id, recorded_at=datetime.now(timezone.utc))


def test_in_memory_creates_a_ready_client_with_a_tenant() -> None:
    client = MilexiumClient.in_memory(tenant_name="Demo Mobility Co")
    assert isinstance(client.tenant_id, TenantId)
    # The tenant really exists in the wrapped store: an aggregate read is
    # tenant-scoped and simply returns nothing rather than erroring.
    assert client.store.history(client.tenant_id, "no-such-aggregate") == ()


def test_ingest_summarizes_accepted_quarantined_and_semantic_loss() -> None:
    client = MilexiumClient.in_memory(tenant_name="Demo Mobility Co")
    summary = client.ingest(_adapter(client), _ROWS)

    assert summary.accepted == 2
    assert summary.quarantined == 1
    assert len(summary.records) == 2
    assert all(isinstance(r, ServiceRequest) for r in summary.records)
    assert len(summary.quarantined_rows) == 1
    # Every mapped reference-agency row emits at least the time-coercion note.
    assert len(summary.semantic_loss) >= 2


def test_record_decision_and_override_append_typed_events() -> None:
    client = MilexiumClient.in_memory(tenant_name="Demo Mobility Co")
    summary = client.ingest(_adapter(client), _ROWS)
    aggregate_id = str(summary.records[0].request_id)

    recommendation = client.record_decision(
        aggregate_id=aggregate_id,
        actor_id="scheduler-v1",
        payload={"recommended_vehicle_id": "veh-A"},
    )
    override = client.record_override(
        aggregate_id=aggregate_id,
        actor_id="dispatcher-7",
        payload={"overridden_to_vehicle_id": "veh-C", "note": "familiar driver"},
    )

    assert recommendation.event_type == DecisionEventType.RECOMMENDATION
    assert recommendation.actor_type == "system"
    assert override.event_type == DecisionEventType.OVERRIDE
    assert override.actor_type == "human"
    assert override.sequence == recommendation.sequence + 1


def test_evidence_for_returns_a_verified_packet() -> None:
    client = MilexiumClient.in_memory(tenant_name="Demo Mobility Co")
    summary = client.ingest(_adapter(client), _ROWS)
    aggregate_id = str(summary.records[0].request_id)

    client.record_decision(
        aggregate_id=aggregate_id, actor_id="scheduler-v1",
        payload={"recommended_vehicle_id": "veh-A"},
    )
    client.record_override(
        aggregate_id=aggregate_id, actor_id="dispatcher-7",
        payload={"overridden_to_vehicle_id": "veh-C"},
    )

    packet = client.evidence_for(aggregate_id)
    assert packet.integrity_verified is True
    assert packet.chain_violations == ()
    assert len(packet.known_inputs) == 1
    assert packet.executed is not None
    assert packet.executed.event_type == DecisionEventType.OVERRIDE
    assert packet.observed is None
    # The independent verifier agrees the aggregate's chain is intact.
    assert client.verify(aggregate_id) == ()
