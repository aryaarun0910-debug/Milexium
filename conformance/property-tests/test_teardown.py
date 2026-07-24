"""Deadhead teardown: which hours, which runs, how much (Program H, v0.1).

Covers the bucket arithmetic and its reconciliation property, the run ranking
and its honest "unattributable" degradation, the failure injections (empty,
single-trip, all-deadhead, zero-deadhead, missing run identifiers), the privacy
boundary (a rider-identifier column is dropped or rejected, never persisted),
and -- load-bearing -- that the money figure stays a hedged modelled envelope
and never a guaranteed saving (ADR-0019 + the outreach hedge).

Ends with an end-to-end demonstration on REAL public data already in this repo
(NYC TLC FHVHV trip records, realdata/raw_tlc/). That is real published data,
NOT operator data -- this repo holds none -- and the teardown labels it as such
via data_provenance="real_public".
"""

from __future__ import annotations

import glob
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from packages.replay import (
    DEADHEAD_TEARDOWN_NOTE,
    FIXED_COST_HEDGE,
    MODELLED_COMPARISON_NOTE,
    CostBasis,
    CostEnvelope,
    DeadheadTeardown,
    RunContribution,
    TeardownError,
    TimeBucket,
    VehicleSegment,
    segment_set_fingerprint,
    teardown_deadhead,
)

RAW_TLC_DIR = Path(__file__).parents[2] / "realdata" / "raw_tlc"

# A fixed real-calendar anchor: Monday 2026-07-20, so weekday() is unambiguous.
MONDAY = datetime(2026, 7, 20, tzinfo=timezone.utc)


def seg(
    *,
    day: int = 0,
    hour: int = 9,
    minute: int = 0,
    minutes: float = 10.0,
    kind: str = "deadhead",
    run: str | None = "RUN-1",
) -> VehicleSegment:
    start = MONDAY + timedelta(days=day, hours=hour, minutes=minute)
    return VehicleSegment(
        started_at=start, ended_at=start + timedelta(minutes=minutes), kind=kind, run_ref=run
    )


def torn_down(segments, **overrides) -> DeadheadTeardown:
    kwargs = dict(
        dataset_label="fixture-week",
        data_provenance="synthetic",
        run_ref_source="run_ref (fixture)",
    )
    kwargs.update(overrides)
    return teardown_deadhead(segments, **kwargs)


def bucket_at(buckets: tuple[TimeBucket, ...], *, day=None, hour=None) -> TimeBucket:
    (found,) = [b for b in buckets if b.day_of_week == day and b.hour_of_day == hour]
    return found


# --------------------------------------------------------------------------
# WHICH HOURS
# --------------------------------------------------------------------------


def test_empty_time_is_localised_to_the_hours_it_actually_happened_in() -> None:
    result = torn_down(
        [
            seg(day=0, hour=6, minutes=30.0),  # Monday 06:00
            seg(day=0, hour=6, minute=30, minutes=15.0),  # Monday 06:30
            seg(day=2, hour=17, minutes=20.0),  # Wednesday 17:00
            seg(day=2, hour=17, minutes=60.0, kind="revenue"),
        ]
    )

    assert result.total_deadhead_minutes == pytest.approx(65.0)
    assert result.total_revenue_minutes == pytest.approx(60.0)
    assert result.deadhead_share_of_vehicle_time == pytest.approx(65.0 / 125.0, abs=1e-6)

    assert bucket_at(result.by_hour_of_day, hour=6).deadhead_minutes == pytest.approx(45.0)
    assert bucket_at(result.by_hour_of_day, hour=17).deadhead_minutes == pytest.approx(20.0)
    assert bucket_at(result.by_hour_of_day, hour=17).revenue_minutes == pytest.approx(60.0)
    # The 17:00 hour is 20 empty minutes out of 80 vehicle minutes.
    assert bucket_at(result.by_hour_of_day, hour=17).deadhead_share_of_bucket == pytest.approx(
        0.25, abs=1e-6
    )

    monday = bucket_at(result.by_day_of_week, day=0)
    assert monday.day_of_week_name == "Monday"
    assert monday.deadhead_minutes == pytest.approx(45.0)
    assert bucket_at(result.by_day_of_week, day=2).day_of_week_name == "Wednesday"

    joint = bucket_at(result.by_day_of_week_and_hour, day=0, hour=6)
    assert joint.deadhead_minutes == pytest.approx(45.0)
    assert joint.share_of_total_deadhead == pytest.approx(45.0 / 65.0, abs=1e-6)


