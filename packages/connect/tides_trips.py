"""Adapter: TIDES trips_performed rows -> ServiceRequest (v0.1).

Status: **Demonstrated** only. TIDES (Transit ITS Data Exchange Specification)
is the open community standard for demand-responsive/paratransit trip-level
operational data. The column schema this adapter maps is the real TIDES
`trips_performed` header (acquired at data/standards/tides-sample.*.csv), but
the rows this adapter is exercised against are open-spec fixtures, not
consented paratransit operator data -- nothing here may be promoted to
"Validated", per architecture/decisions/0001.

This is a deliberately *third*, structurally-different adapter against the same
packages.connect.adapter.SourceAdapter contract, alongside
reference_agency_trips.py (fictional CSV) and tlc_trips.py (real TLC Parquet).
Its defining heterogeneity: TIDES trips_performed is a *performed-vehicle-trip*
record, not a booking record. It has no rider identity, no mobility-device
field, and -- most importantly -- no rider "request" timestamp at all, so the
mandatory ServiceRequest.requested_at has no direct source field (see the
service_date coercion below, and the accompanying ADR).

THE VEHICLE AND RUN REFERENCE (MX-B-ADAPTER-REFS-009, extending ADR-0054)
TIDES is the one remaining adapter source that genuinely carries BOTH fields the
deadhead teardown chains on: `vehicle_id` is the vehicle that performed the trip
and `block_id` is a day's chained vehicle work -- the run reference. ADR-0043
put their canonical home on `Outcome` and deliberately not on `ServiceRequest`,
so `parse()` (which returns a request) still reports them as dropped, correctly
and now narrowly. `parse_performed_trip()` returns the `Outcome` that carries
them, and it is the entry point anything feeding the teardown should use.

TIDES trips_performed columns (from data/standards/tides-sample.*.csv, the real
TIDES header row):
    date, trip_id_performed, vehicle_id, trip_id_scheduled, route_id,
    route_type, shape_id, direction_id, operator_id, block_id,
    trip_start_stop_id, trip_end_stop_id, schedule_trip_start,
    schedule_trip_end, actual_trip_start, actual_trip_end, trip_type,
    schedule_relationship, service_date
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, model_validator

from packages.canonical import (
    BitemporalMeta,
    Outcome,
    RequestId,
    RequestTimes,
    ServiceRequest,
    ServiceRequestState,
    TenantId,
    new_id,
)
from packages.connect.adapter import AdapterResult, QuarantinedRow, SemanticLossRecord

# service_date is required because it is the only always-present temporal anchor
# available to fill the mandatory requested_at (see _parse_service_date and the
# service_date semantic-loss entry in parse() for the full justification).
REQUIRED_COLUMNS = ("service_date", "trip_start_stop_id", "trip_end_stop_id")

# Real TIDES trips_performed columns that ServiceRequest v0.1 has no home for.
# Each is recorded as a `dropped` semantic-loss entry rather than silently
# discarded (blueprint/03-connect-and-standards.md).
_UNMAPPED_COLUMN_REASONS = {
    "date": (
        "operational calendar date of the record; requested_at is anchored on "
        "service_date (the service-day field that also captures after-midnight "
        "trips) instead, so this near-duplicate has no separate ServiceRequest home"
    ),
    "trip_id_performed": (
        "TIDES's own performed-trip identifier; ServiceRequest mints its own "
        "request_id, and this is a vehicle-trip id, not a booking/request id"
    ),
    "trip_id_scheduled": (
        "linkage to the scheduled-trip record it was performed against; no "
        "ServiceRequest v0.1 field for a source scheduled-trip cross-reference"
    ),
    "vehicle_id": (
        "identifies the vehicle that performed the trip. Dropped from THIS output and only "
        "this one: ADR-0043 gave vehicle_ref a canonical home on Outcome and deliberately NOT "
        "on ServiceRequest (one fact, one home), and parse() returns a request. It is no "
        "longer homeless -- parse_performed_trip() returns the Outcome that carries it "
        "verbatim (MX-B-ADAPTER-REFS-009)"
    ),
    "operator_id": (
        "identifies the operating agency/operator (belongs on Driver / Tenant), "
        "not a rider and not a ServiceRequest field"
    ),
    "block_id": (
        "the vehicle block -- a day's chained vehicle work, and the run reference the deadhead "
        "teardown groups on. Dropped from THIS output only, for the same reason as vehicle_id: "
        "run_ref lives on Outcome, not ServiceRequest. parse_performed_trip() carries it "
        "(MX-B-ADAPTER-REFS-009)"
    ),
    "route_id": "route the trip ran on has no ServiceRequest v0.1 field",
    "route_type": "GTFS route-type classification has no ServiceRequest v0.1 field",
    "shape_id": "trip geometry/shape reference has no ServiceRequest v0.1 field",
    "direction_id": "trip direction flag has no ServiceRequest v0.1 field",
    "schedule_trip_end": (
        "scheduled trip END; ServiceRequest models the request/pickup, not the "
        "executed trip's end, so there is no scheduled-dropoff time field"
    ),
    "actual_trip_end": (
        "observed trip END/completion; ServiceRequest has no actual-dropoff time "
        "field (a trip's end/dropoff belongs on an Outcome record)"
    ),
    "trip_type": "TIDES trip-type classification has no ServiceRequest v0.1 field",
    "schedule_relationship": (
        "GTFS-style schedule relationship (scheduled/added/unscheduled/canceled); "
        "could in principle inform ServiceRequestState, but mapping it would "
        "require walking the aggregate through check_transition, out of scope for a "
        "one-row parse -- status is left at REQUESTED, the same boundary "
        "tlc_trips.py drew for its own implicit trip outcome"
    ),
}

_KNOWN_COLUMNS = (
    frozenset(REQUIRED_COLUMNS)
    | frozenset(_UNMAPPED_COLUMN_REASONS)
    | frozenset({"schedule_trip_start", "actual_trip_start"})
)


ENTITY_BEHIND_THE_LABEL_FIELD = "<the block or vehicle the reference names>"
"""The `source_field` of the NARROWED loss record `parse_performed_trip()`
emits in place of the `vehicle_id`/`block_id` `dropped` records.

