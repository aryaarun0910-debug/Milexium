"""Derive SCHEDULED deadhead by chaining GTFS trips within a block.

WHAT THIS MEASURES, AND WHAT IT DOES NOT
========================================
Read this before quoting any number this tool produces.

Milexium's only existing deadhead figure comes from the NTD Service form: one
self-reported number per operator, per mode, per year, describing what vehicles
ACTUALLY DID. This tool produces something categorically different -- what a
published timetable IMPLIES a vehicle must do -- and the two must never be
subtracted from one another as though they measured the same quantity.

The derivation is simple and its inputs are honest about their own limits:
within one feed, one `block_id` and one `service_id`, order the trips by their
scheduled first departure; the interval between one trip's last scheduled
arrival and the next trip's first scheduled departure is time in which that
vehicle is assigned to the block and carrying no passengers.

Four things make the result a LOWER BOUND on real deadhead, and one makes it an
UPPER bound on some of it. They are not symmetric and they do not cancel:

1. PULL-OUT AND PULL-IN ARE ABSENT. GTFS almost never publishes the garage.
   The empty run from the depot to the first trip, and back from the last, is
   invisible here -- and on many operators it is the single largest deadhead
   component. Every figure below therefore EXCLUDES the deadhead most likely to
   dominate. `packages.canonical.entities.DeadheadKind` has `pull_out` and
   `pull_in` members; this tool never emits either, because it never sees one.
2. NO CANONICAL `Block` ROW IS CREATED. `Block` requires `pull_out_at` and
   `pull_in_at`. GTFS gives neither. Setting them to the first trip's departure
   and the last trip's arrival would silently redefine a block as its revenue
   envelope and erase point 1 by construction, so this tool emits
   `DeadheadSegment`s with `block_id=None` and the agency's own `block_ref`,
   and creates no `Block` at all.
3. SCHEDULE IS NOT OPERATION. A vehicle that ran late, short-turned, was
   swapped, or was pulled from service did none of what the timetable says.
   This tool cannot see any of that. Only vehicle positions can (the "Observed"
   tier of data/ACQUISITION_PLAN.md), and the estate holds none.
4. `block_id` IS OPTIONAL IN GTFS AND OFTEN ABSENT OR MISUSED. An agency that
   publishes no `block_id` contributes nothing here -- not zero deadhead, but
   NO MEASUREMENT. An agency that reuses one `block_id` across several physical
   vehicles produces overlapping trips, which are counted and excluded rather
   than chained into fictional movements.
5. Against those four, one effect points the other way: a gap between two trips
   is only PARTLY deadhead. Some of it is layover -- the vehicle standing at a
   terminal, and the driver on a break. This tool separates the two on the only
   evidence the source actually carries: whether the next trip starts at a
   DIFFERENT stop from where the last one ended. Same stop => the schedule says
   the vehicle does not move => reported as layover-in-place, and NO
   `DeadheadSegment` is emitted. Different stop => the schedule says the vehicle
   must get from one place to the other => a segment is emitted. That split is
   the source's own statement, not a threshold this tool invented; the
   sensitivity of it (how many "different stop" pairs are actually metres
   apart) is reported so a reader can subtract for themselves.

DEADHEAD TYPE IS ALWAYS `other`, DELIBERATELY. `DeadheadKind`'s contract is
explicit that the kind is "a CLASSIFICATION carried by the source, never
inferred here from geometry or timing", and warns specifically that guessing
`interline` "silently inflat[es] the one number an interlining change is
measured by". GTFS carries no deadhead classification whatsoever, so every
segment this tool emits is `other` -- the honest landing place the entity
documents. Whether the two trips were on different routes IS known, and is
reported as a statistic in the summary, where it informs without pretending to
be a source-carried classification.

TIMES ARE ANCHORED TO A NOMINAL REFERENCE DATE. GTFS schedules are recurring:
a service day has an offset in seconds, not an instant. `DeadheadSegment`
requires absolute UTC instants, so every segment is anchored to one declared
reference service date in the feed's own agency timezone. The DURATIONS are
real; the absolute instants are a nominal placement of a pattern that recurs on
every date its `service_id` is active. `--reference-date` makes that visible
rather than buried.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from packages.canonical.entities import DeadheadSegment  # noqa: E402
from packages.canonical.ids import (  # noqa: E402
    PLATFORM_TENANT_ID,
    DeadheadSegmentId,
    new_id,
)

_CATALOG = _REPO_ROOT / "data" / "catalog"

#: Fallback timezone when a feed's `agency_timezone` is absent or unparseable.
#: Every operator in this dataset is Californian, so this is a safe default --
#: but it is applied per feed and COUNTED, never applied silently.
_DEFAULT_TZ = "America/Los_Angeles"

#: Two different stop ids closer than this are almost certainly the same
#: physical place (opposite kerbs, adjacent bays at one terminal). Used ONLY to
#: report the sensitivity of the layover/movement split -- never to filter.
_SAME_PLACE_METRES = 50.0


# --------------------------------------------------------------------------
# Pure helpers -- all independently testable without any of the 2.8 GB inputs
# --------------------------------------------------------------------------


def parse_gtfs_seconds(value: str | None) -> int | None:
    """Parse a GTFS HH:MM:SS time into seconds after the service day starts.

    GTFS clock times legitimately exceed 24:00:00: a trip that arrives at
    01:10 on the morning AFTER its service day is written `25:10:00`. Parsing
    that as a wall clock and wrapping it to 01:10 would make the last trip of a
    block sort BEFORE the first, and turn a 20-minute gap into a -23-hour one.
    Hours are therefore unbounded above; minutes and seconds are not.

    Returns None for anything unusable, so the caller decides what to do about
    a missing time rather than receiving a plausible-looking zero.
    """
    text = (value or "").strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = (int(part) for part in parts)
    except ValueError:
        return None
    if hours < 0 or not (0 <= minutes < 60) or not (0 <= seconds < 60):
        return None
    return hours * 3600 + minutes * 60 + seconds


def coerce_seconds(second_field: str | None, clock_field: str | None) -> int | None:
    """Prefer Cal-ITP's precomputed `*_sec` column, fall back to the clock text.

    The `*_sec` columns are the publisher's own conversion and already handle
    the >24:00:00 case. They are not always populated, so the raw GTFS time is
    the fallback -- and disagreement between the two is a quality test, not
    something to paper over silently (see `second_offsets_agree_with_clock_times`
    in the stop_times manifest).
    """
    text = (second_field or "").strip()
    if text:
        try:
            return int(float(text))
        except ValueError:
            pass
    return parse_gtfs_seconds(clock_field)


def haversine_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance. Used only to report how many "different stop"
    gaps are really the same physical place; never to classify."""
    radius = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def anchor_to_utc(reference_date: date, tz: ZoneInfo, offset_seconds: int) -> datetime:
    """Place a service-day offset onto a nominal calendar date, in UTC.

    The service day starts at local midnight on `reference_date`; offsets past
    86400 roll into the following calendar day, which is exactly the GTFS
    after-midnight convention. Arithmetic is wall-clock (Python adds the
    timedelta to the naive local time and keeps the zone), which matches GTFS's
    own service-day semantics; the two only diverge on a DST-transition date,
    and the reference date is chosen to avoid one.
    """
    local_midnight = datetime.combine(reference_date, time(0, 0), tzinfo=tz)
    return (local_midnight + timedelta(seconds=offset_seconds)).astimezone(timezone.utc)


