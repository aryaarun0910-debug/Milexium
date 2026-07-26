"""Adapter: GTFS-Realtime FeedMessage entities -> operational observations (v0.1).

Status: **Demonstrated** only. This maps *open public real-time transit data*
(GTFS-Realtime, the most widely deployed real-time transit standard) -- the
Apache-2.0 GTFS-Realtime specification example feeds and an open agency feed
snapshot, not consented operator data. Nothing here may be promoted to
"Validated" on the strength of this adapter alone, per
forge/knowledge/architecture/decisions/0001.

This is a deliberately *different-in-kind* adapter against the same
themis.connect.adapter.SourceAdapter contract as reference_agency_trips.py,
tlc_trips.py, tides_trips.py, and gtfs_flex.py. The first four adapters all map a
*request/booking* record onto ServiceRequest. GTFS-Realtime is NOT request-level;
it carries **operational** telemetry about a fixed-route (or flex) network in
motion:

- ``VehiclePosition``: where a vehicle is right now, its status
  (INCOMING_AT / STOPPED_AT / IN_TRANSIT_TO), occupancy, and a timestamp.
- ``TripUpdate``: per-stop arrival/departure *predictions* and schedule
  deviations (delays) for a trip, plus SKIPPED/added stop decisions.
- ``Alert``: rider-facing service disruption messaging.

THE GAP -- NOW CLOSED (ADR-0031 -> MX-A-OPS-ENTITY-002)
------------------------------------------------------
ADR-0031 recorded this adapter's first cut squashing GTFS-RT onto ``Outcome`` --
the only operational-*result* entity that then existed. Outcome is
rider-request-keyed: it references a ``request_id`` (a ServiceRequest). GTFS-RT is
keyed by ``(trip, stop, vehicle)`` and has **no rider request at all**, so that
mapping forced two compromises recorded as loss on every row: (1) ``request_id``
was a *synthetic placeholder referencing no ServiceRequest*; (2) Outcome had **no
operational-context fields** (no stop_id, vehicle_id, route_id, position,
occupancy), so almost everything a GTFS-RT entity said was semantic loss.

That gap is now closed. The canonical contract has a first-class,
request-INDEPENDENT operational entity family --
``themis.canonical.entities.VehicleObservation`` and ``StopTimeObservation`` --
keyed by their own ``observation_id`` and ``(tenant, vehicle/trip/stop,
observed_at)``, NOT by a rider request. This adapter now maps onto them:

- ``VehiclePosition`` -> ``VehicleObservation``. position (latitude/longitude/
  bearing/speed), occupancy (status + percentage), current_status, and the
  stop/vehicle/trip/route refs all have real homes. **Every** vehicle position is
  now a valid observation -- the STOPPED_AT-only gate is gone, because an
  in-transit position is exactly what a telemetry entity is for. No synthetic
  request id is minted: ``observation_id`` is the record's OWN key.
- ``TripUpdate`` stop_time_update -> ``StopTimeObservation``. stop_ref,
  stop_sequence, schedule_relationship, predicted arrival/departure times, and
  the arrival/departure delays all have homes. Each exploded stop_time_update is
  its own observation (no sibling-stop loss). GTFS-RT carries *predictions*, so
  they land in ``predicted_arrival_at`` / delays; the ``observed_*`` fields stay
  None (a prediction is not a record of what happened) -- the predicted-vs-actual
  discipline is preserved, not coerced away as it was under Outcome.on_time.
- ``Alert`` -> still **quarantined**: rider/agency service-disruption messaging
  is not a vehicle or stop-time observation; the operational entity family has no
  home for it, and inventing one would be the same over-reach this packet exists
  to avoid.

RESIDUAL LOSS (honest -- much smaller, not zero)
------------------------------------------------
The observation entities model the operational context GTFS-RT centrally carries,
not every optional field. What remains as recorded semantic loss is genuinely
homeless detail: trip ``direction_id`` / ``start_date`` / ``start_time`` /
trip-level schedule_relationship, human vehicle ``label`` / ``license_plate``,
``odometer``, ``congestion_level``, ``current_stop_sequence`` (on a vehicle),
trip-level ``delay``, and prediction ``uncertainty``. Every such present field is
still reported (``dropped``), and any key outside the schema this adapter was
written against still surfaces as ``unmapped_extension`` -- never a silent drop
(blueprint/03 mapping discipline). The headline change is that the *synthetic
request id* and the *whole-of-operational-context* loss are gone.

THE VEHICLE REFERENCE, AND THE RUN REFERENCE THAT IS NOT THERE (ADR-0054 ->
MX-B-ADAPTER-REFS-009)
---------------------------------------------------------------------------
Of the two fields the deadhead teardown can chain on, this feed carries exactly
one, and the honest outcome differs per field:

- ``vehicle.id`` IS a genuine vehicle reference and ALREADY reaches
  ``VehicleObservation.vehicle_ref`` -- wired when the observation family landed
  (ADR-0031), not by this packet. What this packet adds is the *proof the chain
  closes*: adapter -> ``VehicleObservation`` -> observation store -> read back ->
  ``VehicleSegment`` -> ``teardown_deadhead``, which nothing demonstrated before.
  ``VehicleSegment.run_ref`` is documented as a "run/block/vehicle id", so
  chaining a vehicle is a first-class use of it -- but the teardown's
  ``run_ref_source`` must then say a VEHICLE was ranked, not a run.
- There is NO run/block reference, and none is invented. See
  ``NO_RUN_REFERENCE_FIELD``: it is recorded as loss on every mapped row.

Absence stays absent on the vehicle side too. GTFS-RT's ``vehicle`` descriptor is
optional, so a trip-keyed position names no vehicle; ``vehicle_ref`` is then
``None`` and is never back-filled from ``vehicle_label``, ``license_plate``,
``trip_id`` or the feed ``entity_id``.

WHAT IS QUARANTINED
-------------------
Only signals with no honest observation to emit (mapping rule 7): an ``Alert``; a
``TripUpdate`` entity carrying no stop_time_update; a stop_time_update with no
stop identity and no prediction content at all; a VehiclePosition with no
timestamp (vehicle nor feed) to anchor ``observed_at``; a malformed epoch; and an
out-of-range latitude/longitude the entity validator rejects. In-transit
telemetry and content-free-but-identified stops are NO LONGER quarantined -- they
are exactly what the observation entities record.

GTFS-Realtime timestamps are POSIX epoch seconds, unambiguously UTC -- so, unlike
the CSV/naive-local adapters in this repo, no timezone coercion is needed here (a
small but real fidelity win). ``observed_at`` is valid time (the vehicle/feed
timestamp); ``recorded_at`` is the adapter run's transaction time.

The reader (``read_gtfs_realtime_feed`` / ``feed_message_to_rows``) is the only
part that needs the protobuf bindings; ``GtfsRealtimeAdapter.parse`` operates on
plain dicts, so the mapping logic is fully testable without protobuf and the
real-feed test skips cleanly if the bindings or the acquired sample are absent.

TODS (Transit Operational Data Standard) -- still Specified, not built
---------------------------------------------------------------------
TODS describes *scheduling* structures -- runs, blocks, pieces-of-work, deadhead
segments -- which are a different family again (a ``Block`` / ``RunCut`` /
``PieceOfWork`` entity), still absent, and no rights-clean TODS sample was
acquired. This packet lands the *telemetry/observation* family it needed; the
scheduling family remains a later Program A step. See ADR-0031 and the packet
report.

Wired into themis/connect/__init__.py: import ``GtfsRealtimeAdapter`` from
``themis.connect`` or directly from this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from pydantic import ValidationError

from themis.canonical import (
    ObservationId,
    StopTimeObservation,
    TenantId,
    VehicleObservation,
    new_id,
)
from themis.connect.adapter import AdapterResult, QuarantinedRow, SemanticLossRecord

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

# RESIDUAL loss: GTFS-RT fields that STILL have no home on VehicleObservation /
# StopTimeObservation (the operational entities model the central operational
# context, not every optional field). Present (non-None) values are reported as
# `dropped` semantic loss; absent ones carry no signal and are not reported. Note
# how much smaller these are than the ADR-0031 Outcome-era lists: position,
# occupancy, status, stop/vehicle/route/trip refs, predicted times and delays are
# no longer here -- they now map.
_VEHICLE_RESIDUAL_REASONS = {
    "direction_id": "trip direction; VehicleObservation models the vehicle, not the trip's direction",
    "trip_start_date": "the trip's service date; no VehicleObservation field",
    "trip_start_time": "frequency-based trip start time; no VehicleObservation field",
    "trip_schedule_relationship": (
        "trip-level schedule relationship; VehicleObservation carries the vehicle's "
        "operational status, not the trip's schedule relationship"
    ),
    "vehicle_label": "human-readable vehicle label; VehicleObservation keeps the id (vehicle_ref), not the label",
    "vehicle_license_plate": "vehicle licence plate; no VehicleObservation field",
    "position_odometer": "vehicle odometer; VehicleObservation models position, not distance travelled",
    "current_stop_sequence": "index of the current stop within the trip; no VehicleObservation field",
    "congestion_level": "network congestion around the vehicle; no VehicleObservation field",
}

NO_RUN_REFERENCE_FIELD = "<no run or block reference in a GTFS-Realtime feed>"
"""MX-B-ADAPTER-REFS-009. The `source_field` under which this adapter records
that GTFS-Realtime carries a VEHICLE reference but no RUN reference.