def test_a_segment_crossing_an_hour_boundary_is_split_across_both_hours() -> None:
    """09:50 -> 10:20 is 10 empty minutes in hour 09 and 20 in hour 10. Charging
    it whole to its start hour would place empty time in an hour it did not
    happen in -- the exact error a teardown exists to correct."""
    result = torn_down([seg(hour=9, minute=50, minutes=30.0)])

    assert bucket_at(result.by_hour_of_day, hour=9).deadhead_minutes == pytest.approx(10.0)
    assert bucket_at(result.by_hour_of_day, hour=10).deadhead_minutes == pytest.approx(20.0)
    assert result.total_deadhead_minutes == pytest.approx(30.0)


def test_a_segment_crossing_midnight_is_split_across_both_days() -> None:
    result = torn_down([seg(day=0, hour=23, minute=40, minutes=40.0)])

    assert bucket_at(result.by_day_of_week, day=0).deadhead_minutes == pytest.approx(20.0)
    assert bucket_at(result.by_day_of_week, day=1).deadhead_minutes == pytest.approx(20.0)
    assert bucket_at(result.by_day_of_week_and_hour, day=1, hour=0).deadhead_minutes == pytest.approx(
        20.0
    )


def test_every_grouping_reconciles_to_the_headline_totals() -> None:
    """The reconciliation the manifest's method step 4 promises an operator."""
    segments = [
        seg(day=d, hour=h, minute=45, minutes=37.5, kind=k, run=f"RUN-{d}")
        for d in range(7)
        for h in (0, 8, 23)
        for k in ("deadhead", "revenue")
    ]
    result = torn_down(segments)

    for grouping in (
        result.by_hour_of_day,
        result.by_day_of_week,
        result.by_day_of_week_and_hour,
    ):
        assert sum(b.deadhead_minutes for b in grouping) == pytest.approx(
            result.total_deadhead_minutes, abs=1e-3
        )
        assert sum(b.revenue_minutes for b in grouping) == pytest.approx(
            result.total_revenue_minutes, abs=1e-3
        )

    assert sum(r.deadhead_minutes for r in result.top_runs) == pytest.approx(
        result.total_deadhead_minutes, abs=1e-3
    )


# --------------------------------------------------------------------------
# WHICH RUNS
# --------------------------------------------------------------------------


def test_runs_are_ranked_by_the_empty_time_they_contributed() -> None:
    result = torn_down(
        [
            seg(run="RUN-A", minutes=10.0),
            seg(run="RUN-B", minutes=50.0),
            seg(run="RUN-B", minutes=5.0),
            seg(run="RUN-C", minutes=30.0),
            seg(run="RUN-C", minutes=90.0, kind="revenue"),
        ]
    )

    assert [r.run_ref for r in result.top_runs] == ["RUN-B", "RUN-C", "RUN-A"]
    assert result.top_runs[0].deadhead_minutes == pytest.approx(55.0)
    assert result.top_runs[0].segment_count == 2
    assert result.top_runs[0].share_of_total_deadhead == pytest.approx(55.0 / 95.0, abs=1e-6)
    assert result.top_runs[1].revenue_minutes == pytest.approx(90.0)
    assert result.attributed_run_count == 3
    assert result.unattributable is None
    assert all(r.attributable for r in result.top_runs)


def test_top_n_truncates_the_ranking_but_never_the_unattributable_row() -> None:
    segments = [seg(run=f"RUN-{i}", minutes=float(i + 1)) for i in range(6)]
    segments.append(seg(run=None, minutes=1.0))  # smallest contributor, still reported
    result = torn_down(segments, top_n_runs=2)

    assert len(result.top_runs) == 2
    assert result.attributed_run_count == 6  # the full ranking size is still stated
    assert result.unattributable is not None
    assert result.unattributable.deadhead_minutes == pytest.approx(1.0)