@dataclass
class TripExtent:
    """Where and when one trip starts and ends, per its published stop times."""

    first_sequence: int
    last_sequence: int
    first_departure_s: int | None
    last_arrival_s: int | None
    first_stop_ref: str
    last_stop_ref: str
    stop_time_rows: int = 0

    def observe(
        self, sequence: int, stop_ref: str, arrival_s: int | None, departure_s: int | None
    ) -> None:
        """Fold one stop_times row in. Ordering is by `stop_sequence`, NOT by
        file order and NOT by time: GTFS defines trip order by sequence, and a
        feed with a mis-sorted file or a clock error must still yield the trip's
        real first and last stop."""
        self.stop_time_rows += 1
        if sequence <= self.first_sequence:
            self.first_sequence = sequence
            self.first_stop_ref = stop_ref
            # First departure; fall back to the arrival at the same stop.
            self.first_departure_s = departure_s if departure_s is not None else arrival_s
        if sequence >= self.last_sequence:
            self.last_sequence = sequence
            self.last_stop_ref = stop_ref
            self.last_arrival_s = arrival_s if arrival_s is not None else departure_s

    @property
    def is_usable(self) -> bool:
        """A trip is chainable only with both ends timed and at least two stops.

        A single-stop "trip" has no revenue span at all; chaining one would
        create a gap on each side of a point event that never happened.
        """
        return (
            self.first_departure_s is not None
            and self.last_arrival_s is not None
            and self.stop_time_rows >= 2
            and self.last_arrival_s >= self.first_departure_s
        )

    @property
    def revenue_seconds(self) -> int:
        assert self.first_departure_s is not None and self.last_arrival_s is not None
        return self.last_arrival_s - self.first_departure_s


