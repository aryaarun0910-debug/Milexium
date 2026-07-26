"""Conformance for GTFS block-chained SCHEDULED deadhead (MX-C-GTFS-BLOCK-HARVEST-010).

These tests hold the derivation to the three things that decide whether the
number it produces is worth anything:

1. **The arithmetic survives GTFS's own edge cases.** After-midnight times
   (`25:10:00`), stop_times rows out of file order, and a missing `*_sec`
   column are all normal in real feeds and all silently produce a wrong answer
   if handled naively -- a negative gap, a reversed trip, a zero where a
   duration belongs.
2. **What the derivation REFUSES to emit.** Overlapping trips, single-trip
   blocks, same-stop layovers and frequency-defined trips are each excluded for
   a stated reason, and each exclusion is asserted here. An exclusion that
   isn't tested is an exclusion that will quietly stop happening.
3. **The output really is Program A's entity, with the honest field values.**
   `deadhead_type == "other"` and `block_id is None` are not incidental -- they
   are the claims this packet is entitled to make, and a later "improvement"
   that sets `interline` or mints a `Block` should fail here loudly.

The scheduled-vs-operated distinction is itself asserted (not just documented)
in `test_summary_labels_the_measurement_as_scheduled` and
`test_no_artifact_compares_scheduled_against_ntd_silently`: the label has to be
IN the artifacts, because an artifact travels away from its docstring.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.derive_scheduled_deadhead import (  # noqa: E402
    ScheduledGap,
    TripExtent,
    anchor_to_utc,
    chain_block,
    coerce_seconds,
    gap_to_deadhead_segment,
    haversine_metres,
    parse_gtfs_seconds,
    percentiles,
)

_TZ = ZoneInfo("America/Los_Angeles")
_REF = date(2026, 7, 21)
_RECORDED = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)

_SUMMARY = _REPO_ROOT / "data" / "catalog" / "calitp-scheduled-deadhead.summary.json"
_NARRATIVE = _REPO_ROOT / "data" / "catalog" / "calitp-scheduled-deadhead.md"


def _extent(
    first_dep: int,
    last_arr: int,
    first_stop: str = "A",
    last_stop: str = "B",
    rows: int = 2,
) -> TripExtent:
    return TripExtent(
        first_sequence=1,
        last_sequence=rows,
        first_departure_s=first_dep,
        last_arrival_s=last_arr,
        first_stop_ref=first_stop,
        last_stop_ref=last_stop,
        stop_time_rows=rows,
    )


# --------------------------------------------------------------------------
# 1. GTFS time arithmetic
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("00:00:00", 0),
        ("09:07:00", 32820),
        ("23:59:59", 86399),
        ("24:00:00", 86400),
        ("25:10:00", 90600),  # after-midnight service, the whole point
        ("  06:15:30  ", 22530),
    ],
)
def test_after_midnight_times_do_not_wrap(text: str, expected: int) -> None:
    """GTFS hours are unbounded above. If `25:10:00` came back as 4200 s
    (01:10), the last trip of a block would sort before the first and the gap
    before it would be computed as roughly minus 23 hours."""
    assert parse_gtfs_seconds(text) == expected


@pytest.mark.parametrize("text", ["", "   ", None, "9:07", "abc", "09:60:00", "09:07:60", "-1:00:00"])
def test_unusable_times_return_none_not_zero(text: str | None) -> None:
    """None forces the caller to decide. A zero would be a valid-looking
    midnight departure and would silently anchor a trip to the start of the
    service day."""
    assert parse_gtfs_seconds(text) is None


def test_sec_column_is_preferred_and_clock_text_is_the_fallback() -> None:
    assert coerce_seconds("90600", "25:10:00") == 90600
    assert coerce_seconds("", "25:10:00") == 90600  # publisher column empty
    assert coerce_seconds("   ", "09:07:00") == 32820
    assert coerce_seconds("not-a-number", "09:07:00") == 32820
    assert coerce_seconds("", "") is None


def test_service_day_offsets_past_midnight_land_on_the_next_calendar_day() -> None:
    """25:10 on 2026-07-21 local is 01:10 on the 22nd local, which is 08:10 UTC
    (PDT = UTC-7). Getting this wrong makes overnight blocks nonsense."""
    got = anchor_to_utc(_REF, _TZ, 90600)
    assert got == datetime(2026, 7, 22, 8, 10, tzinfo=timezone.utc)
    # and the duration between two anchored instants is exactly the offset delta
    start = anchor_to_utc(_REF, _TZ, 86000)
    assert (got - start).total_seconds() == 90600 - 86000


# --------------------------------------------------------------------------
# 2. Chaining: what is emitted, and what is refused
# --------------------------------------------------------------------------


def _chain(trips):
    return chain_block(trips, feed="F", block_ref="B1", service_ref="WKDY")


def test_a_real_gap_between_two_trips_is_emitted() -> None:
    gaps, stats = _chain(
        [
            ("t1", "r1", _extent(28800, 32400, "A", "B")),  # 08:00 -> 09:00
            ("t2", "r2", _extent(33600, 37200, "C", "D")),  # 09:20 -> 10:00
        ]
    )
    assert stats.positive_pairs == 1
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.duration_seconds == 1200  # 20 minutes
    assert (gap.from_stop_ref, gap.to_stop_ref) == ("B", "C")
    assert gap.is_movement is True
    assert gap.changes_route is True


def test_trips_are_ordered_by_time_not_by_input_order() -> None:
    """A feed hands us a block's trips in arbitrary order. Chaining them as
    given would produce a negative gap and lose the real one."""
    later = ("t2", "r1", _extent(33600, 37200, "C", "D"))
    earlier = ("t1", "r1", _extent(28800, 32400, "A", "B"))
    gaps, _ = _chain([later, earlier])
    assert len(gaps) == 1
    assert gaps[0].from_trip_id == "t1" and gaps[0].to_trip_id == "t2"


def test_overlapping_trips_are_dropped_and_counted_not_emitted() -> None:
    """One block_id claiming a vehicle is in two places at once is evidence the
    id is shared between vehicles. Emitting a negative-duration segment is
    impossible (the entity rejects it); emitting a zero one would hide the
    signal. So it is dropped AND counted."""
    gaps, stats = _chain(
        [
            ("t1", "r1", _extent(28800, 36000, "A", "B")),  # 08:00 -> 10:00
            ("t2", "r1", _extent(32400, 39600, "C", "D")),  # 09:00 -> 11:00
        ]
    )
    assert gaps == []
    assert stats.overlapping_pairs == 1
    assert stats.positive_pairs == 0


def test_through_routed_zero_length_pair_is_counted_but_not_a_deadhead() -> None:
    gaps, stats = _chain(
        [
            ("t1", "r1", _extent(28800, 32400, "A", "B")),
            ("t2", "r2", _extent(32400, 36000, "B", "C")),
        ]
    )
    assert gaps == []
    assert stats.zero_length_pairs == 1


def test_single_trip_block_yields_no_gap_and_is_counted() -> None:
    """A block with one trip has no BETWEEN. Reporting zero deadhead for it
    would drag every average down with a non-measurement."""
    gaps, stats = _chain([("t1", "r1", _extent(28800, 32400))])
    assert gaps == []
    assert stats.single_trip_blocks == 1
    assert stats.chained_pairs == 0


def test_trips_with_unusable_times_are_excluded_before_chaining() -> None:
    """A trip with no end time cannot bound a gap. Including it would chain the
    trip AFTER it directly to the trip BEFORE, inventing one long fictional
    deadhead spanning a real revenue trip."""
    broken = TripExtent(
        first_sequence=1,
        last_sequence=2,
        first_departure_s=28800,
        last_arrival_s=None,
        first_stop_ref="A",
        last_stop_ref="B",
        stop_time_rows=2,
    )
    assert broken.is_usable is False
    gaps, stats = _chain(
        [
            ("t1", "r1", _extent(0, 3600, "A", "B")),
            ("t2", "r1", broken),
            ("t3", "r1", _extent(7200, 10800, "C", "D")),
        ]
    )
    assert stats.chained_pairs == 1
    assert len(gaps) == 1
    assert (gaps[0].from_trip_id, gaps[0].to_trip_id) == ("t1", "t3")


def test_single_stop_trip_is_not_usable() -> None:
    """One stop is a point, not a span; it has no revenue duration to sit
    between two deadheads."""
    assert _extent(28800, 28800, "A", "A", rows=1).is_usable is False


def test_same_stop_gap_is_layover_not_deadhead() -> None:
    """THE honesty split. The schedule says the vehicle ends and restarts in the
    same place, so it asserts no movement. Counting that as deadhead is the
    single easiest way to overstate this measurement."""
    gaps, _ = _chain(
        [
            ("t1", "r1", _extent(28800, 32400, "A", "TERMINAL")),
            ("t2", "r1", _extent(36000, 39600, "TERMINAL", "A")),
        ]
    )
    assert len(gaps) == 1
    assert gaps[0].is_movement is False
    assert gaps[0].duration_seconds == 3600


def test_stop_times_out_of_file_order_still_bound_the_trip_correctly() -> None:
    """TripExtent orders by stop_sequence, not by arrival order in the file.
    Folding rows in reverse must give the same first/last stop and times."""
    forward = TripExtent(10**9, -1, None, None, "", "")
    for seq, stop, arr, dep in [(1, "A", 28800, 28800), (2, "B", 30000, 30060), (3, "C", 32400, 32400)]:
        forward.observe(seq, stop, arr, dep)
    backward = TripExtent(10**9, -1, None, None, "", "")
    for seq, stop, arr, dep in [(3, "C", 32400, 32400), (1, "A", 28800, 28800), (2, "B", 30000, 30060)]:
        backward.observe(seq, stop, arr, dep)
    for extent in (forward, backward):
        assert (extent.first_stop_ref, extent.last_stop_ref) == ("A", "C")
        assert extent.first_departure_s == 28800
        assert extent.last_arrival_s == 32400
        assert extent.revenue_seconds == 3600


# --------------------------------------------------------------------------
# 3. The canonical entity, and the claims it is entitled to make
# --------------------------------------------------------------------------


def _sample_gap(**overrides) -> ScheduledGap:
    base = dict(
        feed="F",
        block_ref="B1",
        service_ref="WKDY",
        from_trip_id="t1",
        to_trip_id="t2",
        from_route_id="r1",
        to_route_id="r2",
        from_stop_ref="B",
        to_stop_ref="C",
        started_s=32400,
        ended_s=33600,
    )
    base.update(overrides)
    return ScheduledGap(**base)


def test_emitted_row_is_program_as_entity_with_real_instants() -> None:
    segment = gap_to_deadhead_segment(
        _sample_gap(), reference_date=_REF, tz=_TZ, recorded_at=_RECORDED
    )
    assert segment.started_at == datetime(2026, 7, 21, 16, 0, tzinfo=timezone.utc)  # 09:00 PDT
    assert segment.ended_at == datetime(2026, 7, 21, 16, 20, tzinfo=timezone.utc)
    assert (segment.ended_at - segment.started_at).total_seconds() == 1200
    assert segment.from_stop_ref == "B" and segment.to_stop_ref == "C"


def test_deadhead_type_is_other_because_gtfs_classifies_nothing() -> None:
    """DeadheadKind's contract: the kind is carried by the source, never
    inferred. GTFS carries none, and guessing `interline` inflates the exact
    number an interlining change is judged by. This test exists to fail if a
    later change starts guessing -- including the tempting guess below, where
    the route genuinely does change."""
    changed_route = gap_to_deadhead_segment(
        _sample_gap(from_route_id="r1", to_route_id="r2"),
        reference_date=_REF,
        tz=_TZ,
        recorded_at=_RECORDED,
    )
    same_route = gap_to_deadhead_segment(
        _sample_gap(from_route_id="r1", to_route_id="r1"),
        reference_date=_REF,
        tz=_TZ,
        recorded_at=_RECORDED,
    )
    assert changed_route.deadhead_type == "other"
    assert same_route.deadhead_type == "other"


def test_no_canonical_block_is_referenced_because_gtfs_has_no_pull_out() -> None:
    """`Block` requires pull_out_at/pull_in_at and GTFS publishes neither, so no
    Block row exists to point at. A non-None block_id here would be a dangling
    typed reference -- exactly what app.canonical.ids exists to prevent."""
    segment = gap_to_deadhead_segment(
        _sample_gap(), reference_date=_REF, tz=_TZ, recorded_at=_RECORDED
    )
    assert segment.block_id is None
    assert segment.block_ref == "B1"


def test_run_ref_carries_the_block_so_a_teardown_can_attribute_the_time() -> None:
    """app.replay.teardown attributes empty time by run_ref and drops rows
    without one into `unattributable`. DeadheadSegment.run_ref is documented as
    the "run/block identifier as the operator writes it", so the GTFS block id
    belongs there; leaving it None would make every derived segment
    unattributable and the teardown useless on this data."""
    segment = gap_to_deadhead_segment(
        _sample_gap(block_ref="BLOCK-7"), reference_date=_REF, tz=_TZ, recorded_at=_RECORDED
    )
    assert segment.run_ref == "BLOCK-7"


def test_no_vehicle_or_deadhead_identifier_is_invented() -> None:
    segment = gap_to_deadhead_segment(
        _sample_gap(), reference_date=_REF, tz=_TZ, recorded_at=_RECORDED
    )
    assert segment.vehicle_ref is None
    assert segment.deadhead_ref is None


def test_a_reversed_gap_can_never_become_a_segment() -> None:
    """Belt and braces: chaining already drops overlaps, and the entity itself
    refuses one. Both layers are asserted because a negative duration would
    SUBTRACT from a teardown's headline empty-time total."""
    with pytest.raises(ValueError, match="ends before it starts"):
        gap_to_deadhead_segment(
            _sample_gap(started_s=36000, ended_s=32400),
            reference_date=_REF,
            tz=_TZ,
            recorded_at=_RECORDED,
        )


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def test_haversine_is_metres_and_zero_for_a_point() -> None:
    assert haversine_metres(37.7749, -122.4194, 37.7749, -122.4194) == pytest.approx(0.0)
    # SF -> LA is ~559 km; a degrees/radians slip would be orders out.
    assert haversine_metres(37.7749, -122.4194, 34.0522, -118.2437) == pytest.approx(
        559_000, rel=0.02
    )