def test_a_missing_run_identifier_is_reported_as_unattributable_not_guessed() -> None:
    """The failure injection: an export that omits the run id must degrade to an
    honest 'we cannot tell you which run this was', never get folded onto a
    neighbouring run."""
    result = torn_down(
        [
            seg(run="RUN-A", minutes=40.0),
            seg(run=None, minutes=25.0),
            seg(run=None, minutes=35.0),
        ]
    )

    assert [r.run_ref for r in result.top_runs] == ["RUN-A"]
    assert result.top_runs[0].deadhead_minutes == pytest.approx(40.0)

    unattributable = result.unattributable
    assert unattributable is not None
    assert unattributable.run_ref is None
    assert unattributable.attributable is False
    assert unattributable.segment_count == 2
    assert unattributable.deadhead_minutes == pytest.approx(60.0)
    assert unattributable.share_of_total_deadhead == pytest.approx(0.6)

    # Nothing went missing and nothing was invented: ranked + unattributable == total.
    assert sum(r.deadhead_minutes for r in result.top_runs) + unattributable.deadhead_minutes == (
        pytest.approx(result.total_deadhead_minutes)
    )


def test_an_export_with_no_run_identifiers_at_all_attributes_nothing() -> None:
    result = torn_down([seg(run=None, minutes=12.0), seg(run=None, minutes=8.0)])

    assert result.top_runs == ()
    assert result.attributed_run_count == 0
    assert result.unattributable is not None
    assert result.unattributable.deadhead_minutes == pytest.approx(20.0)
    assert result.unattributable.share_of_total_deadhead == pytest.approx(1.0)
    # The hours answer still stands even when the runs answer cannot be given.
    assert bucket_at(result.by_hour_of_day, hour=9).deadhead_minutes == pytest.approx(20.0)


def test_a_run_contribution_cannot_claim_attribution_without_an_identifier() -> None:
    with pytest.raises(ValueError):
        RunContribution(
            run_ref=None,
            attributable=True,
            deadhead_minutes=1.0,
            revenue_minutes=0.0,
            segment_count=1,
            share_of_total_deadhead=1.0,
        )


# --------------------------------------------------------------------------
# Failure injections: empty, single trip, all-deadhead, zero-deadhead
# --------------------------------------------------------------------------


def test_empty_input_is_sane_and_divides_by_nothing() -> None:
    result = torn_down([])

    assert result.total_deadhead_minutes == 0.0
    assert result.total_revenue_minutes == 0.0
    assert result.deadhead_share_of_vehicle_time is None  # not a fabricated 0.0
    assert result.by_hour_of_day == ()
    assert result.by_day_of_week == ()
    assert result.by_day_of_week_and_hour == ()
    assert result.top_runs == ()
    assert result.unattributable is None
    assert result.manifest.segment_count == 0
    assert result.manifest.observed_from is None and result.manifest.observed_to is None


def test_a_single_trip_is_torn_down_without_special_casing() -> None:
    result = torn_down([seg(hour=14, minutes=7.5)])

    assert result.total_deadhead_minutes == pytest.approx(7.5)
    assert result.deadhead_share_of_vehicle_time == pytest.approx(1.0)
    assert len(result.by_hour_of_day) == 1
    assert bucket_at(result.by_hour_of_day, hour=14).share_of_total_deadhead == pytest.approx(1.0)
    assert len(result.top_runs) == 1


def test_an_all_deadhead_input_reports_a_full_share_not_an_error() -> None:
    result = torn_down([seg(minutes=10.0), seg(day=3, hour=1, minutes=20.0)])

    assert result.total_revenue_minutes == 0.0
    assert result.deadhead_share_of_vehicle_time == pytest.approx(1.0)
    assert all(b.deadhead_share_of_bucket == pytest.approx(1.0) for b in result.by_hour_of_day)


