"""Runnable ten-minute adoption example (blueprint 08's quickstart intent).

Drives the whole Milexium loop in a few lines with zero external infrastructure
and clearly fictional data: create an in-memory client, ingest a few
reference-agency trip rows through an existing Connect adapter, record a
recommendation and a human override for one of the resulting requests, then
print a verified evidence packet.

The concrete adapter (`ReferenceAgencyTripsAdapter`) is imported ONLY here, in
the example -- never in the SDK core -- to prove the SDK stays decoupled from
any specific adapter. Run it from the repo root:

    py -3 -m argus.sdk.example

All data below is synthetic (the "reference agency" is fabricated); nothing
here is validated against a real operator.
"""

from __future__ import annotations

from datetime import datetime, timezone

from themis.canonical import ReasonCode, ScheduleRunId, VehicleId, new_id
from themis.connect import ReferenceAgencyTripsAdapter
from argus.sdk import MilexiumClient

# Three trips.csv-shaped rows; the middle one is malformed (hour out of range)
# so the run demonstrates quarantine rather than a silent drop.
SAMPLE_ROWS = [
    {"date": "2026-07-24", "hour": "8", "req_minute": "3", "rider_id": "rider-001",
     "origin_zone": "zone-12", "dest_zone": "zone-04", "wheelchair": "true", "purpose": "dialysis"},
    {"date": "2026-07-24", "hour": "99", "req_minute": "10", "rider_id": "rider-002",
     "origin_zone": "zone-07", "dest_zone": "zone-01", "wheelchair": "false"},
    {"date": "2026-07-24", "hour": "9", "req_minute": "15", "rider_id": "rider-003",
     "origin_zone": "zone-03", "dest_zone": "zone-09", "wheelchair": "false", "subscription": "1"},
]


def main() -> None:
    # 1. Zero-infra client: in-memory store + a fresh tenant.
    client = MilexiumClient.in_memory(tenant_name="Demo Mobility Co")

    # 2. Connect: map raw rows through an adapter the SDK knows nothing about.
    adapter = ReferenceAgencyTripsAdapter(
        client.tenant_id, recorded_at=datetime.now(timezone.utc)
    )
    summary = client.ingest(adapter, SAMPLE_ROWS)
    print(f"ingested: accepted={summary.accepted} quarantined={summary.quarantined}")
    print(f"semantic-loss notes: {len(summary.semantic_loss)}")

    # 3. Decide: record a recommendation for the first mapped request, showing
    #    one rejected alternative and the exact constraint (blueprint 08 step 6).
    request = summary.records[0]
    aggregate_id = str(request.request_id)
    schedule_run_id = new_id(ScheduleRunId)
    vehicle_a, vehicle_b = new_id(VehicleId), new_id(VehicleId)
    # Alternatives follow the evidence-packet convention (each parseable as a
    # DecisionAlternative), so the packet surfaces the rejected candidate and
    # its exact failed constraint -- blueprint 08 quickstart step 6.
    client.record_decision(
        aggregate_id=aggregate_id,
        actor_id="scheduler-v1",
        payload={
            "policy_version": "reference-agency@1",
            "recommended_vehicle_id": str(vehicle_a),
            "alternatives": [
                {"schedule_run_id": str(schedule_run_id), "request_id": str(request.request_id),
                 "candidate_vehicle_id": str(vehicle_a), "feasible": True, "objective_delta": 0.0},
                {"schedule_run_id": str(schedule_run_id), "request_id": str(request.request_id),
                 "candidate_vehicle_id": str(vehicle_b), "feasible": False,
                 "failed_constraints": [ReasonCode.NO_ACCESSIBLE_CAPACITY.value]},
            ],
        },
    )

    # 4. A dispatcher overrides the recommendation (a human act).
    client.record_override(
        aggregate_id=aggregate_id,
        actor_id="dispatcher-1",
        payload={
            "policy_version": "reference-agency@1",
            "overridden_to_vehicle_id": "veh-demo-C",
            "note": "rider requested a familiar driver",
        },
    )

    # 5. Evidence: one call yields an independently verified packet.
    packet = client.evidence_for(aggregate_id)
    print(f"integrity_verified: {packet.integrity_verified}")
    print(f"executed decision:  {packet.executed.event_type.value} "
          f"by {packet.executed.actor_type}:{packet.executed.actor_id}")
    print(f"chain_violations:   {len(packet.chain_violations)}")
    for alt in packet.alternatives_considered:
        if not alt.feasible:
            print(f"rejected alternative {alt.candidate_vehicle_id}: "
                  f"{[c.value for c in alt.failed_constraints]}")


if __name__ == "__main__":
    main()