@dataclass(frozen=True)
class ScheduledGap:
    """One interval inside a block during which the vehicle carries no riders.

    Deliberately NOT called a deadhead: whether it is deadhead, layover, or a
    mixture is a separate judgement made by `is_movement`, and naming the raw
    interval "deadhead" would smuggle that judgement into the data structure.
    """

    feed: str
    block_ref: str
    service_ref: str
    from_trip_id: str
    to_trip_id: str
    from_route_id: str
    to_route_id: str
    from_stop_ref: str
    to_stop_ref: str
    started_s: int
    ended_s: int

    @property
    def duration_seconds(self) -> int:
        return self.ended_s - self.started_s

    @property
    def is_movement(self) -> bool:
        """The schedule says the vehicle ends one trip somewhere and begins the
        next somewhere else, so it must physically get there. Same stop means
        the schedule asserts no movement at all -- that is layover, and calling
        it deadhead would overstate the very number this exists to measure."""
        return self.from_stop_ref != self.to_stop_ref

    @property
    def changes_route(self) -> bool:
        return self.from_route_id != self.to_route_id


@dataclass
class ChainStats:
    """Everything the chaining discarded, and why. Kept beside the result so a
    reader can see the denominator, not just the numerator."""

    blocks: int = 0
    chained_pairs: int = 0
    overlapping_pairs: int = 0
    zero_length_pairs: int = 0
    positive_pairs: int = 0
    single_trip_blocks: int = 0


def chain_block(
    trips: list[tuple[str, str, TripExtent]],
    *,
    feed: str,
    block_ref: str,
    service_ref: str,
) -> tuple[list[ScheduledGap], ChainStats]:
    """Order one block's trips in time and emit the interval between each pair.

    `trips` is [(trip_id, route_id, extent)] for exactly one
    (feed, block_id, service_id). Sorting is by first departure, then last
    arrival, then trip_id -- the last two purely so the output is deterministic
    when a feed schedules two trips at the identical second.

    THREE OUTCOMES PER CONSECUTIVE PAIR, and only one of them is a gap:

    * `next.start < current.end` -- the block claims one vehicle is in two
      places at once. That is not a deadhead of negative length; it is evidence
      the `block_id` is shared between physical vehicles (or that the feed is
      wrong). Counted as `overlapping_pairs` and DROPPED. `DeadheadSegment`
      would reject it at construction anyway; dropping it here means the count
      survives as a quality signal instead of surfacing as an exception.
    * `next.start == current.end` -- a through-routed continuation. Zero
      non-revenue seconds; nothing to emit.
    * `next.start > current.end` -- a real interval, emitted.
    """
    stats = ChainStats(blocks=1)
    ordered = sorted(
        (t for t in trips if t[2].is_usable),
        key=lambda t: (t[2].first_departure_s, t[2].last_arrival_s, t[0]),
    )
    if len(ordered) < 2:
        stats.single_trip_blocks = 1
        return [], stats

    gaps: list[ScheduledGap] = []
    for (from_id, from_route, left), (to_id, to_route, right) in zip(ordered, ordered[1:]):
        stats.chained_pairs += 1
        started_s = left.last_arrival_s
        ended_s = right.first_departure_s
        assert started_s is not None and ended_s is not None
        if ended_s < started_s:
            stats.overlapping_pairs += 1
            continue
        if ended_s == started_s:
            stats.zero_length_pairs += 1
            continue
        stats.positive_pairs += 1
        gaps.append(
            ScheduledGap(
                feed=feed,
                block_ref=block_ref,
                service_ref=service_ref,
                from_trip_id=from_id,
                to_trip_id=to_id,
                from_route_id=from_route,
                to_route_id=to_route,
                from_stop_ref=left.last_stop_ref,
                to_stop_ref=right.first_stop_ref,
                started_s=started_s,
                ended_s=ended_s,
            )
        )
    return gaps, stats