ADR-0054 narrowed rather than deleted the equivalent record for the operator
export, and the reasoning transfers unchanged: the reference itself is retained,
the ENTITY it names is not. Deleting the record outright is the tidy-looking
move that silently discards a residual claim which is still true."""

_CANCELED_RELATIONSHIPS = frozenset({"canceled", "cancelled"})
"""GTFS-style `schedule_relationship` values that mean the trip did not run.
Both spellings, because TIDES inherits GTFS's American `canceled` but exports
are written by people."""


class TidesPerformedTrip(BaseModel):
    """One TIDES `trips_performed` row as the canonical entities it actually is.

    NOT a canonical entity: `packages.canonical` owns the canonical model and
    this module does not extend it. A Connect-layer container, exactly as
    `OperatorTripRecord` is, so one call can return the request and the outcome
    that carries the vehicle/run reference together.

    WHY THIS EXISTS ALONGSIDE `parse()` RATHER THAN REPLACING IT. Two reasons,
    both about files this packet does not own. `parse()` returns an
    `AdapterResult[ServiceRequest]`, and five assertions across two unowned test
    files (`conformance/fixtures/test_connect_tides_trips.py`,
    `conformance/adversarial/test_connect_tides_malformed_rows.py`) read
    `result.record` as a request. More binding: one of them pins
    `lost["vehicle_id"].disposition == "dropped"` and `source_value == "VH-07"`,
    which is exactly the record that would have to move. Changing the return
    type is the right end state and is a follow-up, not something to do to other
    people's files from here. The cost is real and is stated rather than hidden:
    two entry points for one row. It is bounded by construction --
    `parse_performed_trip()` CALLS `parse()` and returns its request unmodified,
    so the two cannot disagree about anything except the loss list, where they
    differ deliberately (see `ENTITY_BEHIND_THE_LABEL_FIELD`).

    `vehicle_ref`/`run_ref` are mirrored here for symmetry with
    `OperatorTripRecord`; `Outcome.vehicle_ref`/`Outcome.run_ref` is the copy
    that persists, and both are set from one source.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request: ServiceRequest
    outcome: Outcome
    vehicle_ref: str | None = None
    run_ref: str | None = None

    @model_validator(mode="after")
    def _outcome_belongs_to_request(self) -> "TidesPerformedTrip":
        if self.outcome.request_id != self.request.request_id:
            raise ValueError("outcome.request_id must reference the request it accompanies")
        if self.outcome.tenant_id != self.request.tenant_id:
            raise ValueError("outcome.tenant_id must match the request's tenant")
        return self


