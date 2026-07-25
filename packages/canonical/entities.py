"""Canonical entities (Program A contract, v0.1).

These mirror the minimum tables in docs/MASTER_ROADMAP.md ("MilexiumDB: the
operational evidence data plane") exactly, so the same contract serves both
the YC-deadline demo and the expansion's Program A -- there is deliberately
no separate "expansion version" of these entities. Field names match the
roadmap's table/column intent; types and validation are new.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.canonical.ids import (
    PLATFORM_TENANT_ID,
    PLATFORM_TENANT_NAME,
    BlockId,
    DeadheadSegmentId,
    DecisionEventId,
    DriverId,
    ModelVersionId,
    ObservationId,
    PolicyId,
    RequestId,
    RunPieceId,
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


DeadheadKind = Literal[
    "pull_out", "pull_in", "interline", "relief", "repositioning", "other"
]
"""What a non-revenue movement WAS. The five named kinds are the ones a
scheduler actually acts on differently:

- ``pull_out``  -- garage/depot to the start of the first revenue trip.
- ``pull_in``   -- end of the last revenue trip back to the garage/depot.
- ``interline`` -- between two revenue trips the same vehicle performs, typically
  on different routes; the movement that block-building exists to minimise.
- ``relief``    -- to or from a relief point where one operator hands the vehicle
  to another. Empty for a different reason: the crew, not the schedule.
- ``repositioning`` -- any other in-service empty movement (to a layover point, a
  fuelling stop, a turn-back).

``other`` is a deliberate escape hatch, NOT a default. A source that records a
deadhead without saying which kind it was maps to ``other`` so the movement is
still counted, rather than being guessed into ``interline`` and silently
inflating the one number an interlining change is measured by. It is a
CLASSIFICATION carried by the source, never inferred here from geometry or
timing -- the same discipline ``packages.replay.teardown.SegmentKind`` keeps.