def test_percentiles_are_ordered_and_bracket_the_data() -> None:
    values = [float(v) for v in range(1, 101)]
    got = percentiles(values, (10, 50, 90))
    assert got["p10"] <= got["p50"] <= got["p90"]
    assert got["p50"] == pytest.approx(50.0)
    assert percentiles([], (50,)) == {"p50": 0.0}


# --------------------------------------------------------------------------
# The labelling requirement, asserted on the artifacts themselves
# --------------------------------------------------------------------------


def _summary() -> dict:
    if not _SUMMARY.exists():
        pytest.skip("summary not derived on this checkout (run platform/tools/derive_scheduled_deadhead.py)")
    return json.loads(_SUMMARY.read_text(encoding="utf-8"))


def test_summary_labels_the_measurement_as_scheduled() -> None:
    """The label has to live IN the artifact. A summary JSON gets pasted into a
    slide deck without its docstring, and at that moment the only thing keeping
    someone from reading it as operated deadhead is the field below."""
    summary = _summary()
    assert summary["measurement"] == "scheduled_deadhead"
    assert summary["instants_are_nominal"] is True
    for key in ("scheduled_deadhead_minutes", "scheduled_layover_minutes"):
        assert key in summary, f"{key} missing -- every metric name must carry 'scheduled'"