def test_a_zero_deadhead_input_ranks_no_runs_and_costs_nothing() -> None:
    result = torn_down(
        [seg(kind="revenue", minutes=60.0), seg(kind="revenue", run="RUN-B", minutes=30.0)],
        cost_basis=CostBasis(cost_per_vehicle_hour=80.0, source="fixture rate"),
    )

    assert result.total_deadhead_minutes == 0.0
    assert result.deadhead_share_of_vehicle_time == pytest.approx(0.0)
    assert result.top_runs == ()  # a run with no empty time is not a top contributor
    assert result.attributed_run_count == 0
    # Shares of a zero total are unavailable, never 0/0.
    assert all(b.share_of_total_deadhead is None for b in result.by_hour_of_day)
    assert all(b.deadhead_share_of_bucket == pytest.approx(0.0) for b in result.by_hour_of_day)
    assert result.cost is not None
    assert result.cost.deadhead_hours == 0.0
    assert result.cost.value_at_full_cost == 0.0


def test_a_zero_length_segment_contributes_nothing_but_is_still_counted() -> None:
    result = torn_down([seg(minutes=0.0), seg(minutes=10.0)])

    assert result.manifest.segment_count == 2
    assert result.total_deadhead_minutes == pytest.approx(10.0)
    assert len(result.by_hour_of_day) == 1


def test_a_segment_that_ends_before_it_starts_is_rejected() -> None:
    with pytest.raises(ValueError):
        VehicleSegment(
            started_at=MONDAY + timedelta(hours=2), ended_at=MONDAY, kind="deadhead", run_ref="R"
        )


def test_an_implausibly_long_segment_is_rejected_as_a_parsing_artefact() -> None:
    with pytest.raises(ValueError):
        VehicleSegment(
            started_at=MONDAY, ended_at=MONDAY + timedelta(days=9), kind="deadhead", run_ref="R"
        )


def test_out_of_range_modelling_arguments_are_rejected() -> None:
    with pytest.raises(TeardownError):
        torn_down([], reduction_fraction=1.5)
    with pytest.raises(TeardownError):
        torn_down([], top_n_runs=-1)
    with pytest.raises(TeardownError):
        torn_down([], unmeasured_segments=-1)


def test_unmeasurable_rows_are_reported_rather_than_counted_as_zero_empty_time() -> None:
    result = torn_down(
        [seg(minutes=10.0)],
        unmeasured_segments=412,
        unmeasured_reason="rows whose export published no on-scene timestamp",
    )

    assert result.manifest.unmeasured_segment_count == 412
    assert "on-scene" in result.manifest.unmeasured_reason
    (recorded,) = [i for i in result.manifest.inputs if i.name == "unmeasured_segments"]
    assert recorded.value == "412"


# --------------------------------------------------------------------------
# Privacy: trip structure only
# --------------------------------------------------------------------------


def test_a_rider_identifier_cannot_be_attached_to_a_segment() -> None:
    with pytest.raises(ValueError):
        VehicleSegment(
            started_at=MONDAY,
            ended_at=MONDAY + timedelta(minutes=5),
            kind="deadhead",
            run_ref="RUN-A",
            rider_id="RIDER-000123",
        )


def test_a_rider_identifier_column_is_dropped_when_reading_an_export_row() -> None:
    """A real de-identified operator export still carries rider-level columns.
    from_row reads only the columns it is pointed at, so they never enter the
    teardown at all."""
    row = {
        "block_id": "BLK-7",
        "start": MONDAY,
        "end": MONDAY + timedelta(minutes=6),
        "rider_id": "RIDER-000123",
        "client_name": "A Real Person",
        "phone_number": "+1-555-0100",
    }
    segment = VehicleSegment.from_row(
        row,
        kind="deadhead",
        started_at_column="start",
        ended_at_column="end",
        run_ref_column="block_id",
    )

    assert segment.run_ref == "BLK-7"
    assert set(segment.model_dump()) == {"started_at", "ended_at", "kind", "run_ref"}

    dumped = torn_down([segment]).model_dump_json()
    for leaked in ("RIDER-000123", "A Real Person", "555-0100", "rider_id", "client_name"):
        assert leaked not in dumped