A closed Literal rather than a free string (unlike ``current_status`` /
``schedule_relationship`` on the telemetry family, which stay source strings):
this is the field a consumer BRANCHES on, so an unrecognised value would not be
lossless detail, it would be a silently unhandled branch. The portable schema
mirrors it with `CHECK (deadhead_type IN (...))`, which is why it is a Literal
here and not an enum in vocab.py -- ADR-0002 bans ENUM types from the portable
DDL.
"""


class Block(_Canonical):
    """One vehicle's continuous work between pull-out and pull-in.

    The first entity of the request-INDEPENDENT **scheduling** family, and the
    canonical home ADR-0031 found missing for TODS. ADR-0035 closed the
    *telemetry* half of that gap (``VehicleObservation`` /
    ``StopTimeObservation``: what a vehicle was observed doing). This is the
    other half: what a vehicle and an operator were ASSIGNED to do. TODS
    describes runs, blocks, pieces-of-work and deadheads, and every one of them
    was homeless -- which is why ADR-0031 and ADR-0035 both left TODS and NeTEx
    Specified rather than half-building an adapter that would route most of the
    standard to semantic loss.

    A block is the vehicle's unit of work: it leaves the garage once
    (``pull_out_at``), performs a sequence of revenue trips and the deadheads
    between them, and returns once (``pull_in_at``). It is the thing a
    ``DeadheadSegment`` belongs to and the thing a ``RunPiece`` is worked on.

    REQUEST-INDEPENDENT, like the telemetry family and for the same reason. A
    block exists whether or not a single rider ever asks for anything -- it is
    published days before service runs. ``_Canonical``'s ``extra="forbid"``
    means a ``request_id`` cannot even be attached to one, so ADR-0031's
    synthetic-``request_id`` squash is structurally impossible here.

    SOURCE REFS ARE PLAIN STRINGS, NOT CANONICAL TYPED IDS -- ADR-0035's first
    design call, applied unchanged. ``block_ref`` is the agency's own block id
    (GTFS ``trips.block_id``, a TODS block), ``vehicle_ref`` their vehicle
    number, ``garage_ref`` their depot code. They name an EXTERNAL agency's
    entities, not Milexium aggregates, so typing ``vehicle_ref`` as ``VehicleId``
    would assert a canonical ``Vehicle`` row no operator export creates. The
    canonical id is ``block_id``: the record's own key, pointing at nothing it
    cannot back up.

    Bitemporal: ``pull_out_at``/``pull_in_at`` are valid time (when the vehicle
    is/was out); ``recorded_at`` is transaction time (when Milexium ingested the
    assignment).
    """

    block_id: BlockId
    tenant_id: TenantId
    block_ref: str | None = Field(
        default=None,
        description="Source-system block identifier (e.g. GTFS trips.block_id). Never a canonical id.",
    )
    service_ref: str | None = Field(
        default=None,
        description="Source-system service/calendar identifier the block runs under (e.g. GTFS service_id).",
    )
    vehicle_ref: str | None = Field(
        default=None,
        description="Source-system vehicle identifier assigned to the block. Never a VehicleId.",
    )
    garage_ref: str | None = Field(
        default=None,
        description="Source-system garage/depot the block pulls out of and back into.",
    )
    pull_out_at: UtcDateTime
    pull_in_at: UtcDateTime
    recorded_at: UtcDateTime

    @model_validator(mode="after")
    def _pull_in_does_not_precede_pull_out(self) -> "Block":
        """A vehicle cannot return before it leaves. Rejected at construction
        because a reversed pair is a parsing artefact (a date rollover, a
        local-vs-UTC mix-up) that would otherwise yield a NEGATIVE block
        duration and quietly subtract from every total derived from it."""
        if self.pull_in_at < self.pull_out_at:
            raise ValueError(
                f"block pulls in before it pulls out ({self.pull_in_at.isoformat()} < "
                f"{self.pull_out_at.isoformat()})"
            )
        return self


class RunPiece(_Canonical):
    """One continuous piece of work in an operator's run (TODS `runs_pieces`).

    A *run* is one operator's assignment for a service day; a *piece* is one
    unbroken stretch of it on one block, bounded by a report, a relief or a
    pull-in. A two-piece run is a split shift: morning peak, break, afternoon
    peak.

    WHY THE ROW IS A PIECE AND NOT A RUN. TODS gives a run no attribute of its
    own -- ``runs_pieces.txt`` is one row per (run, piece), and the run is the
    grouping key those rows share. Minting a separate ``Run`` table would create
    an aggregate with nothing in it but an id, and two places for the same fact
    to disagree. So the run's identity lives on every piece as ``run_ref``, and a
    single-piece run is exactly one row. Grouping by ``run_ref`` reconstructs the
    run; a piece whose export named no run is *unattributable* and says so,
    rather than being invented into a run that did not work it.

    REQUEST-INDEPENDENT, and structurally so (``extra="forbid"``): a crew
    assignment is made before any rider request exists.

    ``operator_ref`` IS A PERSON REFERENCE AND IS TREATED LIKE ONE. It follows
    ``ServiceRequest.rider_ref``'s rule exactly (blueprint 10 data
    minimisation): a tokenised badge/run-signup reference as the operator's own
    system writes it, NEVER a name. Nothing in this package needs to know who an
    operator is -- only that the same one worked two pieces -- so a token is
    sufficient for every consumer and a name is never required.
    """

    run_piece_id: RunPieceId
    tenant_id: TenantId
    run_ref: str | None = Field(
        default=None,
        description="Source-system run identifier this piece belongs to. None means the export did not say.",
    )
    piece_ref: str | None = Field(
        default=None, description="Source-system identifier for the piece itself, where one exists."
    )
    piece_sequence: int | None = Field(
        default=None, ge=0, description="Position of this piece within its run, when the source orders them."
    )
    operator_ref: str | None = Field(
        default=None,
        description="Tokenized operator reference. Never a raw name (blueprint 10 data minimization).",
    )
    block_id: BlockId | None = Field(
        default=None,
        description="The canonical Block this piece works, when Milexium holds one. Optional: a crew export can arrive before the vehicle assignment does.",
    )
    block_ref: str | None = Field(
        default=None,
        description="Source-system block identifier as the export writes it, kept even when block_id is unresolved.",
    )
    vehicle_ref: str | None = None
    start_type: str | None = Field(
        default=None,
        description="Why the piece begins (report / pull-out / relief) -- kept as the source string.",
    )
    end_type: str | None = Field(
        default=None,
        description="Why the piece ends (relief / pull-in) -- kept as the source string.",
    )
    started_at: UtcDateTime
    ended_at: UtcDateTime
    recorded_at: UtcDateTime

    @model_validator(mode="after")
    def _piece_does_not_end_before_it_starts(self) -> "RunPiece":
        if self.ended_at < self.started_at:
            raise ValueError(
                f"run piece ends before it starts ({self.ended_at.isoformat()} < "
                f"{self.started_at.isoformat()})"
            )
        return self


class DeadheadSegment(_Canonical):
    """One non-revenue ("empty") vehicle movement: pull-out, pull-in, interlining.

    The third scheduling entity, and the one with a consumer already waiting for
    it. ``packages/replay/teardown.py`` measures exactly this -- where empty
    vehicle time sat, by hour, by day and by run -- but it can only be handed
    ``VehicleSegment``s built in memory from a Connect-layer export, because
    deadhead had no canonical home to be read back out of. This entity is that
    home, and it is deliberately shaped so the handoff is a field-for-field
    mapping rather than a translation:

        VehicleSegment(started_at=seg.started_at, ended_at=seg.ended_at,
                       kind="deadhead", run_ref=seg.run_ref)

    ``started_at``/``ended_at``/``run_ref`` therefore carry the teardown's own
    names, and ``run_ref`` keeps the teardown's absence semantics precisely: None
    means the export did not say, the segment lands in ``unattributable``, and it
    is NEVER guessed onto a neighbouring run. A fabricated run reference would
    attribute empty time to a run that did not incur it, which is the one error a
    teardown exists to prevent.

    ``deadhead_type`` is REQUIRED, unlike almost every other field here, because
    a movement nobody classified is still a classification decision -- see
    ``DeadheadKind`` for why ``other`` is the honest landing place and not a
    default. Every other field is optional: a source that gives only "this
    vehicle was empty from 06:12 to 06:31" still produces a usable row.

    REQUEST-INDEPENDENT (``extra="forbid"``), and necessarily so: deadhead is
    time when NO rider is aboard. Keying it on a rider request would be the
    ADR-0031 category error in its purest form.
    """

    deadhead_segment_id: DeadheadSegmentId
    tenant_id: TenantId
    deadhead_ref: str | None = Field(
        default=None, description="Source-system identifier for the deadhead itself (e.g. a TODS deadhead_id)."
    )
    block_id: BlockId | None = Field(
        default=None,
        description="The canonical Block this movement belongs to, when Milexium holds one.",
    )
    block_ref: str | None = None
    run_ref: str | None = Field(
        default=None,
        description=(
            "Source-system run/block identifier, as the operator writes it -- the field "
            "packages.replay.teardown attributes empty time by. None means unattributable."
        ),
    )
    vehicle_ref: str | None = None
    deadhead_type: DeadheadKind
    from_stop_ref: str | None = Field(
        default=None, description="Source-system stop/location the movement started from (a garage, a terminal)."
    )
    to_stop_ref: str | None = Field(
        default=None, description="Source-system stop/location the movement ended at."
    )
    started_at: UtcDateTime
    ended_at: UtcDateTime
    recorded_at: UtcDateTime

    @model_validator(mode="after")
    def _segment_does_not_end_before_it_starts(self) -> "DeadheadSegment":
        """The same guard ``packages.replay.teardown.VehicleSegment`` applies to
        its own inputs, applied one layer earlier so a reversed pair cannot even
        be STORED. A negative duration here would subtract from the empty-time
        total and make a teardown understate the very thing it measures."""
        if self.ended_at < self.started_at:
            raise ValueError(
                f"deadhead segment ends before it starts ({self.ended_at.isoformat()} < "
                f"{self.started_at.isoformat()})"
            )
        return self


class OutboxEntry(_Canonical):
    """Transactional handoff so exported state and recorded evidence cannot
    diverge (docs/MASTER_ROADMAP.md `outbox` table)."""

    tenant_id: TenantId
    event_id: DecisionEventId
    destination: str
    status: str = Field(pattern="^(pending|sent|failed)$")
    dispatched_at: UtcDateTime | None = None