def test_summary_states_the_ntd_incomparability_and_names_the_definitional_gap_first() -> None:
    summary = _summary()
    text = summary["NOT_COMPARABLE_TO"].lower()
    assert "ntd" in text
    assert "definitional" in text, "the definitional gap must be named explicitly"
    assert text.index("definitional") < text.index("operational"), (
        "the definitional gap must be presented BEFORE the operational finding"
    )
    assert "pull-out" in text and "pull-in" in text, (
        "the excluded deadhead components must be named where the comparison is refused"
    )


def test_summary_reports_the_denominator_not_only_the_headline() -> None:
    """A deadhead figure without its coverage is unreadable: 'agencies with no
    block_id' is not 'agencies with zero deadhead'."""
    coverage = _summary()["coverage"]
    for key in (
        "agencies_with_any_trip",
        "agencies_with_any_block_id",
        "agencies_with_a_scheduled_deadhead_measurement",
        "trips_without_block_id",
    ):
        assert key in coverage, f"coverage is missing {key}"
    assert (
        coverage["agencies_with_a_scheduled_deadhead_measurement"]
        <= coverage["agencies_with_any_block_id"]
        <= coverage["agencies_with_any_trip"]
    ), "coverage counts must nest; a broken join would show up as an inversion here"


def test_share_of_in_block_time_is_declared_a_lower_bound() -> None:
    share = _summary()["share_of_scheduled_in_block_time"]
    assert 0.0 <= share["deadhead_share"] <= 1.0
    assert "lower bound" in share["note"].lower()


