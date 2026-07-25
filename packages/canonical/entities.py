"""Canonical entities (Program A contract, v0.1).

These mirror the minimum tables in docs/MASTER_ROADMAP.md ("MilexiumDB: the
operational evidence data plane") exactly, so the same contract serves both
the YC-deadline demo and the expansion's Program A -- there is deliberately
no separate "expansion version" of these entities. Field names match the
roadmap's table/column intent; types and validation are new.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.canonical.ids import (
    PLATFORM_TENANT_ID,
    PLATFORM_TENANT_NAME,
    DecisionEventId,
    DriverId,
    ModelVersionId,
    ObservationId,
    PolicyId,
    RequestId,
    ScheduleRunId,
    TenantId,
    VehicleId,
)
from packages.canonical.state_machine import ServiceRequestState
from packages.canonical.time import BitemporalMeta, RequestTimes, UtcDateTime
from packages.canonical.vocab import DecisionEventType, ReasonCode, ScheduleRunStatus


class _Canonical(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Tenant(_Canonical):
    tenant_id: TenantId
    name: str
    created_at: UtcDateTime


PLATFORM_TENANT_CREATED_AT = datetime(2026, 7, 24, tzinfo=timezone.utc)
"""The reserved tenant's registration instant: the date ADR-0040 was accepted.
A FIXED value, not `now()`, so seeding it twice produces a byte-identical row --
idempotency of the *value*, not just of the row count."""


def platform_tenant() -> Tenant:
    """The reserved platform tenant as a canonical `Tenant` row (ADR-0040).

    The reserved id must be a REAL row in `tenants`, because every tenant-scoped
    table has a foreign key to it -- a convention alone would fail the first
    insert. Both `SqliteCanonicalStore` and `PostgresCanonicalStore` seed exactly
    this row, idempotently, as part of store setup.
    """
    return Tenant(
        tenant_id=PLATFORM_TENANT_ID,
        name=PLATFORM_TENANT_NAME,
        created_at=PLATFORM_TENANT_CREATED_AT,
    )


class ServiceRequest(_Canonical):
    """The immutable-per-version request aggregate. A correction produces a
    new `ServiceRequest` with `meta.corrects_version` set and the same
    `request_id`, per architecture/decisions/0003-append-only-hash-chained-event-log.md.
    """

    request_id: RequestId
    tenant_id: TenantId
    rider_ref: str = Field(
        description="Tokenized rider reference. Never a raw name (blueprint 10 data minimization)."
    )
    pickup_zone: str
    dropoff_zone: str
    mobility_device: str | None = None
    times: RequestTimes
    status: ServiceRequestState
    meta: BitemporalMeta


class Vehicle(_Canonical):
    vehicle_id: VehicleId
    tenant_id: TenantId
    capacity_ambulatory: int = Field(ge=0)
    capacity_wheelchair: int = Field(ge=0)
    accessibility_equipment: tuple[str, ...] = ()


class Driver(_Canonical):
    driver_id: DriverId
    tenant_id: TenantId
    shift_start: UtcDateTime
    shift_end: UtcDateTime


class Policy(_Canonical):
    """Versioned time-window/ride-time/capacity/objective configuration."""

    policy_id: PolicyId
    tenant_id: TenantId
    name: str
    version: int = Field(ge=1)
    config: dict[str, float | int | str | bool]
    effective_from: UtcDateTime


class ModelVersion(_Canonical):
    model_version_id: ModelVersionId
    tenant_id: TenantId
    task: str
    training_data_manifest_hash: str
    feature_schema_version: str
    evaluation_window_start: UtcDateTime
    evaluation_window_end: UtcDateTime
    artifact_hash: str


class ForecastVintage(_Canonical):
    """What was predicted, when, for which horizon -- distinct from the
    eventual actual so forecast quality can be scored without contaminating
    the prediction with hindsight (replay/bitemporal invariant)."""

    tenant_id: TenantId
    model_version_id: ModelVersionId
    horizon_start: UtcDateTime
    horizon_end: UtcDateTime
    issued_at: UtcDateTime
    point_estimate: float
    interval_low: float | None = None
    interval_high: float | None = None
    eventual_actual: float | None = None


class ScheduleRun(_Canonical):
    schedule_run_id: ScheduleRunId
    tenant_id: TenantId
    policy_id: PolicyId
    solver_name: str
    solver_version: str
    seed: int
    status: ScheduleRunStatus
    objective_value: float | None = None
    bound: float | None = None
    gap: float | None = Field(default=None, description="Optimality gap; null unless status is feasible/optimal.")
    started_at: UtcDateTime
    finished_at: UtcDateTime | None = None


class DecisionAlternative(_Canonical):
    """A candidate assignment considered (and, usually, rejected) during a
    schedule run -- required so "why not the alternatives" is answerable."""

    schedule_run_id: ScheduleRunId
    request_id: RequestId
    candidate_vehicle_id: VehicleId | None = None
    feasible: bool
    failed_constraints: tuple[ReasonCode, ...] = ()
    objective_delta: float | None = None


class DecisionEvent(_Canonical):
    """One entry in the append-only, hash-chained decision ledger.

    See architecture/decisions/0003-append-only-hash-chained-event-log.md:
    tamper-evident, not immutable, not a compliance certificate.
    """

    event_id: DecisionEventId
    tenant_id: TenantId
    aggregate_id: str
    aggregate_type: str
    sequence: int = Field(ge=1)
    occurred_at: UtcDateTime
    actor_type: str = Field(pattern="^(system|human)$")
    actor_id: str
    event_type: DecisionEventType
    payload: dict
    reason_codes: tuple[ReasonCode, ...] = ()
    idempotency_key: str | None = None
    prev_hash: str | None
    hash: str


class Outcome(_Canonical):
    """What actually happened to one service request.

    ``vehicle_ref``/``run_ref`` are the CANONICAL HOME ADR-0038 found missing.
    Before them, the vehicle/run assignment lived only on the Connect-layer
    ``OperatorTripRecord`` and was recorded as a ``dropped`` semantic loss on
    every row -- so the single field the whole deadhead teardown depends on
    (``packages/replay/teardown.py`` chains ONE vehicle's consecutive trips;
    ADR-0038 makes ``vehicle_ref``-or-``run_ref`` a mandatory intake column for
    exactly that reason) survived the in-memory handoff and would NOT have
    survived a write to MilexiumDB.

    WHY HERE AND NOWHERE ELSE. Which vehicle/run performed (or was assigned and
    did not perform) a trip is a fact about *what happened*, not about what was
    asked for, so it belongs on the outcome record -- sitting directly beside
    ``deadhead_minutes``, the field derived from chaining it. It is deliberately
    NOT duplicated onto ``ServiceRequest``: one fact, one home, so the two can
    never disagree. A teardown needing the request's own times joins on
    ``(tenant_id, request_id)``.

    WHY PLAIN STRINGS, NOT ``VehicleId``. These name the SOURCE SYSTEM's entities
    (an operator's own vehicle number, run or block id), not a Milexium
    ``Vehicle`` aggregate -- the same reason ``VehicleObservation.vehicle_ref`` is
    a plain string. Typing them as ``VehicleId`` would assert a canonical
    aggregate that no operator export creates.

    Both are optional and BOTH may be absent: a trip whose export named neither
    is unattributable, and the teardown reports it as such rather than guessing
    it onto a neighbouring run. Absent means absent; it is never back-filled.
    """

    tenant_id: TenantId
    request_id: RequestId
    served: bool
    actual_pickup_at: UtcDateTime | None = None
    on_time: bool | None = None
    excess_ride_time_minutes: float | None = None
    deadhead_minutes: float | None = None
    vehicle_ref: str | None = Field(
        default=None,
        description="Source-system vehicle identifier, as the operator writes it. Never a VehicleId.",
    )
    run_ref: str | None = Field(
        default=None,
        description="Source-system run/block identifier, as the operator writes it.",
    )


class VehicleObservation(_Canonical):
    """A request-INDEPENDENT operational observation of one vehicle in motion.

    This is the operational/telemetry entity ADR-0031 found the canonical model
    was missing. GTFS-Realtime (and every AVL/telemetry source like it) is keyed
    by ``(trip, stop, vehicle)`` and carries NO rider request; before this entity,
    such data could only be squashed onto ``Outcome`` via a synthetic
    ``request_id`` that referenced no ServiceRequest, with position/occupancy/
    status all lost. A ``VehicleObservation`` instead keys on its own
    ``observation_id`` and the natural key ``(tenant_id, observed_at,
    vehicle_ref)``, and gives real homes to the operational context the feed
    actually carries.

    ``vehicle_ref``/``trip_ref``/``route_ref``/``stop_ref`` are the *source
    system's* identifiers (e.g. a GTFS vehicle/trip/route/stop id), kept as plain
    strings, NOT canonical typed ids -- they name an external agency's entities,
    not a Milexium ``Vehicle`` aggregate, so typing them as ``VehicleId`` would be
    the same category error this entity exists to avoid.

    Bitemporal: ``observed_at`` is valid time (when the vehicle was observed --
    the feed/vehicle timestamp, POSIX epoch, unambiguously UTC); ``recorded_at``
    is transaction time (when Milexium ingested it).
    """

    observation_id: ObservationId
    tenant_id: TenantId
    vehicle_ref: str | None = None
    trip_ref: str | None = None
    route_ref: str | None = None
    stop_ref: str | None = None
    current_status: str | None = Field(
        default=None,
        description="INCOMING_AT / STOPPED_AT / IN_TRANSIT_TO -- kept as the source string.",
    )
    latitude: float | None = None
    longitude: float | None = None
    bearing: float | None = None
    speed: float | None = None
    occupancy_status: str | None = None
    occupancy_percentage: int | None = Field(default=None, ge=0)
    observed_at: UtcDateTime
    recorded_at: UtcDateTime

    @model_validator(mode="after")
    def _validate_position(self) -> "VehicleObservation":
        """A geographic point needs both coordinates and both in range. Invalid
        or half-present coordinates are rejected here rather than silently stored
        (they would corrupt the PostGIS geometry populated from them)."""
        lat, lon = self.latitude, self.longitude
        if (lat is None) != (lon is None):
            raise ValueError(
                "latitude and longitude must be provided together (a point needs both) "
                "or both omitted"
            )
        if lat is not None and not (-90.0 <= lat <= 90.0):
            raise ValueError(f"latitude {lat} out of range [-90, 90]")
        if lon is not None and not (-180.0 <= lon <= 180.0):
            raise ValueError(f"longitude {lon} out of range [-180, 180]")
        return self


class StopTimeObservation(_Canonical):
    """A request-INDEPENDENT observation/prediction for one stop of one trip.

    The second half of the operational entity family (ADR-0031). A GTFS-Realtime
    ``TripUpdate`` ``stop_time_update`` -- which stop, in which trip, its schedule
    relationship, and predicted arrival/departure with schedule deviations -- has
    no rider request either, so it also could only be squashed onto ``Outcome``
    before. Here it keys on its own ``observation_id`` and ``(tenant_id, trip_ref,
    stop_ref/stop_sequence, observed_at)``.

    Predicted vs observed are kept as separate fields on purpose: GTFS-Realtime
    supplies *predictions* (``predicted_arrival_at`` and the delays); the
    ``observed_arrival_at``/``observed_departure_at`` fields are the homes a later
    observed-time source (AVL/TODS) will populate, and stay None for GTFS-RT --
    the same predicted-vs-actual discipline ``ForecastVintage`` keeps, so a
    prediction is never mistaken for a record of what happened.
    """

    observation_id: ObservationId
    tenant_id: TenantId
    trip_ref: str | None = None
    route_ref: str | None = None
    stop_ref: str | None = None
    stop_sequence: int | None = Field(default=None, ge=0)
    schedule_relationship: str | None = Field(
        default=None,
        description="SCHEDULED / SKIPPED / NO_DATA / UNSCHEDULED -- the source string.",
    )
    predicted_arrival_at: UtcDateTime | None = None
    predicted_departure_at: UtcDateTime | None = None
    observed_arrival_at: UtcDateTime | None = None
    observed_departure_at: UtcDateTime | None = None
    arrival_delay_seconds: int | None = None
    departure_delay_seconds: int | None = None
    observed_at: UtcDateTime
    recorded_at: UtcDateTime


class OutboxEntry(_Canonical):
    """Transactional handoff so exported state and recorded evidence cannot
    diverge (docs/MASTER_ROADMAP.md `outbox` table)."""

    tenant_id: TenantId
    event_id: DecisionEventId
    destination: str
    status: str = Field(pattern="^(pending|sent|failed)$")
    dispatched_at: UtcDateTime | None = None