class _UnmappableValue(ValueError):
    """Internal signal that a field value cannot become canonical; caught in
    parse() and turned into a QuarantinedRow rather than propagating."""


def _is_blank(value: object) -> bool:
    """True for the null vocabulary a TIDES CSV export actually uses: an absent
    key (None) or an empty/whitespace-only string cell."""
    return value is None or (isinstance(value, str) and value.strip() == "")


def _parse_service_date(raw_value: object) -> datetime:
    """service_date -> a midnight-UTC day anchor for the mandatory requested_at.

    Accepts the TIDES date form 'YYYY-MM-DD'. A datetime is accepted for its
    date only (its time-of-day, if any, is deliberately discarded -- the day
    anchor must not smuggle in a spurious request time)."""
    if isinstance(raw_value, datetime):
        return datetime(raw_value.year, raw_value.month, raw_value.day, tzinfo=timezone.utc)
    if not isinstance(raw_value, str):
        raise _UnmappableValue(f"unparseable service_date: {raw_value!r}")
    try:
        day = datetime.strptime(raw_value.strip()[:10], "%Y-%m-%d")
    except ValueError as exc:
        raise _UnmappableValue(f"unparseable service_date {raw_value!r}: {exc}") from exc
    return day.replace(tzinfo=timezone.utc)


def _parse_timestamp(column: str, raw_value: object) -> datetime:
    """A TIDES ISO-8601 timestamp -> a UTC datetime.

    Naive timestamps are treated as UTC directly (the same simplification
    reference_agency_trips.py and tlc_trips.py already use -- recorded as
    semantic loss by the caller). Timezone-aware timestamps are converted to
    UTC honestly via astimezone."""
    if isinstance(raw_value, datetime):
        value = raw_value
    elif isinstance(raw_value, str):
        try:
            value = datetime.fromisoformat(raw_value.strip())
        except ValueError as exc:
            raise _UnmappableValue(f"unparseable {column} timestamp {raw_value!r}: {exc}") from exc
    else:
        raise _UnmappableValue(f"unparseable {column} timestamp: {raw_value!r}")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _reference(raw_row: dict, column: str) -> str | None:
    """A TIDES reference column -> its trimmed value, or None when the export did
    not carry it.

    ABSENT IS ABSENT. A blank cell becomes None, never `''` and never the string
    `'None'`, because either would read back out of a nullable TEXT column later
    as a block somebody worked. Reads exactly one column and has no fallback
    argument, so there is no expression anywhere in this module that could
    back-fill a missing block from a vehicle number.
    """
    value = raw_row.get(column)
    return None if _is_blank(value) else str(value).strip()


def _synthetic_rider_ref(raw_row: dict) -> str:
    # TIDES trips_performed publishes no rider/passenger identifier at all; this
    # hash is a deterministic per-row placeholder that satisfies
    # ServiceRequest.rider_ref, never a stable or joinable entity id. vehicle_id/
    # operator_id/block_id identify vehicles/operators/blocks, not people, so
    # tokenizing one of those the way reference_agency_trips.py tokenizes an
    # actual per-rider id would misrepresent unrelated riders as one identity.
    basis = "|".join(
        str(raw_row.get(field))
        for field in ("service_date", "trip_id_performed", "trip_start_stop_id", "trip_end_stop_id")
    )
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    return f"tides-no-rider-{digest}"


