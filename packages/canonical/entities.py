"""Canonical entities (Program A contract, v0.1).

These mirror the minimum tables in docs/MASTER_ROADMAP.md ("MilexiumDB: the
operational evidence data plane") exactly, so the same contract serves both
the YC-deadline demo and the expansion's Program A -- there is deliberately
no separate "expansion version" of these entities. Field names match the
roadmap's table/column intent; types and validation are new.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.canonical.ids import (
    DecisionEventId,
    DriverId,
    ModelVersionId,
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
    tenant_id: TenantId
    request_id: RequestId
    served: bool
    actual_pickup_at: UtcDateTime | None = None
    on_time: bool | None = None
    excess_ride_time_minutes: float | None = None
    deadhead_minutes: float | None = None


class OutboxEntry(_Canonical):
    """Transactional handoff so exported state and recorded evidence cannot
    diverge (docs/MASTER_ROADMAP.md `outbox` table)."""

    tenant_id: TenantId
    event_id: DecisionEventId
    destination: str
    status: str = Field(pattern="^(pending|sent|failed)$")
    dispatched_at: UtcDateTime | None = None