def test_narrative_refuses_the_silent_comparison_in_prose() -> None:
    if not _NARRATIVE.exists():
        pytest.skip("narrative not written on this checkout")
    text = _NARRATIVE.read_text(encoding="utf-8").lower()
    assert "scheduled" in text and "operated" in text
    assert "pull-out" in text and "pull-in" in text
    assert "we do not know" in text, (
        "the packet was required to say plainly that it cannot apportion the gap "
        "between definitional and operational causes"
    )


def test_emitted_segments_file_labels_every_row_as_scheduled() -> None:
    """Per-ROW labelling, not just per-file. A JSONL gets split, filtered and
    re-joined; a header-level label would not survive that, and the row would
    arrive somewhere looking like an observed movement."""
    path = _REPO_ROOT / "data" / "canonical" / "calitp-scheduled-deadhead-segments.jsonl"
    if not path.exists():
        pytest.skip("segments not derived on this checkout (gitignored canonical zone)")
    checked = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            assert row["measurement"] == "scheduled_deadhead"
            assert row["derivation"]["instants_are_nominal"] is True
            assert row["deadhead_segment"]["deadhead_type"] == "other"
            assert row["deadhead_segment"]["block_id"] is None
            checked += 1
            if checked >= 5000:
                break
    assert checked > 0, "segments file exists but is empty"
