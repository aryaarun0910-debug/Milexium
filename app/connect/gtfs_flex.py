"""Adapter: GTFS-Flex on-demand-service feed (data/standards/gtfs-flex-*.zip)
-> ServiceRequest (v0.1).

Status: **Demonstrated** only. This maps an *open-standard spec example feed*
(MobilityData's GTFS-Flex "on demand service" example, Apache-2.0 -- a real
City-of-Aspen "Downtowner" flex service published by Trillium), not consented
operator data. Nothing here may be promoted to "Validated" on the strength of
this adapter alone, per knowledge/architecture/decisions/0001.

Why this is a *structurally different third* adapter against the same
app.connect.adapter.SourceAdapter contract -- and the honest modeling
problem it forces:

GTFS-Flex is the closest public standard to how paratransit trips are actually
booked, which is exactly why it is on-brand for Milexium. But a GTFS-Flex feed
is NOT one-row-per-trip like reference_agency_trips.py or tlc_trips.py. It is a
*feed describing bookable service*: a `stop_times` row with a booking rule and a
pickup/drop-off window is a **template for requestable trips** at a location and
time window, not a trip any rider has actually taken. So the mapping here is
deliberately different, and the differences are recorded as semantic loss:

- **Unit of mapping:** one GTFS-Flex `stop_times` row (joined to its
  `booking_rule`, its trip's `calendar` service dates, and `feed_info`) = one
  ServiceRequest representing a *bookable service window* at that location.
- **The standout mapping:** `start_pickup_drop_off_window` /
  `end_pickup_drop_off_window` map directly onto
  `RequestTimes.negotiated_window_start` / `negotiated_window_end` -- GTFS-Flex's
  booking window IS the paratransit negotiated-window concept. The first two
  adapters had no source field for it and correctly left it unset; this one
  finally populates it from real data.
- **Service-template vs. actual request:** because the feed describes
  *potential* service, `status=REQUESTED` is the honest lifecycle state, but a
  semantic-loss entry records on every mapping that no rider, booking, or demand
  event underlies it -- it must not be counted as observed demand.
- **`requested_at`:** the feed has no per-request time; it is coerced to the
  moment the booking window opens on the service's first valid date (from
  `calendar.start_date`, falling back to `feed_info.feed_start_date`), recorded
  as a coercion.
- **No rider identity:** GTFS-Flex publishes service definitions, not riders;
  `rider_ref` is a synthetic, non-joinable per-row placeholder.
- **No vehicle identity either (MX-B-ADAPTER-REFS-009).** GTFS-Flex has no
  vehicle field of any kind, and the only run-shaped field in GTFS core --
  `trips.block_id` -- is optional and empty throughout the acquired feed. The
  reader now carries it through so the absence is *measured* per row, and
  `NO_VEHICLE_REFERENCE_FIELD` records it. Nothing is wired and nothing is
  synthesized: see that record's reason for why `trip_id` is not a run id.
- **Rich booking-rule info** (`booking_type`, `prior_notice_duration_*`,
  `phone_number`, messages, URLs) has no ServiceRequest v0.1 field and is
  recorded as semantic loss rather than dropped silently.

GTFS-Flex `stop_times` columns this adapter was written against (from the
acquired feed's header):
    trip_id, arrival_time, departure_time, stop_id, stop_sequence, stop_headsign,
    pickup_type, drop_off_type, shape_dist_traveled, timepoint, continuous_pickup,
    continuous_drop_off, pickup_booking_rule_id, drop_off_booking_rule_id,
    start_pickup_drop_off_window, end_pickup_drop_off_window, mean_duration_factor,
    mean_duration_offset, safe_duration_factor, safe_duration_offset,
    tts_stop_headsign
`booking_rules` columns:
    booking_rule_id, booking_type, prior_notice_duration_min,
    prior_notice_duration_max, prior_notice_start_day, prior_notice_start_time,
    prior_notice_last_day, prior_notice_last_time, prior_notice_service_id,
    message, pickup_message, drop_off_message, phone_number, info_url, booking_url
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from app.canonical import (
    BitemporalMeta,
    RequestId,
    RequestTimes,
    ServiceRequest,
    ServiceRequestState,
    TenantId,
    new_id,
)
from app.connect.adapter import AdapterResult, QuarantinedRow, SemanticLossRecord

REQUIRED_COLUMNS = (
    "trip_id",
    "stop_id",
    "start_pickup_drop_off_window",
    "end_pickup_drop_off_window",
)

# Synthetic join/context keys the read_gtfs_flex_zip() helper attaches to each
# stop_times row (the join products a self-contained parse(raw_row) needs). They
# are adapter-managed context, not source fields, so they are never reported as
# semantic loss.
_CONTEXT_KEYS = frozenset(
    {
        "booking_rule",
        "service_id",
        "service_start_date",
        "service_end_date",
        "feed_start_date",
        "block_id",
    }
)

_MAPPED_STOP_TIMES = frozenset(REQUIRED_COLUMNS) | frozenset(
    {"pickup_booking_rule_id", "drop_off_booking_rule_id"}
)

_UNMAPPED_STOP_TIMES_REASONS = {
    "arrival_time": (
        "fixed-schedule arrival time; empty for a flex window row -- the window, not a "
        "point time, defines flex availability"
    ),
    "departure_time": "fixed-schedule departure time; empty for a flex window row and unused",
    "stop_sequence": (
        "ordering of this stop within the flex trip; ServiceRequest v0.1 has no field for "
        "source stop ordering"
    ),
    "stop_headsign": "rider-facing headsign text; no ServiceRequest v0.1 field",
    "pickup_type": (
        "GTFS pickup access method (1=none, 2=must phone agency, 3=coordinate with driver); "
        "corroborates that booking is required but has no ServiceRequest v0.1 field"
    ),
    "drop_off_type": "GTFS drop-off access method; encodes flex access but has no ServiceRequest v0.1 field",
    "shape_dist_traveled": "distance travelled along the shape; no ServiceRequest v0.1 field",
    "timepoint": "whether times are exact vs approximate; no ServiceRequest v0.1 field",
    "continuous_pickup": "continuous stopping / flag-down pickup flag; no ServiceRequest v0.1 field",
    "continuous_drop_off": "continuous stopping / flag-down drop-off flag; no ServiceRequest v0.1 field",
    "mean_duration_factor": "GTFS-Flex travel-time estimation parameter; no ServiceRequest v0.1 field",
    "mean_duration_offset": "GTFS-Flex travel-time estimation parameter; no ServiceRequest v0.1 field",
    "safe_duration_factor": "GTFS-Flex travel-time estimation parameter; no ServiceRequest v0.1 field",
    "safe_duration_offset": "GTFS-Flex travel-time estimation parameter; no ServiceRequest v0.1 field",
    "tts_stop_headsign": "text-to-speech headsign; no ServiceRequest v0.1 field",
}

_KNOWN_STOP_TIMES = _MAPPED_STOP_TIMES | frozenset(_UNMAPPED_STOP_TIMES_REASONS)

_UNMAPPED_BOOKING_RULE_REASONS = {
    "booking_type": (
        "GTFS-Flex booking_type (0=real-time, 1=up-to-same-day with notice, 2=up-to-prior-day(s)); "
        "the core demand-responsive booking mode, but ServiceRequest v0.1 has no booking-mode field"
    ),
    "prior_notice_duration_min": (
        "minimum advance-notice minutes required to book -- the paratransit 'advance notice' lead "
        "time; ServiceRequest v0.1 has no booking-lead-time field"
    ),
    "prior_notice_duration_max": "maximum advance-notice minutes; no ServiceRequest v0.1 field",
    "prior_notice_start_day": "earliest day (relative) booking opens; no ServiceRequest v0.1 field",
    "prior_notice_start_time": "time of day booking opens; no ServiceRequest v0.1 field",
    "prior_notice_last_day": "latest day (relative) booking is accepted; no ServiceRequest v0.1 field",
    "prior_notice_last_time": "cutoff time of day for booking; no ServiceRequest v0.1 field",
    "prior_notice_service_id": "calendar service the prior-notice window follows; no ServiceRequest v0.1 field",
    "message": "rider-facing booking instructions; no ServiceRequest v0.1 field",
    "pickup_message": "rider-facing pickup instructions; no ServiceRequest v0.1 field",
    "drop_off_message": "rider-facing drop-off instructions; no ServiceRequest v0.1 field",
    "phone_number": (
        "booking phone number; no ServiceRequest v0.1 field (and a contact detail Core would not "
        "store on an individual request under blueprint 10 data minimization)"
    ),
    "info_url": "booking information URL; no ServiceRequest v0.1 field",
    "booking_url": "online booking URL; no ServiceRequest v0.1 field",
}


NO_VEHICLE_REFERENCE_FIELD = (
    "<no vehicle reference in a GTFS-Flex feed; trips.block_id is the only run-shaped field>"
)
"""MX-B-ADAPTER-REFS-009. The `source_field` under which this adapter records
that its source format carries NO vehicle reference at all.

