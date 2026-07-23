"""Full-loop SDK property tests (Program M, v0.1 slice).

Proves the composed loop the facade exposes -- ingest -> record decision ->
override -> evidence -- produces an independently verified EvidencePacket, and
that a tampered chain surfaces `integrity_verified=False` *through the SDK*,
not only through the underlying verifier. The tamper uses the same
`SqliteCanonicalStore.tamper_with_row` escape hatch as
conformance/adversarial/test_tamper_and_isolation.py, reached via the client's
`.store` property -- the SDK is not patched or weakened to make either case pass.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from packages.connect import ReferenceAgencyTripsAdapter
from packages.sdk import MilexiumClient
from packages.sdk.example import main as run_example

_ROWS = [
    {"date": "2026-07-24", "hour": "8", "req_minute": "3", "rider_id": "rider-001",
     "origin_zone": "zone-12", "dest_zone": "zone-04", "wheelchair": "true"},
    {"date": "2026-07-24", "hour": "9", "req_minute": "15", "rider_id": "rider-003",
     "origin_zone": "zone-03", "dest_zone": "zone-09", "wheelchair": "false"},
]


def _driven_client() -> tuple[MilexiumClient, str]:
    """Run the whole loop and return (client, aggregate_id)."""
    client = MilexiumClient.in_memory(tenant_name="Loop Co")
    adapter = ReferenceAgencyTripsAdapter(client.tenant_id, recorded_at=datetime.now(timezone.utc))
    summary = client.ingest(adapter, _ROWS)
    aggregate_id = str(summary.records[0].request_id)
    client.record_decision(
        aggregate_id=aggregate_id, actor_id="scheduler-v1",
        payload={"policy_version": "reference-agency@1", "recommended_vehicle_id": "veh-A"},
    )
    client.record_override(
        aggregate_id=aggregate_id, actor_id="dispatcher-7",
        payload={"policy_version": "reference-agency@1", "overridden_to_vehicle_id": "veh-C"},
    )
    return client, aggregate_id


def test_full_loop_produces_a_verified_evidence_packet() -> None:
    client, aggregate_id = _driven_client()
    packet = client.evidence_for(aggregate_id)

    assert packet.integrity_verified is True
    assert packet.chain_violations == ()
    assert packet.schema_violations == ()
    assert client.verify(aggregate_id) == ()


def test_tampered_chain_surfaces_integrity_false_through_the_sdk() -> None:
    client, aggregate_id = _driven_client()

    # Attack: rewrite a recorded event's payload after the fact without
    # recomputing its hash, reaching the store through the SDK's own escape
    # hatch -- exactly the threat the evidence packet must not hide.
    recorded = client.store.history(client.tenant_id, aggregate_id)
    client.store.tamper_with_row(recorded[0].event_id, payload_json='{"tampered": true}')

    packet = client.evidence_for(aggregate_id)
    assert packet.integrity_verified is False
    assert len(packet.chain_violations) >= 1
    # The lighter direct verifier surfaces it too.
    violations = client.verify(aggregate_id)
    assert any(v.kind == "hash_mismatch" for v in violations)


def test_evidence_for_rejects_an_unknown_aggregate() -> None:
    client = MilexiumClient.in_memory(tenant_name="Loop Co")
    with pytest.raises(ValueError):
        client.evidence_for("never-recorded-anything")


def test_example_script_runs_end_to_end() -> None:
    # blueprint 08: "Examples must run as tests." Executes the shipped
    # quickstart top to bottom; a raised exception fails the test.
    run_example()