def test_pointing_the_run_mapping_at_a_rider_identifier_is_rejected() -> None:
    """Silently dropping it would leave the caller believing they had run-level
    attribution when they have none, so this raises instead."""
    for column in ("rider_id", "client_ref", "PassengerNumber", "patient_mrn"):
        with pytest.raises(TeardownError):
            VehicleSegment.from_row(
                {"start": MONDAY, "end": MONDAY},
                kind="deadhead",
                started_at_column="start",
                ended_at_column="end",
                run_ref_column=column,
            )


def test_a_row_missing_a_timestamp_yields_no_segment_rather_than_a_guess() -> None:
    row = {"start": MONDAY, "end": None, "block_id": "BLK-7"}
    assert (
        VehicleSegment.from_row(
            row,
            kind="deadhead",
            started_at_column="start",
            ended_at_column="end",
            run_ref_column="block_id",
        )
        is None
    )


def test_no_rider_shaped_field_exists_anywhere_in_the_teardown_contract() -> None:
    banned = ("rider", "passenger", "client", "customer", "patient", "phone", "email", "ssn")
    for model in (
        VehicleSegment,
        DeadheadTeardown,
        TimeBucket,
        RunContribution,
        CostEnvelope,
        CostBasis,
    ):
        for field_name in model.model_fields:
            assert not any(token in field_name.lower() for token in banned), (model, field_name)


# --------------------------------------------------------------------------
# HOW MUCH -- hedged, never guaranteed
# --------------------------------------------------------------------------


def test_empty_time_is_valued_at_the_operators_own_cost_per_hour() -> None:
    result = torn_down(
        [seg(minutes=120.0), seg(minutes=60.0, kind="revenue")],
        cost_basis=CostBasis(
            cost_per_vehicle_hour=100.0,
            source="the agency's own 2024 NTD filing: opex / actual_hours",
            avoidable_share_low=0.3,
            avoidable_share_high=0.6,
        ),
        reduction_fraction=0.10,
    )

    cost = result.cost
    assert cost.deadhead_hours == pytest.approx(2.0)
    assert cost.value_at_full_cost == pytest.approx(200.0)  # 2 empty hours x $100
    # 10% of that, times the operator's own variable share: $6 .. $12.
    assert cost.modelled_envelope_low == pytest.approx(6.0)
    assert cost.modelled_envelope_high == pytest.approx(12.0)
    assert cost.currency == "USD"
    assert "NTD filing" in cost.cost_basis_source


def test_without_a_fixed_versus_variable_split_no_envelope_is_invented() -> None:
    result = torn_down(
        [seg(minutes=120.0)],
        cost_basis=CostBasis(cost_per_vehicle_hour=100.0, source="fixture rate"),
    )

    cost = result.cost
    assert cost.value_at_full_cost == pytest.approx(200.0)  # arithmetic on their own rate
    assert cost.modelled_envelope_low is None and cost.modelled_envelope_high is None
    assert "not supplied" in cost.envelope_basis
    assert "not guessed" in cost.envelope_basis


def test_half_a_fixed_versus_variable_split_is_not_a_split() -> None:
    with pytest.raises(ValueError):
        CostBasis(cost_per_vehicle_hour=100.0, source="s", avoidable_share_low=0.3)
    with pytest.raises(ValueError):
        CostBasis(
            cost_per_vehicle_hour=100.0, source="s", avoidable_share_low=0.7, avoidable_share_high=0.2
        )


def test_no_cost_basis_means_no_money_figure_at_all() -> None:
    assert torn_down([seg(minutes=30.0)]).cost is None


def test_a_money_figure_can_never_be_presented_as_a_guaranteed_saving() -> None:
    result = torn_down(
        [seg(minutes=60.0)],
        cost_basis=CostBasis(
            cost_per_vehicle_hour=90.0,
            source="fixture rate",
            avoidable_share_low=0.2,
            avoidable_share_high=0.5,
        ),
    )
    assert result.cost.is_guaranteed_saving is False
    assert result.cost.hedge == FIXED_COST_HEDGE
    hedge = result.cost.hedge.lower()
    assert "not guaranteed cash" in hedge
    assert "fixed-versus-variable split" in hedge
    assert "do not fall proportionally" in hedge

    with pytest.raises(ValueError):
        CostEnvelope(**{**result.cost.model_dump(), "is_guaranteed_saving": True})


