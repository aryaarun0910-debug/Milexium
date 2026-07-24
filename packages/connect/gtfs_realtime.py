"""Adapter: GTFS-Realtime FeedMessage entities -> Outcome (v0.1).

Status: **Demonstrated** only. This maps *open public real-time transit data*
(GTFS-Realtime, the most widely deployed real-time transit standard) -- the
Apache-2.0 GTFS-Realtime specification example feeds and an open agency feed
snapshot, not consented operator data. Nothing here may be promoted to
"Validated" on the strength of this adapter alone, per
architecture/decisions/0001.

This is a deliberately *different-in-kind* adapter against the same
packages.connect.adapter.SourceAdapter contract as reference_agency_trips.py,
tlc_trips.py, tides_trips.py, and gtfs_flex.py -- and the reason it is different
is the whole point of the packet:

The first four adapters all map a *request/booking* record onto ServiceRequest.
GTFS-Realtime is NOT request-level. It carries **operational** signals about a
fixed-route (or, increasingly, flex) network in motion:

- ``VehiclePosition``: where a vehicle is right now, its status
  (INCOMING_AT / STOPPED_AT / IN_TRANSIT_TO), occupancy, and a timestamp.
- ``TripUpdate``: per-stop arrival/departure *predictions* and schedule
  deviations (delays) for a trip, plus SKIPPED/added stop decisions.
- ``Alert``: rider-facing service disruption messaging.

None of these is a rider request, so mapping them onto ServiceRequest would be
dishonest (there is no rider, no booking, no requested_at). The closest
canonical *operational* record is ``packages.canonical.entities.Outcome`` -- the
only canonical entity that models an operational result rather than a request:
``served``, ``actual_pickup_at``, ``on_time``, ``excess_ride_time_minutes``,
``deadhead_minutes``. So Outcome is the target here.

THE HONEST GAP (flag for the canonical contract, next ADR 0030+)
----------------------------------------------------------------
Outcome is a thin, *rider-request-keyed* record: it references a ``request_id``
(a ServiceRequest) and a ``tenant_id`` and asks "was this request served, on
time." GTFS-Realtime data is keyed by ``(trip, stop, vehicle)`` and has **no
rider request at all**. Mapping GTFS-RT onto Outcome therefore forces two
honest compromises, both recorded as semantic loss on every mapping:

1. ``request_id`` must be a *synthetic* per-entity id that references no
   ServiceRequest in the store -- there is no request to point at. This is the
   core mismatch.
2. Outcome carries **no operational context fields** -- no stop_id, no
   vehicle_id, no route_id, no position, no occupancy. Almost everything a
   GTFS-RT entity actually says is therefore semantic loss, because the
   canonical model has nowhere to put it.

The useful finding: the canonical contract has **no first-class operational /
telemetry entity** (a ``VehicleTelemetry`` or ``StopTimeObservation`` keyed by
trip/stop/vehicle and NOT by a rider request). Until it does, GTFS-Realtime --
the single most widely deployed transit-integration surface in the world -- can
only be mapped by squinting at the rider-outcome record. That gap, not this
adapter, is the real output of this packet.

WHAT MAPS, AND WHAT IS QUARANTINED
----------------------------------
An Outcome is an *observed result*. So this adapter emits one only from a
GTFS-RT signal that carries observed/decided content, and quarantines the rest
(mapping rule 7: quarantine rather than guess) with a reason that names the
canonical gap:

- ``VehiclePosition`` with ``current_status == STOPPED_AT`` and a timestamp and
  a stop_id: an **observed arrival** -- the one genuinely-observed instant a
  vehicle feed gives. -> Outcome(served=True, actual_pickup_at=timestamp). An
  in-transit / incoming position is live telemetry with no observed arrival ->
  quarantined.
- ``TripUpdate`` stop_time_update with ``schedule_relationship == SKIPPED``: an
  observed decision the stop will NOT be served -> Outcome(served=False).
- ``TripUpdate`` stop_time_update that predicts an arrival/departure (a
  ``time`` or a ``delay``): a *prediction*, not an observation. Outcome is
  observed-only and has no predicted-time field, so ``actual_pickup_at`` stays
  None; ``on_time`` is *derived from the predicted delay* as an explicit
  coercion (|delay| <= _ON_TIME_TOLERANCE_SECONDS) and the predicted time
  itself is recorded as loss. A stop_time_update that is neither SKIPPED nor
  carries any time/delay is quarantined (no outcome content).
- ``Alert``: rider/agency service messaging, not an operational outcome ->
  quarantined.

GTFS-Realtime timestamps are POSIX epoch seconds, which are unambiguously UTC --
so, unlike the CSV/naive-local adapters in this repo, no timezone coercion is
needed here (a small but real fidelity win worth noting).

The reader (``read_gtfs_realtime_feed`` / ``feed_message_to_rows``) is the only
part that needs the protobuf bindings; ``GtfsRealtimeAdapter.parse`` operates on
plain dicts, so the mapping logic is fully testable without protobuf and the
real-feed test skips cleanly if the bindings or the acquired sample are absent.

TODS (Transit Operational Data Standard) -- Specified, not built
----------------------------------------------------------------
The packet asked whether a TODS mapping was also tractable. It is **deferred as
Specified**, deliberately, for the same reason this adapter's gap exists. TODS
describes *operational* structures -- runs, blocks, pieces-of-work, deadhead
segments, and driver/vehicle assignments -- almost none of which have a
canonical home today: ``deadhead_minutes`` lives on Outcome and ``ScheduleRun``
touches solver runs, but there is no canonical ``Block`` / ``RunCut`` /
``PieceOfWork`` entity, and (as above) no request-independent operational
entity. Half-building a TODS adapter would mean routing most of TODS straight to
semantic loss against a canonical model that is not yet shaped for operational
scheduling data, and no rights-clean TODS sample was acquired into the estate.
The honest move is to mark it Specified and let the same gap-driven canonical
work (an operational entity family) land first. See the packet report / ADR.

Not wired into packages/connect/__init__.py by this change (owned-path boundary
with parallel work); import directly:
``from packages.connect.gtfs_realtime import GtfsRealtimeAdapter``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from packages.canonical import (
    Outcome,
    RequestId,
    TenantId,
    new_id,
)
from packages.connect.adapter import AdapterResult, QuarantinedRow, SemanticLossRecord

# The protobuf bindings are only needed to *read* a .pb / .asciipb feed into
# rows. The mapping (parse) works on plain dicts, so it -- and every fixture /
# adversarial test that feeds dicts -- runs even where the bindings are absent.
try:  # pragma: no cover - import guard
    from google.transit import gtfs_realtime_pb2 as _gtfs_rt
    from google.protobuf import text_format as _text_format

    BINDINGS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only where the dep is missing
    _gtfs_rt = None
    _text_format = None
    BINDINGS_AVAILABLE = False


# An arrival within this many seconds of schedule is treated as "on time". This
# is an adapter-chosen threshold, NOT a value carried by the feed, and it is
# recorded as such in the on_time coercion note below.
_ON_TIME_TOLERANCE_SECONDS = 60

# Reader-managed context keys attached to every row. They are adapter context,
# not source fields, so they are never reported as semantic loss (mirrors
# gtfs_flex._CONTEXT_KEYS).
_CONTEXT_KEYS = frozenset(
    {
        "_gtfs_rt_kind",
        "entity_id",
        "feed_gtfs_realtime_version",
        "feed_incrementality",
        "feed_timestamp",
        "_stop_time_update_index",
        "_stop_time_update_count",
        "_stop_time_update_present",
    }
)

# Per-kind meaning of each GTFS-RT field this adapter surfaces but Outcome v0.1
# has no home for. Present (non-None) values are reported as `dropped` semantic
# loss; absent ones carry no signal and are not reported.
_VEHICLE_UNMAPPED_REASONS = {
    "trip_id": "GTFS trip the vehicle is running; Outcome has no trip reference field",
    "route_id": "GTFS route the vehicle is running; Outcome has no route field",
    "direction_id": "trip direction; no Outcome field",
    "trip_start_date": "the trip's service date; no Outcome field",
    "trip_start_time": "frequency-based trip start time; no Outcome field",
    "trip_schedule_relationship": "trip-level schedule relationship; no Outcome field",
    "vehicle_id": (
        "identifies the vehicle observed at the stop; Outcome is keyed to a rider "
        "request, not a vehicle, so there is nowhere to record which vehicle "
        "produced this arrival"
    ),
    "vehicle_label": "human-readable vehicle label; no Outcome field",
    "vehicle_license_plate": "vehicle licence plate; no Outcome field",
    "position_latitude": "live vehicle latitude -- pure telemetry, no canonical home",
    "position_longitude": "live vehicle longitude -- pure telemetry, no canonical home",
    "position_bearing": "vehicle bearing; no canonical home",
    "position_speed": "vehicle speed; no canonical home",
    "position_odometer": "vehicle odometer; no canonical home",
    "current_stop_sequence": "index of the stop within the trip; no Outcome field",
    "stop_id": (
        "the stop the vehicle is observed at -- the WHERE of this arrival. Outcome "
        "records only that a (synthetic) request was served, never at which stop, "
        "so the stop identity is lost"
    ),
    "congestion_level": "network congestion around the vehicle; no canonical home",
    "occupancy_status": (
        "how full the vehicle is (a genuine demand signal); Outcome has no occupancy "
        "or load field"
    ),
    "occupancy_percentage": "occupancy as a percentage; no canonical home",
}

_TRIP_UPDATE_UNMAPPED_REASONS = {
    "trip_id": "GTFS trip this update is for; Outcome has no trip reference field",
    "route_id": "GTFS route; no Outcome field",
    "direction_id": "trip direction; no Outcome field",
    "trip_start_date": "the trip's service date; no Outcome field",
    "trip_start_time": "frequency-based trip start time; no Outcome field",
    "trip_schedule_relationship": "trip-level schedule relationship; no Outcome field",
    "vehicle_id": "vehicle serving the trip; no Outcome field (Outcome is request-keyed)",
    "vehicle_label": "human-readable vehicle label; no Outcome field",
    "trip_update_timestamp": "when this prediction was generated; no Outcome field",
    "trip_update_delay": "trip-level delay; superseded by the per-stop delay used for on_time",
    "stop_id": (
        "the stop this prediction is for -- the WHERE. Outcome has no stop field, so "
        "the stop identity is lost"
    ),
    "current_stop_sequence": "index of the stop within the trip; no Outcome field",
    "stop_sequence": "index of the stop within the trip; no Outcome field",
    "arrival_uncertainty": "GTFS-RT uncertainty (seconds) on the arrival prediction; no canonical home",
    "departure_uncertainty": "GTFS-RT uncertainty (seconds) on the departure prediction; no canonical home",
    "departure_delay": "predicted departure schedule deviation; on_time is derived from arrival where present",
}

_ALERT_FIELDS = frozenset(
    {
        "alert_cause",
        "alert_effect",
        "alert_header_text",
        "alert_description_text",
        "alert_informed_entity_count",
    }
)


class _UnmappableValue(ValueError):
    """Internal signal that a field value cannot become canonical; caught in
    parse() and turned into a QuarantinedRow rather than propagating."""


def _present(value: object) -> bool:
    """A reader-produced field is absent when it is None or an empty/whitespace
    string. GTFS-RT numeric 0 (e.g. delay == 0, meaning exactly on time) IS a
    signal and is treated as present."""
    return value is not None and not (isinstance(value, str) and value.strip() == "")


def _epoch_to_utc(column: str, raw_value: object) -> datetime:
    """A GTFS-RT POSIX epoch-seconds timestamp -> a UTC datetime. Epoch is
    unambiguously UTC, so there is no timezone coercion here (unlike the naive
    CSV adapters)."""
    try:
        seconds = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise _UnmappableValue(f"unparseable {column} epoch timestamp {raw_value!r}") from exc
    if seconds <= 0:
        raise _UnmappableValue(f"{column} epoch timestamp is not positive: {seconds}")
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _synthetic_request_note() -> SemanticLossRecord:
    return SemanticLossRecord(
        source_field="<no rider request in GTFS-Realtime>",
        source_value=None,
        reason=(
            "GTFS-Realtime is fixed-route/operational data with no rider request, booking, "
            "or ServiceRequest of any kind. Outcome.request_id is a mandatory reference to a "
            "ServiceRequest; here it is a synthetic, non-joinable per-entity placeholder that "
            "references NO ServiceRequest in the store. This is the core operational-vs-request "
            "model mismatch: the canonical contract has no request-independent operational entity "
            "(a VehicleTelemetry / StopTimeObservation) for this data to key on"
        ),
        disposition="coerced",
    )


def _report_unmapped(
    raw_row: dict, reasons: dict[str, str], known: frozenset[str]
) -> list[SemanticLossRecord]:
    """One `dropped` loss per present, documented-but-unmapped field, plus one
    `unmapped_extension` per key outside the schema this adapter was written
    against (mirrors the sibling adapters' two-tier reporting)."""
    losses: list[SemanticLossRecord] = []
    for column, reason in reasons.items():
        value = raw_row.get(column)
        if _present(value):
            losses.append(
                SemanticLossRecord(
                    source_field=column,
                    source_value=str(value),
                    reason=reason,
                    disposition="dropped",
                )
            )
    for column, value in raw_row.items():
        if column in _CONTEXT_KEYS or column in known:
            continue
        losses.append(
            SemanticLossRecord(
                source_field=column,
                source_value=str(value) if _present(value) else None,
                reason="not part of the GTFS-Realtime schema this adapter was written against",
                disposition="unmapped_extension",
            )
        )
    return losses


class GtfsRealtimeAdapter:
    """Maps one GTFS-Realtime signal (a VehiclePosition, or one exploded
    TripUpdate stop_time_update, produced by ``feed_message_to_rows``) onto an
    ``Outcome`` -- the closest canonical *operational* record -- or an explicit
    quarantine where GTFS-RT's operational model has no honest canonical home.

    ``recorded_at`` is the adapter run's own transaction time; it is not read
    from the feed. The feed's own header/entity timestamps are valid-time.
    """

    adapter_name = "gtfs-realtime-outcome"
    adapter_version = "0.1.0"

    def __init__(self, tenant_id: TenantId, *, recorded_at: datetime) -> None:
        self._tenant_id = tenant_id
        self._recorded_at = recorded_at

    # -- entry point -------------------------------------------------------
    def parse(self, raw_row: dict) -> AdapterResult[Outcome]:
        kind = raw_row.get("_gtfs_rt_kind")
        if kind == "vehicle_position":
            return self._parse_vehicle_position(raw_row)
        if kind == "trip_update_stop":
            return self._parse_trip_update_stop(raw_row)
        if kind == "alert":
            return self._quarantine(
                raw_row,
                "GTFS-Realtime Alert is rider/agency service-disruption messaging, not an "
                "operational outcome; the canonical contract has no home for it",
            )
        return self._quarantine(
            raw_row,
            f"unrecognized or absent _gtfs_rt_kind {kind!r}: entity carries no "
            "vehicle_position / trip_update_stop / alert content to map",
            failed_field="_gtfs_rt_kind",
        )

    # -- VehiclePosition ---------------------------------------------------
    def _parse_vehicle_position(self, raw_row: dict) -> AdapterResult[Outcome]:
        status = raw_row.get("current_status")
        if status != "STOPPED_AT":
            return self._quarantine(
                raw_row,
                f"VehiclePosition current_status={status!r} is live in-motion telemetry, not an "
                "observed arrival; a vehicle that is IN_TRANSIT_TO / INCOMING_AT has produced no "
                "arrival to record as an Outcome, and its live position has no canonical home",
                failed_field="current_status",
            )
        if not _present(raw_row.get("stop_id")):
            return self._quarantine(
                raw_row,
                "VehiclePosition is STOPPED_AT but carries no stop_id -- a stop arrival with no "
                "stop is malformed",
                failed_field="stop_id",
            )

        timestamp_raw = raw_row.get("vehicle_timestamp")
        timestamp_source = "vehicle.timestamp"
        if not _present(timestamp_raw):
            timestamp_raw = raw_row.get("feed_timestamp")
            timestamp_source = "feed header timestamp"
        if not _present(timestamp_raw):
            return self._quarantine(
                raw_row,
                "STOPPED_AT VehiclePosition has neither a vehicle timestamp nor a feed header "
                "timestamp to anchor the arrival instant",
                failed_field="vehicle_timestamp",
            )
        try:
            actual_pickup_at = _epoch_to_utc(timestamp_source, timestamp_raw)
        except _UnmappableValue as exc:
            return self._quarantine(raw_row, str(exc), failed_field="vehicle_timestamp")

        semantic_loss = [
            _synthetic_request_note(),
            SemanticLossRecord(
                source_field="current_status",
                source_value="STOPPED_AT",
                reason=(
                    "a STOPPED_AT vehicle is observed servicing this stop now; that observed "
                    "arrival is mapped to Outcome.actual_pickup_at (from "
                    f"{timestamp_source}={actual_pickup_at.isoformat()}), the one genuinely-"
                    "observed instant a vehicle feed provides"
                ),
                disposition="coerced",
            ),
            SemanticLossRecord(
                source_field="<Outcome.served has no GTFS-RT source>",
                source_value=None,
                reason=(
                    "GTFS-Realtime carries no rider-level served/no-show status. served=True here "
                    "encodes 'the vehicle serviced this stop', NOT that any specific rider request "
                    "was fulfilled -- there is no rider request in the feed"
                ),
                disposition="coerced",
            ),
            SemanticLossRecord(
                source_field="<Outcome.on_time has no GTFS-RT source in a VehiclePosition>",
                source_value=None,
                reason=(
                    "a VehiclePosition carries no schedule reference, so on-time-ness cannot be "
                    "derived; on_time is left None rather than guessed (contrast TripUpdate, which "
                    "does carry a delay)"
                ),
                disposition="dropped",
            ),
        ]
        # current_status and vehicle_timestamp are consumed by the mapping above
        # (reported via the explicit notes / actual_pickup_at), so they are known,
        # not vendor extensions.
        vehicle_known = frozenset(_VEHICLE_UNMAPPED_REASONS) | {"current_status", "vehicle_timestamp"}
        semantic_loss.extend(_report_unmapped(raw_row, _VEHICLE_UNMAPPED_REASONS, vehicle_known))

        outcome = Outcome(
            tenant_id=self._tenant_id,
            request_id=new_id(RequestId),
            served=True,
            actual_pickup_at=actual_pickup_at,
            on_time=None,
        )
        return AdapterResult(record=outcome, semantic_loss=tuple(semantic_loss))

    # -- TripUpdate (one exploded stop_time_update) ------------------------
    def _parse_trip_update_stop(self, raw_row: dict) -> AdapterResult[Outcome]:
        if not raw_row.get("_stop_time_update_present", True):
            return self._quarantine(
                raw_row,
                "TripUpdate entity carries no stop_time_update to map",
                failed_field="_stop_time_update_present",
            )

        sr = raw_row.get("stop_schedule_relationship") or "SCHEDULED"
        arrival_time = raw_row.get("arrival_time")
        arrival_delay = raw_row.get("arrival_delay")
        departure_time = raw_row.get("departure_time")
        departure_delay = raw_row.get("departure_delay")
        has_prediction = any(
            _present(v) for v in (arrival_time, arrival_delay, departure_time, departure_delay)
        )

        if sr == "SKIPPED":
            served = False
            on_time = None
            served_note = SemanticLossRecord(
                source_field="stop_schedule_relationship",
                source_value="SKIPPED",
                reason=(
                    "an observed decision that this stop will NOT be served -> Outcome(served=False). "
                    "This is the one TripUpdate signal that maps cleanly and without coercion onto an "
                    "Outcome field, because SKIPPED is a decision, not a prediction"
                ),
                disposition="coerced",
            )
        else:
            if not has_prediction:
                return self._quarantine(
                    raw_row,
                    f"stop_time_update (schedule_relationship={sr}) carries neither an "
                    "arrival/departure time nor a delay, and is not SKIPPED -- it has no "
                    "outcome content to map",
                    failed_field="stop_schedule_relationship",
                )
            served = True
            delay_used = arrival_delay if _present(arrival_delay) else departure_delay
            if _present(delay_used):
                try:
                    on_time = abs(int(delay_used)) <= _ON_TIME_TOLERANCE_SECONDS
                except (TypeError, ValueError) as exc:
                    return self._quarantine(
                        raw_row, f"unparseable delay {delay_used!r}", failed_field="arrival_delay"
                    )
            else:
                on_time = None
            served_note = SemanticLossRecord(
                source_field="<Outcome.served has no GTFS-RT source>",
                source_value=None,
                reason=(
                    "GTFS-Realtime carries no rider-level served status. served=True here encodes "
                    "'this stop is predicted to be served' (schedule_relationship="
                    f"{sr}), NOT that any rider request was fulfilled"
                ),
                disposition="coerced",
            )

        semantic_loss = [_synthetic_request_note(), served_note]

        if served and on_time is not None:
            delay_used = arrival_delay if _present(arrival_delay) else departure_delay
            semantic_loss.append(
                SemanticLossRecord(
                    source_field="arrival_delay",
                    source_value=str(delay_used),
                    reason=(
                        "Outcome.on_time is DERIVED from a *predicted* schedule deviation (|delay| <= "
                        f"{_ON_TIME_TOLERANCE_SECONDS}s, an adapter-chosen threshold not carried by the "
                        "feed). This coerces a prediction into an observed-on-time field: it is an "
                        "estimate of on-time-ness, not an observed fact, because a TripUpdate is a "
                        "forecast of arrival, not a record of one"
                    ),
                    disposition="coerced",
                )
            )
        if _present(arrival_time) or _present(departure_time):
            semantic_loss.append(
                SemanticLossRecord(
                    source_field="arrival_time/departure_time",
                    source_value=f"{arrival_time}/{departure_time}",
                    reason=(
                        "predicted arrival/departure instants. Outcome is an OBSERVED-result record with "
                        "no predicted-time field, so these are dropped: actual_pickup_at is left None "
                        "(a prediction is not an observation). The only predicted-time field in the "
                        "canonical contract is RequestTimes.predicted_pickup_at, which lives on a "
                        "ServiceRequest and is request-keyed -- unavailable for request-less GTFS-RT"
                    ),
                    disposition="dropped",
                )
            )
        if raw_row.get("_stop_time_update_count", 1) > 1:
            semantic_loss.append(
                SemanticLossRecord(
                    source_field="<sibling stop_time_updates in this TripUpdate>",
                    source_value=str(raw_row.get("_stop_time_update_count")),
                    reason=(
                        "a TripUpdate predicts many stops; the reader explodes it to one row per "
                        "stop_time_update so each maps to at most one Outcome. This row represents "
                        f"stop index {raw_row.get('_stop_time_update_index')} of "
                        f"{raw_row.get('_stop_time_update_count')}"
                    ),
                    disposition="dropped",
                )
            )

        known = frozenset(_TRIP_UPDATE_UNMAPPED_REASONS) | {
            "arrival_time",
            "departure_time",
            "arrival_delay",
            "stop_schedule_relationship",
        }
        semantic_loss.extend(_report_unmapped(raw_row, _TRIP_UPDATE_UNMAPPED_REASONS, known))

        outcome = Outcome(
            tenant_id=self._tenant_id,
            request_id=new_id(RequestId),
            served=served,
            actual_pickup_at=None,
            on_time=on_time,
        )
        return AdapterResult(record=outcome, semantic_loss=tuple(semantic_loss))

    # -- helper ------------------------------------------------------------
    def _quarantine(
        self, raw_row: dict, reason: str, *, failed_field: str | None = None
    ) -> AdapterResult[Outcome]:
        return AdapterResult(
            quarantine=QuarantinedRow(raw_row=dict(raw_row), reason=reason, failed_field=failed_field)
        )


# ---------------------------------------------------------------------------
# Reader: GTFS-RT FeedMessage -> adapter-input rows (needs the protobuf bindings)
# ---------------------------------------------------------------------------


def _enum_name(enum_wrapper, value) -> str:
    try:
        return enum_wrapper.Name(value)
    except (ValueError, KeyError):  # pragma: no cover - defensive
        return str(value)


def _get(msg, field: str):
    """Return a singular proto field's value if set (proto2 presence), else
    None. Enum fields are returned as their symbolic name via `enum_names`."""
    if not msg.HasField(field):
        return None
    return getattr(msg, field)


def _trip_descriptor_fields(trip, prefix_map: dict[str, str]) -> dict:
    """Flatten a TripDescriptor into the row keys the adapter expects."""
    row = {
        prefix_map["trip_id"]: _get(trip, "trip_id"),
        prefix_map["route_id"]: _get(trip, "route_id"),
        prefix_map["direction_id"]: _get(trip, "direction_id"),
        prefix_map["trip_start_date"]: _get(trip, "start_date"),
        prefix_map["trip_start_time"]: _get(trip, "start_time"),
    }
    sr = _get(trip, "schedule_relationship")
    row[prefix_map["trip_schedule_relationship"]] = (
        _enum_name(_gtfs_rt.TripDescriptor.ScheduleRelationship, sr) if sr is not None else None
    )
    return row


_TRIP_KEYS = {
    "trip_id": "trip_id",
    "route_id": "route_id",
    "direction_id": "direction_id",
    "trip_start_date": "trip_start_date",
    "trip_start_time": "trip_start_time",
    "trip_schedule_relationship": "trip_schedule_relationship",
}


def _vehicle_row(entity, header_ctx: dict) -> dict:
    v = entity.vehicle
    row = dict(header_ctx)
    row.update(
        {
            "_gtfs_rt_kind": "vehicle_position",
            "entity_id": entity.id,
        }
    )
    row.update(_trip_descriptor_fields(v.trip, _TRIP_KEYS))
    row["vehicle_id"] = _get(v.vehicle, "id")
    row["vehicle_label"] = _get(v.vehicle, "label")
    row["vehicle_license_plate"] = _get(v.vehicle, "license_plate")
    if v.HasField("position"):
        row["position_latitude"] = _get(v.position, "latitude")
        row["position_longitude"] = _get(v.position, "longitude")
        row["position_bearing"] = _get(v.position, "bearing")
        row["position_speed"] = _get(v.position, "speed")
        row["position_odometer"] = _get(v.position, "odometer")
    row["current_stop_sequence"] = _get(v, "current_stop_sequence")
    row["stop_id"] = _get(v, "stop_id")
    cs = _get(v, "current_status")
    row["current_status"] = (
        _enum_name(_gtfs_rt.VehiclePosition.VehicleStopStatus, cs) if cs is not None else None
    )
    row["vehicle_timestamp"] = _get(v, "timestamp")
    cl = _get(v, "congestion_level")
    row["congestion_level"] = (
        _enum_name(_gtfs_rt.VehiclePosition.CongestionLevel, cl) if cl is not None else None
    )
    os_ = _get(v, "occupancy_status")
    row["occupancy_status"] = (
        _enum_name(_gtfs_rt.VehiclePosition.OccupancyStatus, os_) if os_ is not None else None
    )
    row["occupancy_percentage"] = _get(v, "occupancy_percentage")
    return row


def _trip_update_rows(entity, header_ctx: dict) -> Iterator[dict]:
    tu = entity.trip_update
    base = dict(header_ctx)
    base.update({"entity_id": entity.id, "_gtfs_rt_kind": "trip_update_stop"})
    base.update(_trip_descriptor_fields(tu.trip, _TRIP_KEYS))
    base["vehicle_id"] = _get(tu.vehicle, "id") if tu.HasField("vehicle") else None
    base["vehicle_label"] = _get(tu.vehicle, "label") if tu.HasField("vehicle") else None
    base["trip_update_timestamp"] = _get(tu, "timestamp")
    base["trip_update_delay"] = _get(tu, "delay")

    stus = list(tu.stop_time_update)
    if not stus:
        row = dict(base)
        row["_stop_time_update_present"] = False
        row["_stop_time_update_count"] = 0
        yield row
        return

    for index, stu in enumerate(stus):
        row = dict(base)
        row["_stop_time_update_present"] = True
        row["_stop_time_update_index"] = index
        row["_stop_time_update_count"] = len(stus)
        row["stop_sequence"] = _get(stu, "stop_sequence")
        row["stop_id"] = _get(stu, "stop_id")
        if stu.HasField("arrival"):
            row["arrival_time"] = _get(stu.arrival, "time")
            row["arrival_delay"] = _get(stu.arrival, "delay")
            row["arrival_uncertainty"] = _get(stu.arrival, "uncertainty")
        if stu.HasField("departure"):
            row["departure_time"] = _get(stu.departure, "time")
            row["departure_delay"] = _get(stu.departure, "delay")
            row["departure_uncertainty"] = _get(stu.departure, "uncertainty")
        srr = _get(stu, "schedule_relationship")
        row["stop_schedule_relationship"] = (
            _enum_name(_gtfs_rt.TripUpdate.StopTimeUpdate.ScheduleRelationship, srr)
            if srr is not None
            else None
        )
        yield row


def _alert_row(entity, header_ctx: dict) -> dict:
    a = entity.alert
    row = dict(header_ctx)
    row.update({"entity_id": entity.id, "_gtfs_rt_kind": "alert"})
    ca = _get(a, "cause")
    row["alert_cause"] = _enum_name(_gtfs_rt.Alert.Cause, ca) if ca is not None else None
    ef = _get(a, "effect")
    row["alert_effect"] = _enum_name(_gtfs_rt.Alert.Effect, ef) if ef is not None else None
    row["alert_header_text"] = (
        a.header_text.translation[0].text if a.header_text.translation else None
    )
    row["alert_description_text"] = (
        a.description_text.translation[0].text if a.description_text.translation else None
    )
    row["alert_informed_entity_count"] = len(a.informed_entity) or None
    return row


def feed_message_to_rows(feed) -> Iterator[dict]:
    """Flatten a parsed GTFS-Realtime ``FeedMessage`` into adapter-input rows,
    one per mappable signal:

    - one row per ``VehiclePosition`` entity,
    - one row per ``TripUpdate`` ``stop_time_update`` (exploded, so each maps to
      at most one Outcome; a TripUpdate with none yields a single sentinel row
      that quarantines rather than vanishing),
    - one row per ``Alert`` entity,
    - one ``unknown`` row for an entity with none of the three.

    Requires the protobuf bindings only to read enum names; the rows it yields
    are plain JSON-safe dicts the dict-only adapter can map.
    """
    if not BINDINGS_AVAILABLE:  # pragma: no cover - import guard
        raise RuntimeError(
            "gtfs-realtime-bindings is not installed; feed_message_to_rows needs it to read "
            "enum names. Install it (it is a declared dependency) or feed the adapter dicts directly."
        )
    header = feed.header
    header_ctx = {
        "feed_gtfs_realtime_version": _get(header, "gtfs_realtime_version"),
        "feed_incrementality": _enum_name(
            _gtfs_rt.FeedHeader.Incrementality, header.incrementality
        ),
        "feed_timestamp": _get(header, "timestamp"),
    }
    for entity in feed.entity:
        if entity.HasField("vehicle"):
            yield _vehicle_row(entity, header_ctx)
        elif entity.HasField("trip_update"):
            yield from _trip_update_rows(entity, header_ctx)
        elif entity.HasField("alert"):
            yield _alert_row(entity, header_ctx)
        else:
            row = dict(header_ctx)
            row.update({"entity_id": entity.id, "_gtfs_rt_kind": "unknown"})
            yield row


def read_gtfs_realtime_feed(path: str | Path) -> Iterator[dict]:
    """Read an acquired GTFS-Realtime feed file and yield adapter-input rows.

    Supports binary protobuf (``.pb`` / ``.bin``) via ``ParseFromString`` and
    text-format protobuf (``.asciipb`` / ``.textpb`` / ``.pbtext`` / ``.txt``)
    via ``text_format.Parse`` -- the latter is how the Apache-2.0 GTFS-Realtime
    spec examples are published. The whole (small) feed is read into memory and
    the file closed before rows are yielded.
    """
    if not BINDINGS_AVAILABLE:  # pragma: no cover - import guard
        raise RuntimeError(
            "gtfs-realtime-bindings is not installed; read_gtfs_realtime_feed cannot parse a feed. "
            "Install it (it is a declared dependency)."
        )
    path = Path(path)
    feed = _gtfs_rt.FeedMessage()
    text_suffixes = {".asciipb", ".textpb", ".pbtext", ".txt"}
    if path.suffix.lower() in text_suffixes:
        _text_format.Parse(path.read_text(encoding="utf-8"), feed)
    else:
        feed.ParseFromString(path.read_bytes())
    yield from feed_message_to_rows(feed)