Recording the absence is the deliverable, not a placeholder for later wiring.
ADR-0039 measures deadhead by chaining ONE vehicle's consecutive trips, so a
source with no vehicle is a source no deadhead can be measured from -- and
saying so plainly is what stops a later reader synthesizing a reference out of
`trip_id` because the field looked conspicuously empty."""


class _UnmappableValue(ValueError):
    """Internal signal that a field value cannot become canonical; caught in
    parse() and turned into a QuarantinedRow rather than propagating."""


def _present(value: object) -> bool:
    """A GTFS CSV cell is absent when it is None or an empty/whitespace string
    (the empty-string null convention GTFS text files use)."""
    return value is not None and str(value).strip() != ""


def _str_or_none(value: object) -> str | None:
    """A present cell -> its trimmed string form; an absent one -> None. Absent
    is never the empty string: `''` in a reference column reads back later as a
    block nobody worked."""
    return str(value).strip() if _present(value) else None


def _parse_gtfs_date(value: object) -> datetime:
    text = str(value).strip()
    try:
        return datetime.strptime(text, "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise _UnmappableValue(
            f"unparseable GTFS service/feed date {value!r} (expected YYYYMMDD)"
        ) from exc


def _parse_gtfs_time(column: str, value: object) -> timedelta:
    """GTFS times are HH:MM:SS where HH may be >= 24 (service past midnight is
    expressed as e.g. 25:30:00, meaning 01:30 the next day)."""
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) != 3:
        raise _UnmappableValue(f"unparseable {column} {value!r} (expected HH:MM:SS)")
    try:
        hours, minutes, seconds = (int(part) for part in parts)
    except ValueError as exc:
        raise _UnmappableValue(f"unparseable {column} {value!r} (expected HH:MM:SS)") from exc
    if hours < 0 or not (0 <= minutes <= 59) or not (0 <= seconds <= 59):
        raise _UnmappableValue(f"{column} out of range {value!r}")
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


def _synthetic_rider_ref(raw_row: dict) -> str:
    # GTFS-Flex has no rider/passenger identifier at all (it describes service,
    # not riders); this hash is a deterministic per-row placeholder that satisfies
    # ServiceRequest.rider_ref, never a stable or joinable entity id.
    basis = "|".join(
        str(raw_row.get(field))
        for field in (
            "trip_id",
            "stop_id",
            "stop_sequence",
            "start_pickup_drop_off_window",
            "end_pickup_drop_off_window",
        )
    )
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    return f"gtfs-flex-no-rider-{digest}"


def _read_member(zf: zipfile.ZipFile, name: str) -> list[dict]:
    """Read one GTFS text file into a list of dict rows, or [] if absent.
    utf-8-sig strips the BOM GTFS files are sometimes published with."""
    if name not in zf.namelist():
        return []
    text = zf.read(name).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def read_gtfs_flex_zip(zip_path: str | Path) -> Iterator[dict]:
    """Read an acquired GTFS-Flex feed zip and yield one adapter-input dict per
    `stop_times` row, pre-joined so each dict is self-contained for parse():

    - the raw `stop_times` columns,
    - `booking_rule`: the resolved booking_rules row dict for the row's
      pickup (or, failing that, drop-off) booking_rule_id, or None if that id is
      absent/dangling,
    - `service_id`, `service_start_date`, `service_end_date`: resolved via
      trips -> calendar for the row's trip,
    - `block_id`: the row's trip's `trips.block_id`, or None when the column is
      absent or blank. Carried ONLY so the adapter can report the absence of a
      run reference as something it MEASURED rather than assumed (see the
      `<no vehicle reference...>` loss record in parse()); nothing maps it.
    - `feed_start_date`: from feed_info.

    The whole feed is read into memory (GTFS-Flex feeds are small) and the zip
    closed before yielding, so the iterator does not hold the file open.
    """
    with zipfile.ZipFile(zip_path) as zf:
        booking_rules = _read_member(zf, "booking_rules.txt")
        trips = _read_member(zf, "trips.txt")
        calendar = _read_member(zf, "calendar.txt")
        feed_info = _read_member(zf, "feed_info.txt")
        stop_times = _read_member(zf, "stop_times.txt")

    booking_index = {
        (row.get("booking_rule_id") or "").strip(): row
        for row in booking_rules
        if (row.get("booking_rule_id") or "").strip()
    }
    trip_index = {
        (row.get("trip_id") or "").strip(): row for row in trips if (row.get("trip_id") or "").strip()
    }
    calendar_index = {
        (row.get("service_id") or "").strip(): row
        for row in calendar
        if (row.get("service_id") or "").strip()
    }
    feed_start_date = (feed_info[0].get("feed_start_date") if feed_info else None) or None

    for stop_time in stop_times:
        row = dict(stop_time)
        ref = (row.get("pickup_booking_rule_id") or "").strip() or (
            row.get("drop_off_booking_rule_id") or ""
        ).strip()
        row["booking_rule"] = booking_index.get(ref) if ref else None

        trip = trip_index.get((row.get("trip_id") or "").strip(), {})
        service_id = (trip.get("service_id") or "").strip()
        calendar_row = calendar_index.get(service_id, {})
        row["service_id"] = service_id or None
        row["block_id"] = (trip.get("block_id") or "").strip() or None
        row["service_start_date"] = (calendar_row.get("start_date") or "").strip() or None
        row["service_end_date"] = (calendar_row.get("end_date") or "").strip() or None
        row["feed_start_date"] = feed_start_date
        yield row


class GtfsFlexAdapter:
    """Maps one GTFS-Flex `stop_times` row (pre-joined to its booking rule and
    service dates by read_gtfs_flex_zip) onto a fresh ServiceRequest that
    represents a *bookable service window*, not an observed trip.

    `recorded_at` is the adapter run's own transaction time (BitemporalMeta),
    distinct from the feed's valid-time fields -- it is not read from the source,
    which has no notion of import/transaction time at all.

    Not wired into app/connect/__init__.py by this change (owned-path
    boundary with parallel work); import directly:
    `from app.connect.gtfs_flex import GtfsFlexAdapter`. Central wiring is a
    follow-up.
    """

    adapter_name = "gtfs-flex-on-demand"
    adapter_version = "0.1.0"

    def __init__(self, tenant_id: TenantId, *, recorded_at: datetime) -> None:
        self._tenant_id = tenant_id
        self._recorded_at = recorded_at

    def parse(self, raw_row: dict) -> AdapterResult[ServiceRequest]:
        missing = [c for c in REQUIRED_COLUMNS if not _present(raw_row.get(c))]
        if missing:
            return AdapterResult(
                quarantine=QuarantinedRow(
                    raw_row=dict(raw_row),
                    reason=f"missing required field(s): {', '.join(missing)}",
                    failed_field=missing[0],
                )
            )

        booking_ref = (
            str(raw_row.get("pickup_booking_rule_id") or "").strip()
            or str(raw_row.get("drop_off_booking_rule_id") or "").strip()
        )
        booking_rule = raw_row.get("booking_rule")
        if not booking_ref:
            return AdapterResult(
                quarantine=QuarantinedRow(
                    raw_row=dict(raw_row),
                    reason=(
                        "flex stop_times row references no booking_rule_id; this adapter maps only "
                        "bookable demand-responsive service (a booking rule is what makes the window "
                        "a *bookable* request), so a window without one is out of scope"
                    ),
                    failed_field="pickup_booking_rule_id",
                )
            )
        if not isinstance(booking_rule, dict):
            return AdapterResult(
                quarantine=QuarantinedRow(
                    raw_row=dict(raw_row),
                    reason=(
                        f"stop_times references booking_rule_id {booking_ref!r}, which is not present "
                        "in booking_rules.txt (dangling reference)"
                    ),
                    failed_field="pickup_booking_rule_id",
                )
            )

        anchor_raw = raw_row.get("service_start_date")
        used_feed_fallback = False
        if not _present(anchor_raw):
            anchor_raw = raw_row.get("feed_start_date")
            used_feed_fallback = True
        if not _present(anchor_raw):
            return AdapterResult(
                quarantine=QuarantinedRow(
                    raw_row=dict(raw_row),
                    reason=(
                        "no service_start_date (calendar) or feed_start_date (feed_info) available to "
                        "anchor the flex booking window on a concrete date"
                    ),
                    failed_field="service_start_date",
                )
            )

        try:
            anchor = _parse_gtfs_date(anchor_raw)
            window_start = anchor + _parse_gtfs_time(
                "start_pickup_drop_off_window", raw_row["start_pickup_drop_off_window"]
            )
            window_end = anchor + _parse_gtfs_time(
                "end_pickup_drop_off_window", raw_row["end_pickup_drop_off_window"]
            )
        except _UnmappableValue as exc:
            return AdapterResult(quarantine=QuarantinedRow(raw_row=dict(raw_row), reason=str(exc)))

        if window_end < window_start:
            return AdapterResult(
                quarantine=QuarantinedRow(
                    raw_row=dict(raw_row),
                    reason=(
                        f"negotiated window end {raw_row['end_pickup_drop_off_window']!r} is before "
                        f"start {raw_row['start_pickup_drop_off_window']!r}"
                    ),
                    failed_field="end_pickup_drop_off_window",
                )
            )

        stop_id = str(raw_row["stop_id"]).strip()
        anchor_source = "feed_info.feed_start_date" if used_feed_fallback else "calendar.start_date"

        semantic_loss = [
            SemanticLossRecord(
                source_field="start_pickup_drop_off_window/end_pickup_drop_off_window",
                source_value=(
                    f"{raw_row['start_pickup_drop_off_window']}..{raw_row['end_pickup_drop_off_window']}"
                ),
                reason=(
                    "GTFS-Flex's pickup/drop-off booking window IS the paratransit negotiated pickup "
                    "window: mapped directly to negotiated_window_start/negotiated_window_end. The "
                    "window is a daily-recurring time-of-day range with no single calendar date in the "
                    f"feed; it is anchored to {anchor.date().isoformat()} (from {anchor_source}) to "
                    "produce concrete UTC instants, collapsing all other valid service days. Times are "
                    "naive agency-local (America/Denver) treated as UTC directly -- the same "
                    "simplification used elsewhere in this repo; a true offset conversion would shift "
                    "them by ~6-7 hours"
                ),
                disposition="coerced",
            ),
            SemanticLossRecord(
                source_field="<no per-request time in a GTFS-Flex feed>",
                source_value=None,
                reason=(
                    "a GTFS-Flex feed describes bookable service availability, not individual booked "
                    "trips, so it carries no per-request timestamp; requested_at is coerced to the "
                    f"moment the booking window opens on the anchor date ({window_start.isoformat()}) "
                    "as a service-availability anchor, NOT an actual rider request instant"
                ),
                disposition="coerced",
            ),
            SemanticLossRecord(
                source_field="<service-availability template, not an actual rider request>",
                source_value=None,
                reason=(
                    "this ServiceRequest is synthesized from a GTFS-Flex feed row, which describes a "
                    "bookable service window (a template for requests a rider *could* make), not a "
                    "request any rider has actually made. status is set to REQUESTED as the honest "
                    "lifecycle state for such a request, but no rider, booking, or demand event "
                    "underlies it -- unlike business/reference_agency/TLC rows, which are real (if "
                    "fictional/anonymous) individual trips. Downstream consumers must not count these "
                    "as observed demand"
                ),
                disposition="coerced",
            ),
            SemanticLossRecord(
                source_field="<no rider/passenger identifier in a GTFS-Flex feed>",
                source_value=None,
                reason=(
                    "GTFS-Flex publishes service definitions, not riders, so there is no "
                    "rider/passenger identifier of any kind; rider_ref is a synthetic, non-joinable "
                    "per-row placeholder (gtfs-flex-no-rider-<hash of trip_id|stop_id|stop_sequence|"
                    "window>), never a stable or joinable entity id"
                ),
                disposition="dropped",
            ),
            SemanticLossRecord(
                source_field="stop_id",
                source_value=stop_id,
                reason=(
                    f"a GTFS-Flex stop_times row names ONE servable location (here the location area "
                    f"{stop_id}, typically a GeoJSON zone polygon, not a physical stop), not an "
                    "origin-destination pair. ServiceRequest requires both pickup_zone and "
                    "dropoff_zone, so both are set to this single flex service-area id. For a "
                    "within-area door-to-door demand-responsive service that is faithful; for a "
                    "general flex trip the true dropoff would come from a different stop_times entry in "
                    "the trip and is not represented here"
                ),
                disposition="coerced",
            ),
            SemanticLossRecord(
                source_field="<no rider mobility-device signal>",
                source_value=None,
                reason=(
                    "a service-availability template carries no per-rider mobility-device information "
                    "(trips.wheelchair_accessible describes vehicle accessibility, not a rider's "
                    "device); mobility_device is left unset rather than guessed"
                ),
                disposition="dropped",
            ),
            SemanticLossRecord(
                source_field=NO_VEHICLE_REFERENCE_FIELD,
                source_value=_str_or_none(raw_row.get("block_id")),
                reason=(
                    "GTFS-Flex has NO vehicle identifier anywhere in the standard -- not in "
                    "stop_times, not in trips, not in booking_rules. A feed describes bookable "
                    "service, and no vehicle has performed anything yet, so there is nothing to "
                    "name. The only run-shaped field GTFS core offers is the optional "
                    "trips.block_id, reported here as source_value (None when the trip carried "
                    "none, which is the case throughout the acquired Aspen 'Downtowner' feed); it "
                    "is MEASURED per row rather than assumed absent. Even where a feed populates "
                    "it, nothing is wired: this adapter emits a ServiceRequest, and ADR-0043 put "
                    "vehicle_ref/run_ref on Outcome and deliberately NOT on ServiceRequest (one "
                    "fact, one home). Attaching a block to a bookable window would assert that a "
                    "vehicle worked a trip nobody has taken. NOTHING here is synthesized from "
                    "trip_id, service_id or a booking_rule_id: a trip id names a published "
                    "pattern, not a vehicle's day of work, and chaining by it would report "
                    "deadhead between two windows no vehicle ever traversed. ADR-0039's "
                    "`unattributable` bucket is the correct destination for this source"
                ),
                disposition="dropped",
            ),
        ]

        for column, reason in _UNMAPPED_STOP_TIMES_REASONS.items():
            value = raw_row.get(column)
            if _present(value):
                semantic_loss.append(
                    SemanticLossRecord(
                        source_field=column,
                        source_value=str(value),
                        reason=reason,
                        disposition="dropped",
                    )
                )

        for column, value in booking_rule.items():
            if column == "booking_rule_id" or not _present(value):
                continue
            reason = _UNMAPPED_BOOKING_RULE_REASONS.get(column)
            semantic_loss.append(
                SemanticLossRecord(
                    source_field=f"booking_rule.{column}",
                    source_value=str(value),
                    reason=reason
                    or "not part of the GTFS-Flex booking_rules schema this adapter was written against",
                    disposition="dropped" if reason is not None else "unmapped_extension",
                )
            )

        for column, value in raw_row.items():
            if column in _CONTEXT_KEYS or column in _KNOWN_STOP_TIMES:
                continue
            semantic_loss.append(
                SemanticLossRecord(
                    source_field=column,
                    source_value=str(value) if _present(value) else None,
                    reason="not part of the GTFS-Flex stop_times schema this adapter was written against",
                    disposition="unmapped_extension",
                )
            )

        request = ServiceRequest(
            request_id=new_id(RequestId),
            tenant_id=self._tenant_id,
            rider_ref=_synthetic_rider_ref(raw_row),
            pickup_zone=stop_id,
            dropoff_zone=stop_id,
            mobility_device=None,
            times=RequestTimes(
                requested_at=window_start,
                negotiated_window_start=window_start,
                negotiated_window_end=window_end,
            ),
            status=ServiceRequestState.REQUESTED,
            meta=BitemporalMeta(version=1, recorded_at=self._recorded_at),
        )
        return AdapterResult(record=request, semantic_loss=tuple(semantic_loss))