# --------------------------------------------------------------------------
# Framing + evidence discipline
# --------------------------------------------------------------------------


def test_causal_proof_can_never_be_claimed() -> None:
    result = torn_down([seg(minutes=10.0)])
    assert result.causal_proof is False
    assert result.is_modelled is True
    with pytest.raises(ValueError):
        DeadheadTeardown(**{**result.model_dump(), "causal_proof": True})


def test_interpretation_carries_the_modelled_not_causal_and_fixed_cost_boundaries() -> None:
    result = torn_down([seg(minutes=10.0)])
    text = result.interpretation.lower()

    assert result.interpretation == DEADHEAD_TEARDOWN_NOTE
    assert "modelled teardown" in text
    assert "not causal proof" in text
    assert "not a promised saving" in text
    assert "fixed-versus-variable split" in text
    # The ADR-0019 replay discipline is reused verbatim, not restated.
    assert result.manifest.replay_discipline_note == MODELLED_COMPARISON_NOTE
    assert result.manifest.note == DEADHEAD_TEARDOWN_NOTE


def test_the_manifest_lets_an_operator_re_derive_every_figure() -> None:
    result = torn_down(
        [seg(minutes=90.0), seg(minutes=30.0, kind="revenue")],
        cost_basis=CostBasis(
            cost_per_vehicle_hour=76.0,
            source="agency 2024 NTD filing",
            avoidable_share_low=0.25,
            avoidable_share_high=0.55,
        ),
    )
    manifest = result.manifest

    recorded = {i.name: i for i in manifest.inputs}
    assert set(recorded) >= {
        "segment_count",
        "observation_window",
        "run_ref_source",
        "data_provenance",
        "unmeasured_segments",
        "reduction_fraction",
        "cost_per_vehicle_hour",
        "avoidable_share_of_cost_per_hour",
    }
    assert recorded["segment_count"].value == "2"
    assert recorded["cost_per_vehicle_hour"].source == "agency 2024 NTD filing"
    assert recorded["reduction_fraction"].value == "0.1"

    steps = [s.step for s in manifest.method]
    assert steps == [
        "1. classify",
        "2. bucket by clock position",
        "3. attribute to runs",
        "4. reconcile",
        "5. cost",
    ]
    # The costing step only appears when a money figure was actually produced.
    assert len(torn_down([seg(minutes=1.0)]).manifest.method) == 4
    assert manifest.observed_from == MONDAY + timedelta(hours=9)
    assert manifest.run_ref_source == "run_ref (fixture)"


def test_the_teardown_id_is_deterministic_and_the_fingerprint_order_independent() -> None:
    segments = [seg(run="RUN-A", minutes=10.0), seg(run="RUN-B", minutes=20.0, hour=11)]
    first = torn_down(segments)
    reordered = torn_down(list(reversed(segments)))

    assert first.manifest.segment_sha256 == reordered.manifest.segment_sha256
    assert first.manifest.teardown_id == reordered.manifest.teardown_id
    assert segment_set_fingerprint(tuple(segments)) == first.manifest.segment_sha256

    # A different modelling choice is a different teardown, and says so.
    assert torn_down(segments, reduction_fraction=0.2).manifest.teardown_id != first.manifest.teardown_id


def test_provenance_must_be_labelled_and_no_operator_data_label_exists_yet() -> None:
    assert torn_down([seg(minutes=1.0)]).manifest.data_provenance == "synthetic"
    assert (
        torn_down([seg(minutes=1.0)], data_provenance="real_public").manifest.data_provenance
        == "real_public"
    )
    # This repo holds no operator data, so no label can assert one.
    with pytest.raises(ValueError):
        torn_down([seg(minutes=1.0)], data_provenance="operator")


# --------------------------------------------------------------------------
# Demonstration on REAL public data (NYC TLC FHVHV), not operator data
# --------------------------------------------------------------------------

_FHVHV_WEEK_SQL = """
SELECT dispatching_base_num, originating_base_num, request_datetime,
       on_scene_datetime, pickup_datetime, dropoff_datetime
FROM read_parquet('{path}')
WHERE request_datetime >= TIMESTAMP '2019-02-04 00:00:00'
  AND request_datetime <  TIMESTAMP '2019-02-11 00:00:00'
"""