The distinction is load-bearing. `VehiclePosition.vehicle.id` is a genuine
vehicle identifier and already lands on `VehicleObservation.vehicle_ref`, so a
teardown CAN chain one vehicle's consecutive observations
(`VehicleSegment.run_ref` is documented as "run/block/vehicle id" for exactly
this). What it cannot do is attribute that time to a RUN or a BLOCK:
GTFS-Realtime's `TripDescriptor` carries trip_id / route_id / direction_id /
start_date / start_time / schedule_relationship and NOTHING else. `block_id`
lives in *static* GTFS `trips.txt`, which a realtime feed does not carry, so a
realtime-only pipeline has no run reference to resolve and must not invent one
from `trip_id` -- a trip is one journey along a pattern, a block is a day's
chained work, and the two differ by exactly the deadhead being measured."""

_TRIP_UPDATE_RESIDUAL_REASONS = {
    "direction_id": "trip direction; StopTimeObservation is stop-keyed, not direction-keyed",
    "trip_start_date": "the trip's service date; no StopTimeObservation field",
    "trip_start_time": "frequency-based trip start time; no StopTimeObservation field",
    "trip_schedule_relationship": (
        "trip-level schedule relationship; StopTimeObservation carries the per-STOP "
        "schedule_relationship, not the trip-level one"
    ),
    "vehicle_id": (
        "vehicle serving the trip. StopTimeObservation is stop-keyed and has no vehicle field, "
        "so the reference does NOT survive this mapping. It survives only if the same feed also "
        "publishes a VehiclePosition for that vehicle, which carries it to "
        "VehicleObservation.vehicle_ref -- a TripUpdate-only feed loses it here, and a teardown "
        "built from such a feed has nothing to chain (MX-B-ADAPTER-REFS-009). It is NOT copied "
        "onto the stop observation and no vehicle-keyed record is minted from it, because a "
        "predicted arrival is not evidence that vehicle was anywhere"
    ),
    "vehicle_label": "human-readable vehicle label; no StopTimeObservation field",
    "trip_update_delay": (
        "trip-level delay; StopTimeObservation carries the per-stop arrival/departure "
        "delays, so the trip-level roll-up is not stored"
    ),
    "arrival_uncertainty": "GTFS-RT uncertainty (seconds) on the arrival prediction; no StopTimeObservation field",
    "departure_uncertainty": "GTFS-RT uncertainty (seconds) on the departure prediction; no StopTimeObservation field",
}


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


def _str_or_none(value: object) -> str | None:
    """An absent source field -> None; a present one -> its string form. GTFS-RT
    ids/enums are already strings; this just normalizes empties to None so the
    observation stores a real ref or nothing, never ''."""
    return str(value) if _present(value) else None


def _as_float(value: object) -> float | None:
    """A present numeric field -> float, else None. Unparseable -> _UnmappableValue
    (caught by parse() -> quarantine, never a silent drop)."""
    if not _present(value):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise _UnmappableValue(f"unparseable numeric value {value!r}") from exc


def _as_int(value: object) -> int | None:
    """A present integer field -> int, else None. GTFS-RT delay 0 is a real
    signal (exactly on schedule) and is preserved. Unparseable -> _UnmappableValue."""
    if not _present(value):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise _UnmappableValue(f"unparseable integer value {value!r}") from exc


def _no_run_reference_loss(carried_instead: str) -> SemanticLossRecord:
    """The record that GTFS-Realtime has no run/block reference to carry.

    Emitted on EVERY mapped row, not only where one looks missing: the point is
    that the standard has no such field, which is a property of the format and
    not of the row. `carried_instead` names what the row DID carry, so the record
    can never be misread as "this feed lost its vehicle reference too".
    """
    return SemanticLossRecord(
        source_field=NO_RUN_REFERENCE_FIELD,
        source_value=None,
        reason=(
            "GTFS-Realtime publishes no run, block or piece-of-work identifier. Its TripDescriptor "
            "carries trip_id/route_id/direction_id/start_date/start_time/schedule_relationship and "
            "nothing more; block_id lives in STATIC GTFS trips.txt, which a realtime feed does not "
            "include. So a realtime-only teardown can attribute empty time to a VEHICLE "
            f"(via {carried_instead}, which this row does carry when the feed names one) but never "
            "to a run, and run-level attribution stays ADR-0039 `unattributable` rather than being "
            "inferred. trip_id is NOT used as a substitute: a trip is one journey along a pattern, "
            "a block is a day's chained work, and the difference between them is precisely the "
            "deadhead being measured -- keying on trip_id would report every vehicle's whole day "
            "as a sequence of single-trip runs with no gaps between them, i.e. zero deadhead. "
            "Joining a static GTFS feed to recover trips.block_id is a real option and is NOT done "
            "here: this adapter maps one realtime row and holds no static feed"
        ),
        disposition="dropped",
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
    TripUpdate stop_time_update, produced by ``feed_message_to_rows``) onto a
    request-INDEPENDENT operational observation -- a ``VehicleObservation`` or a
    ``StopTimeObservation`` -- or an explicit quarantine where the signal carries
    no observation to emit (an Alert, a stop-less TripUpdate, an unanchored or
    malformed position).

    ``observed_at`` is valid time (the vehicle/feed timestamp); ``recorded_at`` is
    the adapter run's own transaction time, not read from the feed.
    ``observation_id`` is each record's OWN key -- unlike ADR-0031's synthetic
    ``request_id``, it references nothing it cannot back up.
    """

    adapter_name = "gtfs-realtime-observation"
    adapter_version = "0.1.0"

    def __init__(self, tenant_id: TenantId, *, recorded_at: datetime) -> None:
        self._tenant_id = tenant_id
        self._recorded_at = recorded_at

    # -- entry point -------------------------------------------------------
    def parse(self, raw_row: dict) -> AdapterResult:
        kind = raw_row.get("_gtfs_rt_kind")
        if kind == "vehicle_position":
            return self._parse_vehicle_position(raw_row)
        if kind == "trip_update_stop":
            return self._parse_trip_update_stop(raw_row)
        if kind == "alert":
            return self._quarantine(
                raw_row,
                "GTFS-Realtime Alert is rider/agency service-disruption messaging, not a vehicle "
                "or stop-time observation; the operational entity family has no home for it",
            )
        return self._quarantine(
            raw_row,
            f"unrecognized or absent _gtfs_rt_kind {kind!r}: entity carries no "
            "vehicle_position / trip_update_stop / alert content to map",
            failed_field="_gtfs_rt_kind",
        )

    # -- VehiclePosition -> VehicleObservation -----------------------------
    def _parse_vehicle_position(self, raw_row: dict) -> AdapterResult:
        # Every VehiclePosition is a valid observation now -- an in-transit or
        # incoming vehicle is exactly what a telemetry entity records, so there is
        # no STOPPED_AT gate. Only an unanchored/malformed position is quarantined.
        timestamp_raw = raw_row.get("vehicle_timestamp")
        timestamp_source = "vehicle.timestamp"
        if not _present(timestamp_raw):
            timestamp_raw = raw_row.get("feed_timestamp")
            timestamp_source = "feed header timestamp"
        if not _present(timestamp_raw):
            return self._quarantine(
                raw_row,
                "VehiclePosition has neither a vehicle timestamp nor a feed header timestamp to "
                "anchor observed_at",
                failed_field="vehicle_timestamp",
            )
        try:
            observed_at = _epoch_to_utc(timestamp_source, timestamp_raw)
            latitude = _as_float(raw_row.get("position_latitude"))
            longitude = _as_float(raw_row.get("position_longitude"))
            bearing = _as_float(raw_row.get("position_bearing"))
            speed = _as_float(raw_row.get("position_speed"))
            occupancy_percentage = _as_int(raw_row.get("occupancy_percentage"))
        except _UnmappableValue as exc:
            return self._quarantine(raw_row, str(exc), failed_field="vehicle_timestamp")

        try:
            observation = VehicleObservation(
                observation_id=new_id(ObservationId),
                tenant_id=self._tenant_id,
                # THE reference the deadhead teardown chains on (ADR-0039), read
                # from `vehicle.id` and NOWHERE else. GTFS-RT's `vehicle`
                # descriptor is optional and its `id` is optional within it, so a
                # position keyed only by trip has none -- and that stays None. It
                # is never back-filled from `vehicle_label` (a human display
                # string an agency may reuse or blank), from `license_plate` (a
                # different identifier, and one attached to a keeper), from
                # `trip_id`, or from the feed's `entity_id` (a per-message key
                # that is only incidentally the vehicle id in some feeds).
                vehicle_ref=_str_or_none(raw_row.get("vehicle_id")),
                trip_ref=_str_or_none(raw_row.get("trip_id")),
                route_ref=_str_or_none(raw_row.get("route_id")),
                stop_ref=_str_or_none(raw_row.get("stop_id")),
                current_status=_str_or_none(raw_row.get("current_status")),
                latitude=latitude,
                longitude=longitude,
                bearing=bearing,
                speed=speed,
                occupancy_status=_str_or_none(raw_row.get("occupancy_status")),
                occupancy_percentage=occupancy_percentage,
                observed_at=observed_at,
                recorded_at=self._recorded_at,
            )
        except ValidationError as exc:
            err = exc.errors()[0]
            loc = err.get("loc") or ()
            # This is where an out-of-range latitude/longitude the entity validator
            # rejects becomes a quarantine rather than a silent drop.
            return self._quarantine(
                raw_row,
                f"VehiclePosition rejected by VehicleObservation validation: {err.get('msg')}",
                failed_field=str(loc[0]) if loc else "latitude/longitude",
            )

        # trip_id / route_id / vehicle_id / stop_id / current_status / position_* /
        # occupancy_* and the timestamp are all consumed into the entity above, so
        # they are `known`, not vendor extensions. Only the genuinely-homeless
        # residual fields are reported as loss -- far fewer than the Outcome era.
        vehicle_known = frozenset(_VEHICLE_RESIDUAL_REASONS) | {
            "trip_id",
            "route_id",
            "vehicle_id",
            "stop_id",
            "current_status",
            "vehicle_timestamp",
            "position_latitude",
            "position_longitude",
            "position_bearing",
            "position_speed",
            "occupancy_status",
            "occupancy_percentage",
        }
        semantic_loss = _report_unmapped(raw_row, _VEHICLE_RESIDUAL_REASONS, vehicle_known)
        semantic_loss.append(_no_run_reference_loss("VehicleObservation.vehicle_ref"))
        return AdapterResult(record=observation, semantic_loss=tuple(semantic_loss))

    # -- TripUpdate stop_time_update -> StopTimeObservation ----------------
    def _parse_trip_update_stop(self, raw_row: dict) -> AdapterResult:
        if not raw_row.get("_stop_time_update_present", True):
            return self._quarantine(
                raw_row,
                "TripUpdate entity carries no stop_time_update to observe",
                failed_field="_stop_time_update_present",
            )

        stop_ref = _str_or_none(raw_row.get("stop_id"))
        schedule_relationship = _str_or_none(raw_row.get("stop_schedule_relationship"))
        arrival_time = raw_row.get("arrival_time")
        arrival_delay = raw_row.get("arrival_delay")
        departure_time = raw_row.get("departure_time")
        departure_delay = raw_row.get("departure_delay")
        stop_sequence_raw = raw_row.get("stop_sequence")

        # A SKIPPED decision, a predicted time/delay, or even just the stop's
        # identity+sequence is now real operational content with a home -- only a
        # row with none of it has no observation to emit.
        if not any(
            _present(v)
            for v in (
                stop_ref,
                stop_sequence_raw,
                schedule_relationship,
                arrival_time,
                arrival_delay,
                departure_time,
                departure_delay,
            )
        ):
            return self._quarantine(
                raw_row,
                "stop_time_update carries no stop identity (stop_id/stop_sequence), schedule "
                "relationship, or arrival/departure prediction -- no stop observation to emit",
                failed_field="stop_id",
            )

        # observed_at anchor: the prediction's generation time, else the feed's.
        timestamp_raw = raw_row.get("trip_update_timestamp")
        timestamp_source = "trip_update.timestamp"
        if not _present(timestamp_raw):
            timestamp_raw = raw_row.get("feed_timestamp")
            timestamp_source = "feed header timestamp"
        if not _present(timestamp_raw):
            return self._quarantine(
                raw_row,
                "stop_time_update has neither a trip_update timestamp nor a feed header timestamp "
                "to anchor observed_at",
                failed_field="trip_update_timestamp",
            )
        try:
            observed_at = _epoch_to_utc(timestamp_source, timestamp_raw)
            predicted_arrival_at = (
                _epoch_to_utc("arrival.time", arrival_time) if _present(arrival_time) else None
            )
            predicted_departure_at = (
                _epoch_to_utc("departure.time", departure_time) if _present(departure_time) else None
            )
            arrival_delay_seconds = _as_int(arrival_delay)
            departure_delay_seconds = _as_int(departure_delay)
            stop_sequence = _as_int(stop_sequence_raw)
        except _UnmappableValue as exc:
            return self._quarantine(raw_row, str(exc))

        try:
            observation = StopTimeObservation(
                observation_id=new_id(ObservationId),
                tenant_id=self._tenant_id,
                trip_ref=_str_or_none(raw_row.get("trip_id")),
                route_ref=_str_or_none(raw_row.get("route_id")),
                stop_ref=stop_ref,
                stop_sequence=stop_sequence,
                schedule_relationship=schedule_relationship,
                predicted_arrival_at=predicted_arrival_at,
                predicted_departure_at=predicted_departure_at,
                # GTFS-RT carries predictions, not observed times -- these stay
                # None so a prediction is never mistaken for a record of arrival.
                observed_arrival_at=None,
                observed_departure_at=None,
                arrival_delay_seconds=arrival_delay_seconds,
                departure_delay_seconds=departure_delay_seconds,
                observed_at=observed_at,
                recorded_at=self._recorded_at,
            )
        except ValidationError as exc:
            err = exc.errors()[0]
            loc = err.get("loc") or ()
            return self._quarantine(
                raw_row,
                f"stop_time_update rejected by StopTimeObservation validation: {err.get('msg')}",
                failed_field=str(loc[0]) if loc else None,
            )

        trip_known = frozenset(_TRIP_UPDATE_RESIDUAL_REASONS) | {
            "trip_id",
            "route_id",
            "stop_id",
            "stop_sequence",
            "stop_schedule_relationship",
            "arrival_time",
            "arrival_delay",
            "departure_time",
            "departure_delay",
            "trip_update_timestamp",
        }
        semantic_loss = _report_unmapped(raw_row, _TRIP_UPDATE_RESIDUAL_REASONS, trip_known)
        # A stop observation carries NEITHER reference: StopTimeObservation has no
        # vehicle field (the vehicle_id residual record above says so), and the
        # feed has no run field at all.
        semantic_loss.append(_no_run_reference_loss("no field on StopTimeObservation"))
        return AdapterResult(record=observation, semantic_loss=tuple(semantic_loss))

    # -- helper ------------------------------------------------------------
    def _quarantine(
        self, raw_row: dict, reason: str, *, failed_field: str | None = None
    ) -> AdapterResult:
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
      its own StopTimeObservation; a TripUpdate with none yields a single sentinel
      row that quarantines rather than vanishing),
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
