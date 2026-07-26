"""Shared example builders for the canonical contract v0.1.

These are the fixtures referenced by knowledge/architecture/decisions/0001 and
blueprint/19-agent-swarm-execution-system.md's "fixtures" requirement: every
other implementation of Program A (a future PostgreSQL store, a TypeScript
client, etc.) should be able to construct the same logical examples and get
byte-identical canonical JSON / hashes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.canonical import (
    BitemporalMeta,
    DecisionEventType,
    RequestId,
    RequestTimes,
    ServiceRequest,
    ServiceRequestState,
    Tenant,
    TenantId,
    new_id,
)


def utc(*args, **kwargs) -> datetime:
    return datetime(*args, tzinfo=timezone.utc, **kwargs)


def example_tenant() -> Tenant:
    return Tenant(
        tenant_id=new_id(TenantId),
        name="Harland County Mobility",
        created_at=utc(2026, 1, 1),
    )


def example_service_request(
    tenant_id: TenantId,
    *,
    request_id: RequestId | None = None,
    status: ServiceRequestState = ServiceRequestState.REQUESTED,
    version: int = 1,
    corrects_version: int | None = None,
) -> ServiceRequest:
    return ServiceRequest(
        request_id=request_id or new_id(RequestId),
        tenant_id=tenant_id,
        rider_ref="rider-token-0001",
        pickup_zone="zone-12",
        dropoff_zone="zone-04",
        mobility_device="wheelchair",
        times=RequestTimes(requested_at=utc(2026, 7, 23, 8, 0)),
        status=status,
        meta=BitemporalMeta(
            version=version,
            recorded_at=utc(2026, 7, 23, 8, 0, 5),
            corrects_version=corrects_version,
        ),
    )


EXAMPLE_DECISION_PAYLOAD = {
    "candidate_vehicle_id": None,
    "note": "no accessible vehicle available in the negotiated window",
}

EXAMPLE_EVENT_TYPE = DecisionEventType.REJECTION