def _fhvhv_week_sample(limit: int = 40000) -> list[dict]:
    """One real calendar week (Mon 2019-02-04 .. Sun 2019-02-10) of NYC TLC FHVHV
    trip records, reservoir-sampled with a fixed seed so the demonstration is
    reproducible. Skips cleanly when the raw corpus is absent (it is gitignored)."""
    files = sorted(glob.glob(str(RAW_TLC_DIR / "fhvhv_tripdata_2019-02.parquet")))
    if not files:
        pytest.skip(f"no fhvhv_tripdata_2019-02.parquet under {RAW_TLC_DIR}")

    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect()
    con.execute("PRAGMA disable_progress_bar")
    week = _FHVHV_WEEK_SQL.format(path=Path(files[0]).as_posix())
    df = con.execute(f"SELECT * FROM ({week}) USING SAMPLE {limit} ROWS (reservoir, 20260724)").fetchdf()
    return df.to_dict(orient="records")


def _fhvhv_segments(rows: list[dict], *, run_ref_column: str) -> tuple[list[VehicleSegment], int]:
    """Map real FHVHV rows onto vehicle segments.

    FHVHV publishes the dispatch instant, the driver's arrival on scene, the
    pickup and the dropoff. request -> on_scene is the vehicle driving EMPTY to
    the pickup: real, published, non-revenue vehicle time. pickup -> dropoff is
    the revenue leg. The curb wait (on_scene -> pickup) is deliberately NOT
    counted as empty time -- it is stationary boarding time, and excluding it
    understates deadhead rather than overstating it.

    Returns (segments, unmeasured_rows): rows whose on-scene timestamp the source
    never published (Lyft/Via did not report it in 2019) are counted, not imputed
    as zero empty time.
    """
    import pandas as pd

    def utc(value) -> datetime | None:
        return None if pd.isna(value) else value.to_pydatetime().replace(tzinfo=timezone.utc)

    segments: list[VehicleSegment] = []
    unmeasured = 0
    for raw in rows:
        row = {
            run_ref_column: raw[run_ref_column],
            "approach_start": utc(raw["request_datetime"]),
            "approach_end": utc(raw["on_scene_datetime"]),
            "revenue_start": utc(raw["pickup_datetime"]),
            "revenue_end": utc(raw["dropoff_datetime"]),
        }
        approach = None
        if (
            row["approach_start"] is not None
            and row["approach_end"] is not None
            and row["approach_end"] >= row["approach_start"]
        ):
            approach = VehicleSegment.from_row(
                row,
                kind="deadhead",
                started_at_column="approach_start",
                ended_at_column="approach_end",
                run_ref_column=run_ref_column,
            )
        if approach is None:
            unmeasured += 1
        else:
            segments.append(approach)

        revenue = VehicleSegment.from_row(
            row,
            kind="revenue",
            started_at_column="revenue_start",
            ended_at_column="revenue_end",
            run_ref_column=run_ref_column,
        )
        if revenue is not None:
            segments.append(revenue)
    return segments, unmeasured