def gap_to_deadhead_segment(
    gap: ScheduledGap,
    *,
    reference_date: date,
    tz: ZoneInfo,
    recorded_at: datetime,
) -> DeadheadSegment:
    """Map one movement gap onto Program A's canonical entity, unchanged.

    Every field choice here is a refusal to overclaim:

    * `deadhead_type="other"` -- GTFS classifies nothing. See the module
      docstring; `DeadheadKind` documents `other` as the honest landing place.
    * `block_id=None` -- no canonical `Block` row exists, because GTFS cannot
      supply `pull_out_at`/`pull_in_at`. A typed id here would be a dangling
      reference.
    * `run_ref=block_ref` -- `DeadheadSegment.run_ref` is documented as the
      "run/block identifier, as the operator writes it", and it is the field
      `packages.replay.teardown` attributes empty time by. The GTFS block is a
      VEHICLE block, not a crew run; the entity's own contract admits either,
      and leaving it None would push every segment into `unattributable` and
      make the teardown useless on this data.
    * `vehicle_ref=None`, `deadhead_ref=None` -- GTFS names no vehicle and mints
      no identifier for the movement. Synthesising either would be inventing a
      source fact.
    """
    return DeadheadSegment(
        deadhead_segment_id=new_id(DeadheadSegmentId),
        tenant_id=PLATFORM_TENANT_ID,
        deadhead_ref=None,
        block_id=None,
        block_ref=gap.block_ref,
        run_ref=gap.block_ref,
        vehicle_ref=None,
        deadhead_type="other",
        from_stop_ref=gap.from_stop_ref,
        to_stop_ref=gap.to_stop_ref,
        started_at=anchor_to_utc(reference_date, tz, gap.started_s),
        ended_at=anchor_to_utc(reference_date, tz, gap.ended_s),
        recorded_at=recorded_at,
    )


def percentiles(values: list[float], points: tuple[float, ...]) -> dict[str, float]:
    """Nearest-rank percentiles. No numpy dependency for a summary table."""
    if not values:
        return {f"p{p:g}": 0.0 for p in points}
    ordered = sorted(values)
    out: dict[str, float] = {}
    for p in points:
        rank = max(1, math.ceil(p / 100.0 * len(ordered)))
        out[f"p{p:g}"] = round(ordered[min(rank, len(ordered)) - 1], 2)
    return out


# --------------------------------------------------------------------------
# Estate plumbing -- resolve inputs from the governed catalog, never by path
# --------------------------------------------------------------------------


def acquired_path(dataset_id: str) -> Path:
    """Resolve a raw object through its acquired-record, so this tool can only
    read bytes that actually passed the governed pipeline. A hard-coded path
    would let it read an ungoverned file that happened to be lying around."""
    record_path = _CATALOG / f"{dataset_id}.acquired.json"
    if not record_path.exists():
        raise SystemExit(
            f"{dataset_id}: no acquired-record in data/catalog/. Acquire it first:\n"
            f'  py -3 -c "from packages.estate import acquire; '
            f"acquire('data/catalog/{dataset_id}.manifest.json', back_with_object_store=True)\""
        )
    record = json.loads(record_path.read_text(encoding="utf-8"))
    path = _REPO_ROOT / record["raw_path"]
    if not path.exists():
        raise SystemExit(f"{dataset_id}: acquired-record present but {path} is not on this disk")
    return path


def _reader(path: Path):
    handle = path.open("r", encoding="utf-8-sig", newline="")
    reader = csv.reader(handle)
    header = next(reader)
    return handle, reader, {name: i for i, name in enumerate(header)}


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


@dataclass
class Inputs:
    """Everything read from the small files, before the big streaming pass."""

    agency_name: dict[tuple[str, str], str] = field(default_factory=dict)
    agency_tz: dict[str, str] = field(default_factory=dict)
    route_agency: dict[tuple[str, str], str] = field(default_factory=dict)
    feed_name: dict[str, str] = field(default_factory=dict)
    stop_latlon: dict[tuple[str, str], tuple[float, float]] = field(default_factory=dict)
    frequency_trips: set[tuple[str, str]] = field(default_factory=set)


def load_small_inputs() -> Inputs:
    inputs = Inputs()

    handle, reader, idx = _reader(acquired_path("calitp-gtfs-agency"))
    with handle:
        for row in reader:
            feed = _cell(row, idx.get("base64_url"))
            agency_id = _cell(row, idx.get("agency_id"))
            inputs.agency_name[(feed, agency_id)] = _cell(row, idx.get("agency_name")) or "(unnamed)"
            tz = _cell(row, idx.get("agency_timezone"))
            if tz and feed not in inputs.agency_tz:
                inputs.agency_tz[feed] = tz

    handle, reader, idx = _reader(acquired_path("calitp-gtfs-routes"))
    with handle:
        for row in reader:
            feed = _cell(row, idx.get("base64_url"))
            inputs.route_agency[(feed, _cell(row, idx.get("route_id")))] = _cell(
                row, idx.get("agency_id")
            )

    handle, reader, idx = _reader(acquired_path("calitp-gtfs-datasets"))
    with handle:
        for row in reader:
            inputs.feed_name[_cell(row, idx.get("base64_url"))] = _cell(row, idx.get("name"))

    handle, reader, idx = _reader(acquired_path("calitp-gtfs-stops"))
    with handle:
        for row in reader:
            lat, lon = _cell(row, idx.get("stop_lat")), _cell(row, idx.get("stop_lon"))
            if not lat or not lon:
                continue
            try:
                inputs.stop_latlon[
                    (_cell(row, idx.get("base64_url")), _cell(row, idx.get("stop_id")))
                ] = (float(lat), float(lon))
            except ValueError:
                continue

    handle, reader, idx = _reader(acquired_path("calitp-gtfs-frequencies"))
    with handle:
        for row in reader:
            inputs.frequency_trips.add(
                (_cell(row, idx.get("base64_url")), _cell(row, idx.get("trip_id")))
            )

    return inputs