class TidesTripsAdapter:
    """Maps one TIDES trips_performed row onto a fresh ServiceRequest.

    `recorded_at` is the adapter run's own transaction time (BitemporalMeta),
    distinct from the trip's valid-time fields -- it is not read from the
    source, which has no notion of import/transaction time at all.
    """

    adapter_name = "tides-trips-performed-csv"
    adapter_version = "0.1.0"

    def __init__(self, tenant_id: TenantId, *, recorded_at: datetime) -> None:
        self._tenant_id = tenant_id
        self._recorded_at = recorded_at

    def parse(self, raw_row: dict) -> AdapterResult[ServiceRequest]:
        missing = [c for c in REQUIRED_COLUMNS if _is_blank(raw_row.get(c))]
        if missing:
            return AdapterResult(
                quarantine=QuarantinedRow(
                    raw_row=dict(raw_row),
                    reason=f"missing required field(s): {', '.join(missing)}",
                    failed_field=missing[0],
                )
            )

        schedule_present = not _is_blank(raw_row.get("schedule_trip_start"))
        actual_present = not _is_blank(raw_row.get("actual_trip_start"))
        try:
            requested_at = _parse_service_date(raw_row["service_date"])
            scheduled_pickup_at = (
                _parse_timestamp("schedule_trip_start", raw_row["schedule_trip_start"])
                if schedule_present
                else None
            )
            actual_pickup_at = (
                _parse_timestamp("actual_trip_start", raw_row["actual_trip_start"])
                if actual_present
                else None
            )
        except _UnmappableValue as exc:
            return AdapterResult(quarantine=QuarantinedRow(raw_row=dict(raw_row), reason=str(exc)))

        pickup_zone = str(raw_row["trip_start_stop_id"]).strip()
        dropoff_zone = str(raw_row["trip_end_stop_id"]).strip()

        semantic_loss = [
            SemanticLossRecord(
                source_field="service_date",
                source_value=str(raw_row["service_date"]),
                reason=(
                    "TIDES trips_performed is a performed-vehicle-trip record with NO rider "
                    "request/booking timestamp of any kind; requested_at ('the fact that starts "
                    "the aggregate') has no direct source. service_date's midnight is used as a "
                    "day-granularity placeholder anchor -- explicitly not a real request instant. "
                    "Chosen over schedule_trip_start because reusing the scheduled pickup time "
                    "would falsely assert zero advance-notice booking (wrong for the advance-"
                    "reservation paratransit/DRT domain TIDES describes) and would collapse two "
                    "distinct fields onto one value; service_date instead preserves the natural "
                    "requested_at <= scheduled_pickup_at <= actual_pickup_at ordering (it is the "
                    "service-day anchor, <= every clock time in the service day, including after-"
                    "midnight trips) and is always populated. The naive date is treated as 00:00 "
                    "UTC, the same simplification the other two adapters use"
                ),
                disposition="coerced",
            )
        ]
        if schedule_present:
            semantic_loss.append(
                SemanticLossRecord(
                    source_field="schedule_trip_start",
                    source_value=str(raw_row["schedule_trip_start"]),
                    reason=(
                        "trip-level scheduled START of the performed vehicle trip, used as the "
                        "proxy for scheduled_pickup_at (TIDES trips_performed records a vehicle "
                        "trip, not a per-rider pickup; the trip's first-stop start time is the "
                        "closest available signal). Naive timestamps are treated as UTC directly "
                        "with no offset conversion, the same simplification the other adapters use"
                    ),
                    disposition="coerced",
                )
            )
        if actual_present:
            semantic_loss.append(
                SemanticLossRecord(
                    source_field="actual_trip_start",
                    source_value=str(raw_row["actual_trip_start"]),
                    reason=(
                        "observed trip-level START of the performed vehicle trip, used as the "
                        "proxy for actual_pickup_at (same vehicle-trip vs. rider-pickup gap as "
                        "schedule_trip_start). Naive timestamps are treated as UTC directly with "
                        "no offset conversion, the same simplification the other adapters use"
                    ),
                    disposition="coerced",
                )
            )
        semantic_loss.append(
            SemanticLossRecord(
                source_field="<no rider/passenger identifier column>",
                source_value=None,
                reason=(
                    "TIDES trips_performed carries no rider/passenger-level identifier; it is a "
                    "vehicle-trip performance record. vehicle_id/operator_id/block_id identify "
                    "the vehicle, operator, and block, never a person, so rider_ref is a synthetic "
                    "per-row placeholder (tides-no-rider-<sha256>), not a stable or joinable "
                    "entity reference"
                ),
                disposition="dropped",
            )
        )
        semantic_loss.append(
            SemanticLossRecord(
                source_field="<no mobility-device column>",
                source_value=None,
                reason=(
                    "TIDES trips_performed has no rider mobility-device / wheelchair field at "
                    "all (unlike TLC's wav_request_flag); mobility_device is left None rather "
                    "than guessed"
                ),
                disposition="dropped",
            )
        )
        for column, reason in _UNMAPPED_COLUMN_REASONS.items():
            value = raw_row.get(column)
            if not _is_blank(value):
                semantic_loss.append(
                    SemanticLossRecord(
                        source_field=column, source_value=str(value), reason=reason, disposition="dropped"
                    )
                )
        for column, value in raw_row.items():
            if column not in _KNOWN_COLUMNS:
                semantic_loss.append(
                    SemanticLossRecord(
                        source_field=column,
                        source_value=str(value) if not _is_blank(value) else None,
                        reason="not part of the documented TIDES trips_performed schema this adapter maps",
                        disposition="unmapped_extension",
                    )
                )

        request = ServiceRequest(
            request_id=new_id(RequestId),
            tenant_id=self._tenant_id,
            rider_ref=_synthetic_rider_ref(raw_row),
            pickup_zone=pickup_zone,
            dropoff_zone=dropoff_zone,
            mobility_device=None,
            times=RequestTimes(
                requested_at=requested_at,
                scheduled_pickup_at=scheduled_pickup_at,
                actual_pickup_at=actual_pickup_at,
            ),
            status=ServiceRequestState.REQUESTED,
            meta=BitemporalMeta(version=1, recorded_at=self._recorded_at),
        )
        return AdapterResult(record=request, semantic_loss=tuple(semantic_loss))

    def parse_performed_trip(self, raw_row: dict) -> AdapterResult[TidesPerformedTrip]:
        """The same row as a request AND the outcome that carries its vehicle
        and block (MX-B-ADAPTER-REFS-009, extending ADR-0054).

        TIDES `trips_performed` is the one remaining adapter source that is
        genuinely a record of WHAT HAPPENED and names both references the
        deadhead teardown needs: `vehicle_id` is the vehicle that performed the
        trip, and `block_id` is a day's chained vehicle work -- the same concept
        `Block.block_ref` documents as "GTFS trips.block_id", and exactly what
        `VehicleSegment.run_ref` groups on. Both are carried verbatim onto
        `Outcome.vehicle_ref`/`Outcome.run_ref`, so they survive a write to
        MilexiumDB rather than dying at the process boundary.

        `served` IS A JUDGMENT AND IS ONLY MADE WHERE THE ROW SUPPORTS IT.
        `Outcome.served` is a non-nullable bool with no "unknown", so a row that
        does not say what happened is QUARANTINED here rather than defaulted
        either way. Defaulting True would assert service that may never have run;
        defaulting False would assert a failure the operator never reported, and
        both would be invisible in the totals. Two signals decide it: a
        `schedule_relationship` of canceled/cancelled means the trip did not run
        (served=False), and otherwise a present `actual_trip_start` means it did
        (served=True). A row with neither is refused. `parse()` still accepts
        such a row -- it is a perfectly good request; it is only unusable as a
        performed trip.

        A row naming NEITHER a vehicle nor a block is accepted, with both fields
        None, unlike `operator_export.py` which quarantines it. That is not an
        inconsistency: ADR-0038 made vehicle-or-run a MANDATORY intake column for
        operator exports, a contract Milexium negotiates with the sender. TIDES
        is a published standard whose fields are optional and which Milexium does
        not get to renegotiate, so the honest destination for an unattributed
        performed trip is ADR-0039's `unattributable` bucket, not a rejection.
        """
        base = self.parse(raw_row)
        if base.is_quarantined:
            return AdapterResult(quarantine=base.quarantine)

        request = base.record
        relationship = raw_row.get("schedule_relationship")
        canceled = (
            not _is_blank(relationship)
            and str(relationship).strip().lower() in _CANCELED_RELATIONSHIPS
        )
        actual_started = request.times.actual_pickup_at is not None
        if not canceled and not actual_started:
            return AdapterResult(
                quarantine=QuarantinedRow(
                    raw_row=dict(raw_row),
                    reason=(
                        "the row does not say whether the trip was performed: actual_trip_start is "
                        "absent and schedule_relationship does not report a cancellation. "
                        "Outcome.served is a non-nullable bool, so there is no honest value to "
                        "write -- defaulting it either way would put an unreported fact into every "
                        "total derived from it. parse() still maps this row to a ServiceRequest"
                    ),
                    failed_field="actual_trip_start",
                )
            )

        vehicle_ref = _reference(raw_row, "vehicle_id")
        run_ref = _reference(raw_row, "block_id")
        outcome = Outcome(
            tenant_id=request.tenant_id,
            request_id=request.request_id,
            served=not canceled,
            # Only where the trip actually ran. A canceled trip has no observed
            # pickup even if the export left a stale timestamp in the column.
            actual_pickup_at=None if canceled else request.times.actual_pickup_at,
            # Not derived here. on_time would need the scheduled-vs-actual
            # comparison and a tolerance nobody has agreed; excess ride time
            # needs a dropoff this adapter does not map; deadhead_minutes is the
            # teardown's OUTPUT, and computing it per row would invert the
            # dependency this packet exists to feed.
            on_time=None,
            excess_ride_time_minutes=None,
            deadhead_minutes=None,
            # ADR-0043's columns. Each read from its OWN source column: a missing
            # block is never back-filled from the vehicle number, and vice versa.
            vehicle_ref=vehicle_ref,
            run_ref=run_ref,
        )
        record = TidesPerformedTrip(
            request=request, outcome=outcome, vehicle_ref=vehicle_ref, run_ref=run_ref
        )

        # The reference is no longer lost, so it is no longer reported as lost --
        # a loss list that keeps naming a field it persists teaches its reader to
        # discount the whole list. What remains true is NARROWER and is kept.
        semantic_loss = [
            loss for loss in base.semantic_loss if loss.source_field not in ("vehicle_id", "block_id")
        ]
        if vehicle_ref is not None or run_ref is not None:
            semantic_loss.append(
                SemanticLossRecord(
                    source_field=ENTITY_BEHIND_THE_LABEL_FIELD,
                    source_value=None,
                    reason=(
                        "the reference itself is retained: vehicle_id/block_id are written to "
                        "Outcome.vehicle_ref/Outcome.run_ref (ADR-0043) and survive a write to "
                        "MilexiumDB. What is NOT retained is the entity behind the label. These "
                        "stay plain source-system strings with no foreign key to vehicles, blocks "
                        "or run_pieces, and no Vehicle/Block/RunPiece row is minted here: a "
                        "trips_performed row describes ONE trip, and a Block needs the pull-out "
                        "and pull-in of a whole service day, which no single row carries and a "
                        "one-row parse() cannot aggregate. Two consequences worth stating plainly: "
                        "the same block id sent by two agencies is not one block, and a teardown "
                        "can measure the gaps BETWEEN this block's consecutive trips but not the "
                        "empty time before its first trip or after its last, which is therefore "
                        "invisible rather than zero"
                    ),
                    disposition="dropped",
                )
            )
        semantic_loss.append(
            SemanticLossRecord(
                source_field="schedule_relationship" if canceled else "actual_trip_start",
                source_value=str(relationship) if canceled else str(raw_row.get("actual_trip_start")),
                reason=(
                    "Outcome.served is materialised from this field. TIDES has no explicit "
                    "served/not-served column, so a cancellation in schedule_relationship is read "
                    "as served=False and a present actual_trip_start as served=True; a row saying "
                    "neither is quarantined by parse_performed_trip() rather than defaulted. "
                    "on_time, excess_ride_time_minutes and deadhead_minutes are left None -- not "
                    "guessed from schedule_trip_start"
                ),
                disposition="coerced",
            )
        )
        return AdapterResult(record=record, semantic_loss=tuple(semantic_loss))