def test_demonstration_on_real_nyc_tlc_fhvhv_trip_records() -> None:
    """End-to-end on REAL public data: a full calendar week of NYC TLC FHVHV
    trip records torn down into which hours, which runs and how much.

    This is real published trip data, NOT operator data -- no operator has sent
    this repo an export, and the teardown labels the source real_public. The
    cost-per-hour is likewise a stand-in national NTD median, not TLC's own.
    """
    rows = _fhvhv_week_sample()
    segments, unmeasured = _fhvhv_segments(rows, run_ref_column="dispatching_base_num")

    result = teardown_deadhead(
        segments,
        dataset_label=(
            "NYC TLC FHVHV trip records, week of 2019-02-04..2019-02-10, "
            f"{len(rows)}-row reservoir sample (seed 20260724)"
        ),
        data_provenance="real_public",
        run_ref_source=(
            "dispatching_base_num -- the TLC-licensed dispatching base. FHVHV publishes no "
            "vehicle, driver or block id, so the base is the finest real fleet unit available; "
            "an operator's own export supplies vehicle_id/block_id/run_id here"
        ),
        cost_basis=CostBasis(
            cost_per_vehicle_hour=76.885,
            source=(
                "STAND-IN rate: national median cost_per_vrh across 2024 NTD demand-response "
                "filings (ntd/agency_economics.csv). TLC publishes no operator cost per "
                "vehicle-hour; this exercises the arithmetic and is not a claim about NYC TNC "
                "economics"
            ),
            avoidable_share_low=0.30,
            avoidable_share_high=0.60,
        ),
        unmeasured_segments=unmeasured,
        unmeasured_reason=(
            "FHVHV rows publishing no on_scene_datetime (Lyft/Via did not report it in 2019); "
            "their empty approach time is unmeasurable and is excluded, not counted as zero"
        ),
    )

    # Real data, honestly labelled.
    assert result.manifest.data_provenance == "real_public"
    assert result.manifest.segment_count == len(segments)
    assert result.manifest.observed_from.year == 2019

    # WHICH HOURS: a full week covers every hour and every weekday.
    assert len(result.by_hour_of_day) == 24
    assert len(result.by_day_of_week) == 7
    assert len(result.by_day_of_week_and_hour) == 168
    assert sum(b.deadhead_minutes for b in result.by_hour_of_day) == pytest.approx(
        result.total_deadhead_minutes, abs=1e-2
    )
    # The shape is real, not flat: the emptiest and least-empty hours differ.
    shares = [b.deadhead_share_of_bucket for b in result.by_hour_of_day]
    assert max(shares) > min(shares)
    assert 0.0 < result.deadhead_share_of_vehicle_time < 1.0

    # WHICH RUNS: the ranking is actionable and concentrated.
    assert result.attributed_run_count > 1
    assert result.top_runs[0].deadhead_minutes >= result.top_runs[-1].deadhead_minutes
    assert result.top_runs[0].share_of_total_deadhead > 0.0

    # HOW MUCH: hedged, and a third of the sample is honestly unmeasurable.
    assert result.cost.value_at_full_cost > 0.0
    assert result.cost.modelled_envelope_low < result.cost.modelled_envelope_high
    assert result.cost.value_at_full_cost > result.cost.modelled_envelope_high
    assert result.cost.is_guaranteed_saving is False
    assert 0 < result.manifest.unmeasured_segment_count < len(rows)
    assert result.causal_proof is False


def test_real_data_missing_run_identifiers_surface_as_unattributable_not_dropped() -> None:
    """The same real week keyed on originating_base_num, which FHVHV leaves null
    on a large minority of real rows (Juno/Via/Lyft publish no originating base).

    Those rows are real vehicle time whose run cannot be named. They land in the
    single unattributable row -- not merged into the bases that WERE named, and
    not dropped, which would have silently removed real vehicle minutes from the
    denominator every share is computed against.

    The honest finding this surfaces: in this source the missingness is
    CORRELATED. The same operators that omit the originating base also omit the
    on-scene timestamp, so the unattributable row carries a large amount of
    revenue time and (in this slice) no measurable empty time at all. An
    operator reading a run ranking has to know that before trusting it.
    """
    rows = _fhvhv_week_sample()
    segments, _ = _fhvhv_segments(rows, run_ref_column="originating_base_num")

    result = teardown_deadhead(
        segments,
        dataset_label="NYC TLC FHVHV week of 2019-02-04, keyed on originating_base_num",
        data_provenance="real_public",
        run_ref_source="originating_base_num (null on a large minority of real FHVHV rows)",
        top_n_runs=100,
    )

    unattributable = result.unattributable
    assert unattributable is not None
    assert unattributable.run_ref is None
    assert unattributable.attributable is False
    assert unattributable.segment_count > 0
    assert unattributable.revenue_minutes > 0.0  # real vehicle time, un-nameable
    assert all(r.run_ref is not None for r in result.top_runs)

    # Correlated missingness, stated rather than hidden.
    assert unattributable.deadhead_minutes == pytest.approx(0.0)
    assert result.total_revenue_minutes > unattributable.revenue_minutes