def resolve_zone(name: str, cache: dict[str, ZoneInfo], fallbacks: dict[str, int]) -> ZoneInfo:
    key = name or ""
    if key in cache:
        return cache[key]
    try:
        zone = ZoneInfo(key) if key else ZoneInfo(_DEFAULT_TZ)
        if not key:
            fallbacks["absent"] = fallbacks.get("absent", 0) + 1
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo(_DEFAULT_TZ)
        fallbacks["unparseable"] = fallbacks.get("unparseable", 0) + 1
    cache[key] = zone
    return zone


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--reference-date",
        default="2026-07-21",
        help=(
            "Nominal service date the recurring schedule is anchored to (default "
            "2026-07-21, the CKAN metadata_modified date of the source assembly, "
            "chosen to be a non-DST-transition date). Durations do not depend on it; "
            "absolute instants do, and are nominal."
        ),
    )
    parser.add_argument(
        "--segments-out",
        default="data/canonical/calitp-scheduled-deadhead-segments.jsonl",
        help="Gitignored canonical zone; one JSON object per emitted DeadheadSegment.",
    )
    parser.add_argument(
        "--summary-out",
        default="data/catalog/calitp-scheduled-deadhead.summary.json",
        help="Committed derived summary (small JSON, no bulk data).",
    )
    parser.add_argument("--max-segments", type=int, default=0, help="0 = write all.")
    args = parser.parse_args(argv)

    reference_date = date.fromisoformat(args.reference_date)
    recorded_at = datetime.now(timezone.utc)

    print("reading small inputs (agency, routes, datasets, stops, frequencies)...", flush=True)
    inputs = load_small_inputs()
    print(
        f"  agencies={len(inputs.agency_name)} routes={len(inputs.route_agency)} "
        f"feeds={len(inputs.feed_name)} stops={len(inputs.stop_latlon)} "
        f"frequency_trips={len(inputs.frequency_trips)}",
        flush=True,
    )

    # ---- trips: what we are allowed to chain, and why the rest is not -----
    trips_path = acquired_path("calitp-gtfs-trips")
    handle, reader, idx = _reader(trips_path)
    trip_meta: dict[tuple[str, str], tuple[str, str, str]] = {}
    total_trips = 0
    trips_without_block = 0
    trips_frequency_excluded = 0
    feeds_seen: set[str] = set()
    agency_all_trips: set[tuple[str, str]] = set()
    agency_block_trips: set[tuple[str, str]] = set()
    with handle:
        for row in reader:
            total_trips += 1
            feed = _cell(row, idx.get("base64_url"))
            trip_id = _cell(row, idx.get("trip_id"))
            block_ref = _cell(row, idx.get("block_id"))
            route_id = _cell(row, idx.get("route_id"))
            service_ref = _cell(row, idx.get("service_id"))
            feeds_seen.add(feed)
            agency_key = (feed, inputs.route_agency.get((feed, route_id), ""))
            agency_all_trips.add(agency_key)
            if not block_ref:
                trips_without_block += 1
                continue
            agency_block_trips.add(agency_key)
            if (feed, trip_id) in inputs.frequency_trips:
                trips_frequency_excluded += 1
                continue
            trip_meta[(feed, trip_id)] = (block_ref, service_ref, route_id)
    print(
        f"trips: total={total_trips:,} no_block_id={trips_without_block:,} "
        f"frequency_excluded={trips_frequency_excluded:,} chainable={len(trip_meta):,}",
        flush=True,
    )

    # ---- stop_times: one streaming pass, keeping only chainable trips ------
    st_path = acquired_path("calitp-gtfs-stop-times")
    handle, reader, idx = _reader(st_path)
    extents: dict[tuple[str, str], TripExtent] = {}
    sec_disagreements = 0
    sec_checked = 0
    rows = 0
    i_feed = idx.get("base64_url")
    i_trip = idx.get("trip_id")
    i_stop = idx.get("stop_id")
    i_seq = idx.get("stop_sequence")
    i_arr_s, i_dep_s = idx.get("arrival_sec"), idx.get("departure_sec")
    i_arr_t, i_dep_t = idx.get("arrival_time"), idx.get("departure_time")
    with handle:
        for row in reader:
            rows += 1
            if rows % 5_000_000 == 0:
                print(f"  stop_times rows={rows:,} tracked_trips={len(extents):,}", flush=True)
            key = (_cell(row, i_feed), _cell(row, i_trip))
            if key not in trip_meta:
                continue
            try:
                sequence = int(_cell(row, i_seq))
            except ValueError:
                continue
            arrival_s = coerce_seconds(_cell(row, i_arr_s), _cell(row, i_arr_t))
            departure_s = coerce_seconds(_cell(row, i_dep_s), _cell(row, i_dep_t))
            # Quality test from the manifest: the publisher's *_sec column must
            # agree with the clock text it was derived from.
            if sec_checked < 200_000:
                clock = parse_gtfs_seconds(_cell(row, i_arr_t))
                raw_sec = _cell(row, i_arr_s)
                if clock is not None and raw_sec:
                    sec_checked += 1
                    if int(float(raw_sec)) != clock:
                        sec_disagreements += 1
            stop_ref = _cell(row, i_stop)
            existing = extents.get(key)
            if existing is None:
                extents[key] = TripExtent(
                    first_sequence=sequence,
                    last_sequence=sequence,
                    first_departure_s=departure_s if departure_s is not None else arrival_s,
                    last_arrival_s=arrival_s if arrival_s is not None else departure_s,
                    first_stop_ref=stop_ref,
                    last_stop_ref=stop_ref,
                    stop_time_rows=1,
                )
            else:
                existing.observe(sequence, stop_ref, arrival_s, departure_s)
    print(
        f"stop_times: rows={rows:,} trips_with_times={len(extents):,} "
        f"sec_column_disagreements={sec_disagreements}/{sec_checked}",
        flush=True,
    )

    # ---- group into blocks and chain --------------------------------------
    blocks: dict[tuple[str, str, str], list[tuple[str, str, TripExtent]]] = defaultdict(list)
    block_service_ids: dict[tuple[str, str], set[str]] = defaultdict(set)
    unusable_trips = 0
    trips_missing_times = 0
    revenue_seconds_by_agency: dict[tuple[str, str], int] = defaultdict(int)
    for key, (block_ref, service_ref, route_id) in trip_meta.items():
        extent = extents.get(key)
        if extent is None:
            trips_missing_times += 1
            continue
        if not extent.is_usable:
            unusable_trips += 1
            continue
        feed, trip_id = key
        blocks[(feed, block_ref, service_ref)].append((trip_id, route_id, extent))
        block_service_ids[(feed, block_ref)].add(service_ref)
        agency_key = (feed, inputs.route_agency.get((feed, route_id), ""))
        revenue_seconds_by_agency[agency_key] += extent.revenue_seconds

    multi_service_blocks = sum(1 for s in block_service_ids.values() if len(s) > 1)

    totals = ChainStats()
    all_gaps: list[ScheduledGap] = []
    for (feed, block_ref, service_ref), members in blocks.items():
        gaps, stats = chain_block(
            members, feed=feed, block_ref=block_ref, service_ref=service_ref
        )
        totals.blocks += stats.blocks
        totals.chained_pairs += stats.chained_pairs
        totals.overlapping_pairs += stats.overlapping_pairs
        totals.zero_length_pairs += stats.zero_length_pairs
        totals.positive_pairs += stats.positive_pairs
        totals.single_trip_blocks += stats.single_trip_blocks
        all_gaps.extend(gaps)

    # ---- split movement from layover, and emit canonical entities ---------
    tz_cache: dict[str, ZoneInfo] = {}
    tz_fallbacks: dict[str, int] = {}
    segments_out = _REPO_ROOT / args.segments_out
    segments_out.parent.mkdir(parents=True, exist_ok=True)

    movement_minutes: list[float] = []
    layover_minutes: list[float] = []
    movement_distances: list[float] = []
    near_same_place = 0
    distance_unknown = 0
    route_changing_movements = 0
    per_agency: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {
            "blocks": 0.0,
            "movement_gaps": 0.0,
            "layover_gaps": 0.0,
            "overlapping_pairs": 0.0,
            "movement_seconds": 0.0,
            "layover_seconds": 0.0,
        }
    )
    agency_of_block: dict[tuple[str, str, str], tuple[str, str]] = {}
    for (feed, block_ref, service_ref), members in blocks.items():
        route_id = members[0][1]
        agency_of_block[(feed, block_ref, service_ref)] = (
            feed,
            inputs.route_agency.get((feed, route_id), ""),
        )
    for block_key, agency_key in agency_of_block.items():
        per_agency[agency_key]["blocks"] += 1

    written = 0
    agencies_with_measurement: set[tuple[str, str]] = set()
    with segments_out.open("w", encoding="utf-8") as out:
        for gap in all_gaps:
            agency_key = agency_of_block[(gap.feed, gap.block_ref, gap.service_ref)]
            minutes = gap.duration_seconds / 60.0
            if not gap.is_movement:
                layover_minutes.append(minutes)
                per_agency[agency_key]["layover_gaps"] += 1
                per_agency[agency_key]["layover_seconds"] += gap.duration_seconds
                continue

            movement_minutes.append(minutes)
            per_agency[agency_key]["movement_gaps"] += 1
            per_agency[agency_key]["movement_seconds"] += gap.duration_seconds
            agencies_with_measurement.add(agency_key)
            if gap.changes_route:
                route_changing_movements += 1

            a = inputs.stop_latlon.get((gap.feed, gap.from_stop_ref))
            b = inputs.stop_latlon.get((gap.feed, gap.to_stop_ref))
            if a is None or b is None:
                distance_unknown += 1
                distance_m = None
            else:
                distance_m = haversine_metres(a[0], a[1], b[0], b[1])
                movement_distances.append(distance_m)
                if distance_m < _SAME_PLACE_METRES:
                    near_same_place += 1

            if args.max_segments and written >= args.max_segments:
                continue
            zone = resolve_zone(inputs.agency_tz.get(gap.feed, ""), tz_cache, tz_fallbacks)
            segment = gap_to_deadhead_segment(
                gap, reference_date=reference_date, tz=zone, recorded_at=recorded_at
            )
            out.write(
                json.dumps(
                    {
                        "measurement": "scheduled_deadhead",
                        "deadhead_segment": json.loads(segment.model_dump_json()),
                        "derivation": {
                            "feed_base64_url": gap.feed,
                            "feed_name": inputs.feed_name.get(gap.feed, ""),
                            "agency_name": inputs.agency_name.get(agency_key, ""),
                            "service_ref": gap.service_ref,
                            "from_trip_id": gap.from_trip_id,
                            "to_trip_id": gap.to_trip_id,
                            "changes_route": gap.changes_route,
                            "straight_line_metres": (
                                round(distance_m, 1) if distance_m is not None else None
                            ),
                            "reference_service_date": args.reference_date,
                            "instants_are_nominal": True,
                        },
                    }
                )
                + "\n"
            )
            written += 1

    # ---- summary ----------------------------------------------------------
    def _hours(seconds: float) -> float:
        return round(seconds / 3600.0, 2)

    movement_seconds = sum(m * 60 for m in movement_minutes)
    layover_seconds = sum(m * 60 for m in layover_minutes)
    revenue_seconds = sum(revenue_seconds_by_agency.values())
    in_block_seconds = revenue_seconds + movement_seconds + layover_seconds

    agency_rows = []
    for agency_key, row in per_agency.items():
        feed, agency_id = agency_key
        rev = revenue_seconds_by_agency.get(agency_key, 0)
        denom = rev + row["movement_seconds"] + row["layover_seconds"]
        agency_rows.append(
            {
                "agency_name": inputs.agency_name.get(agency_key, "(unknown)"),
                "feed_name": inputs.feed_name.get(feed, ""),
                "gtfs_agency_id": agency_id,
                "blocks": int(row["blocks"]),
                "movement_gaps": int(row["movement_gaps"]),
                "layover_gaps": int(row["layover_gaps"]),
                "scheduled_deadhead_hours": _hours(row["movement_seconds"]),
                "scheduled_layover_hours": _hours(row["layover_seconds"]),
                "scheduled_revenue_hours": _hours(rev),
                "scheduled_deadhead_share_of_in_block_time": (
                    round(row["movement_seconds"] / denom, 4) if denom else 0.0
                ),
            }
        )
    agency_rows.sort(key=lambda r: -r["scheduled_deadhead_hours"])

    summary = {
        "measurement": "scheduled_deadhead",
        "NOT_COMPARABLE_TO": (
            "NTD operated deadhead (ntd-service-opex-by-mode-timeseries). That series "
            "reports what vehicles DID over a year; this reports what a published "
            "timetable IMPLIES between revenue trips, excluding pull-out and pull-in "
            "entirely. The difference between them is FIRST a definitional gap and only "
            "SECOND an operational finding, and this packet cannot say how much is which."
        ),
        "generated_at": recorded_at.isoformat(),
        "reference_service_date": args.reference_date,
        "instants_are_nominal": True,
        "source": {
            "dataset": "Cal-ITP GTFS-Ingest Pipeline Dataset (Caltrans, data.ca.gov)",
            "licence": "CC-BY; commercial use permitted; see data/catalog/calitp-gtfs-*.manifest.json",
            "objects": {
                ds: json.loads((_CATALOG / f"{ds}.acquired.json").read_text(encoding="utf-8"))[
                    "sha256"
                ]
                for ds in (
                    "calitp-gtfs-trips",
                    "calitp-gtfs-stop-times",
                    "calitp-gtfs-stops",
                    "calitp-gtfs-routes",
                    "calitp-gtfs-agency",
                    "calitp-gtfs-frequencies",
                    "calitp-gtfs-datasets",
                )
            },
        },
        "coverage": {
            "feeds_in_trips": len(feeds_seen),
            "agencies_declared": len(inputs.agency_name),
            "agencies_with_any_trip": len(agency_all_trips),
            "agencies_with_any_block_id": len(agency_block_trips),
            "agencies_with_a_scheduled_deadhead_measurement": len(agencies_with_measurement),
            "trips_total": total_trips,
            "trips_without_block_id": trips_without_block,
            "trips_without_block_id_pct": round(100.0 * trips_without_block / total_trips, 2)
            if total_trips
            else 0.0,
            "trips_frequency_defined_excluded": trips_frequency_excluded,
            "trips_chainable_declared": len(trip_meta),
            "trips_missing_stop_times": trips_missing_times,
            "trips_unusable_times_or_single_stop": unusable_trips,
        },
        "chaining": {
            "blocks": totals.blocks,
            "blocks_with_one_trip_only": totals.single_trip_blocks,
            "blocks_whose_block_id_spans_multiple_service_ids": multi_service_blocks,
            "consecutive_pairs_examined": totals.chained_pairs,
            "pairs_overlapping_dropped": totals.overlapping_pairs,
            "pairs_zero_length_through_routed": totals.zero_length_pairs,
            "pairs_with_a_positive_gap": totals.positive_pairs,
        },
        "split": {
            "movement_gaps_different_stop": len(movement_minutes),
            "layover_gaps_same_stop": len(layover_minutes),
            "movement_gaps_under_50m_apart": near_same_place,
            "movement_gaps_distance_unknown": distance_unknown,
            "movement_gaps_that_change_route": route_changing_movements,
        },
        "scheduled_deadhead_minutes": {
            "n": len(movement_minutes),
            "total_hours": _hours(movement_seconds),
            "mean": round(sum(movement_minutes) / len(movement_minutes), 2)
            if movement_minutes
            else 0.0,
            **percentiles(movement_minutes, (1, 5, 10, 25, 50, 75, 90, 95, 99)),
            "min": round(min(movement_minutes), 2) if movement_minutes else 0.0,
            "max": round(max(movement_minutes), 2) if movement_minutes else 0.0,
        },
        "scheduled_layover_minutes": {
            "n": len(layover_minutes),
            "total_hours": _hours(layover_seconds),
            **percentiles(layover_minutes, (50, 90, 99)),
        },
        "scheduled_deadhead_straight_line_metres": {
            "n": len(movement_distances),
            **percentiles(movement_distances, (10, 50, 90, 99)),
        },
        "share_of_scheduled_in_block_time": {
            "scheduled_revenue_hours": _hours(revenue_seconds),
            "scheduled_deadhead_hours": _hours(movement_seconds),
            "scheduled_layover_hours": _hours(layover_seconds),
            "deadhead_share": round(movement_seconds / in_block_seconds, 4)
            if in_block_seconds
            else 0.0,
            "note": (
                "Denominator is in-block scheduled time only. It excludes pull-out and "
                "pull-in, which GTFS does not publish, so this share is a LOWER BOUND on "
                "the non-revenue share of a real vehicle day."
            ),
        },
        "quality": {
            "sec_column_rows_checked": sec_checked,
            "sec_column_disagreements_with_clock_text": sec_disagreements,
            "timezone_fallbacks": tz_fallbacks,
            "segments_written": written,
            "segments_path": args.segments_out,
        },
        "per_agency": agency_rows,
    }

    summary_path = _REPO_ROOT / args.summary_out
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {summary_path}")
    print(f"wrote {written:,} DeadheadSegments to {segments_out}")
    print(
        f"\nSCHEDULED deadhead (NOT operated): {len(movement_minutes):,} segments, "
        f"{_hours(movement_seconds):,.1f} h, median "
        f"{summary['scheduled_deadhead_minutes']['p50']} min, across "
        f"{len(agencies_with_measurement)} agencies"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
