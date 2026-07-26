"""Synthetic fixtures for Program H replay tests (v0.1).

Everything here is Demonstrated-grade synthetic data: there is no consented
operator data, so a "baseline" and a "Milexium" schedule are both fabricated
outcome sets over the same fabricated request set. This is exactly why the
comparison they feed is labelled a modelled comparison, not causal proof.
"""

from __future__ import annotations

from datetime import datetime

from themis.canonical import (
    BitemporalMeta,
    Outcome,
    RequestId,
    RequestTimes,
    ServiceRequest,
    ServiceRequestState,
    TenantId,
    new_id,
)

from conformance.fixtures.builders import example_tenant, utc


def make_request_ids(tenant_id: TenantId, n: int) -> tuple[RequestId, ...]:
    return tuple(new_id(RequestId) for _ in range(n))


def make_outcome(
    tenant_id: TenantId,
    request_id: RequestId,
    *,
    served: bool = True,
    on_time: bool | None = True,
    excess: float | None = 2.0,
    deadhead: float | None = 4.0,
    actual_pickup_at: datetime | None = None,
) -> Outcome:
    """One Outcome row. A denial (served=False) carries no served-trip metrics."""
    return Outcome(
        tenant_id=tenant_id,
        request_id=request_id,
        served=served,
        actual_pickup_at=actual_pickup_at,
        on_time=on_time if served else None,
        excess_ride_time_minutes=excess if served else None,
        deadhead_minutes=deadhead,
    )


def make_request_with_actual_pickup(
    tenant_id: TenantId,
    actual_pickup_at: datetime,
    *,
    request_id: RequestId | None = None,
    scheduled_pickup_at: datetime | None = None,
) -> ServiceRequest:
    """A completed request whose actual pickup is a fact only known after it
    happened -- used to prove replay hides it before the replay instant."""
    return ServiceRequest(
        request_id=request_id or new_id(RequestId),
        tenant_id=tenant_id,
        rider_ref="rider-token-replay",
        pickup_zone="zone-12",
        dropoff_zone="zone-04",
        mobility_device=None,
        times=RequestTimes(
            requested_at=utc(2026, 7, 23, 8, 0),
            scheduled_pickup_at=scheduled_pickup_at or utc(2026, 7, 23, 8, 15),
            actual_pickup_at=actual_pickup_at,
        ),
        status=ServiceRequestState.REQUESTED,
        meta=BitemporalMeta(version=1, recorded_at=utc(2026, 7, 23, 8, 0, 5)),
    )
