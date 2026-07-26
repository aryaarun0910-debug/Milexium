"""Shared fixtures for Evidence IR conformance tests (app/evidence):
realistic recommendation -> override -> outcome_recorded chains, built
through a real SqliteCanonicalStore (app.canonical.events.
HashChainAppender's SQLite-backed sibling), never hand-faked, so the
resulting hashes/sequences are exactly what production code would produce.
"""

from __future__ import annotations

from app.canonical import (
    DecisionEventType,
    Outcome,
    ReasonCode,
    RequestId,
    ScheduleRunId,
    SqliteCanonicalStore,
    TenantId,
    VehicleId,
    new_id,
)

from conformance.fixtures.builders import example_tenant, utc


def build_recommendation_override_outcome_chain() -> tuple[SqliteCanonicalStore, TenantId, str, Outcome]:
    """A full narrative: the system recommends vehicle A over two infeasible
    alternatives, a dispatcher overrides to vehicle D, and the trip's outcome
    is later recorded. Returns (store, tenant_id, aggregate_id, outcome).
    """
    store = SqliteCanonicalStore()
    tenant = example_tenant()
    store.create_tenant(tenant)
    aggregate_id = "req-evidence-0001"
    request_id = new_id(RequestId)
    schedule_run_id = new_id(ScheduleRunId)
    vehicle_a, vehicle_b, vehicle_c, vehicle_d = (new_id(VehicleId) for _ in range(4))

    store.append_event(
        tenant_id=tenant.tenant_id,
        aggregate_id=aggregate_id,
        aggregate_type="ServiceRequest",
        occurred_at=utc(2026, 7, 23, 8, 0),
        actor_type="system",
        actor_id="scheduler-v1",
        event_type=DecisionEventType.RECOMMENDATION,
        payload={
            "policy_version": "policy-42-v3",
            "recommended_vehicle_id": str(vehicle_a),
            "alternatives": [
                {
                    "schedule_run_id": str(schedule_run_id),
                    "request_id": str(request_id),
                    "candidate_vehicle_id": str(vehicle_a),
                    "feasible": True,
                    "failed_constraints": [],
                    "objective_delta": 0.0,
                },
                {
                    "schedule_run_id": str(schedule_run_id),
                    "request_id": str(request_id),
                    "candidate_vehicle_id": str(vehicle_b),
                    "feasible": False,
                    "failed_constraints": [ReasonCode.NO_ACCESSIBLE_CAPACITY.value],
                    "objective_delta": None,
                },
                {
                    "schedule_run_id": str(schedule_run_id),
                    "request_id": str(request_id),
                    "candidate_vehicle_id": str(vehicle_c),
                    "feasible": False,
                    "failed_constraints": [ReasonCode.PICKUP_WINDOW.value],
                    "objective_delta": None,
                },
            ],
        },
    )

    store.append_event(
        tenant_id=tenant.tenant_id,
        aggregate_id=aggregate_id,
        aggregate_type="ServiceRequest",
        occurred_at=utc(2026, 7, 23, 8, 5),
        actor_type="human",
        actor_id="dispatcher-7",
        event_type=DecisionEventType.OVERRIDE,
        payload={
            "policy_version": "policy-42-v3",
            "overridden_to_vehicle_id": str(vehicle_d),
            "note": "rider called ahead, requested a specific familiar driver",
        },
    )

    store.append_event(
        tenant_id=tenant.tenant_id,
        aggregate_id=aggregate_id,
        aggregate_type="ServiceRequest",
        occurred_at=utc(2026, 7, 23, 8, 45),
        actor_type="system",
        actor_id="outcome-recorder",
        event_type=DecisionEventType.OUTCOME_RECORDED,
        payload={"served": True, "on_time": True},
    )

    outcome = Outcome(
        tenant_id=tenant.tenant_id,
        request_id=request_id,
        served=True,
        actual_pickup_at=utc(2026, 7, 23, 8, 16),
        on_time=True,
        excess_ride_time_minutes=2.0,
        deadhead_minutes=4.0,
    )

    return store, tenant.tenant_id, aggregate_id, outcome


def build_recommendation_only_chain() -> tuple[SqliteCanonicalStore, TenantId, str]:
    """No override, no outcome yet -- the simplest legal chain, used to prove
    `executed` falls back to the recommendation when nothing supersedes it."""
    store = SqliteCanonicalStore()
    tenant = example_tenant()
    store.create_tenant(tenant)
    aggregate_id = "req-evidence-0002"

    store.append_event(
        tenant_id=tenant.tenant_id,
        aggregate_id=aggregate_id,
        aggregate_type="ServiceRequest",
        occurred_at=utc(2026, 7, 23, 8, 0),
        actor_type="system",
        actor_id="scheduler-v1",
        event_type=DecisionEventType.RECOMMENDATION,
        payload={"policy_version": "policy-42-v3", "recommended_vehicle_id": "vehicle-a"},
    )

    return store, tenant.tenant_id, aggregate_id
