"""Baseline-vs-Milexium metric comparison (Program H, v0.1).

Covers the metric math, the auditable manifest, the metamorphic property
(comparing a schedule to itself is all-zero deltas), and -- load-bearing -- the
non-negotiable boundary that this is a *modelled comparison, not causal proof
of savings*, with no monetary figure anywhere (blueprint/01).
"""

from __future__ import annotations

import pytest

from app.replay import (
    MODELLED_COMPARISON_NOTE,
    MetricDelta,
    ReplayComparison,
    ReplayError,
    ScheduleOutcomeSet,
    compare_schedules,
)

from conformance.fixtures.builders import example_tenant, utc
from conformance.fixtures.builders_replay import make_outcome, make_request_ids

REPLAY_INSTANT = utc(2026, 7, 23, 18, 0)


def _metric(comparison: ReplayComparison, name: str) -> MetricDelta:
    (found,) = [m for m in comparison.metrics if m.name == name]
    return found


def _paired_day() -> tuple[ScheduleOutcomeSet, ScheduleOutcomeSet]:
    """Six requests; baseline worse, Milexium better on every metric."""
    tenant = example_tenant()
    r = make_request_ids(tenant.tenant_id, 6)
    t = tenant.tenant_id

    baseline = ScheduleOutcomeSet(
        schedule_label="greedy-baseline",
        provenance="simulated",
        outcomes=(
            make_outcome(t, r[0], on_time=True, excess=6.0, deadhead=10.0),
            make_outcome(t, r[1], on_time=True, excess=6.0, deadhead=10.0),
            make_outcome(t, r[2], on_time=False, excess=4.0, deadhead=10.0),
            make_outcome(t, r[3], on_time=False, excess=4.0, deadhead=10.0),
            make_outcome(t, r[4], served=False, deadhead=None),
            make_outcome(t, r[5], served=False, deadhead=None),
        ),
        available_vehicle_minutes=600.0,
        productive_vehicle_minutes=300.0,
    )
    milexium = ScheduleOutcomeSet(
        schedule_label="milexium",
        provenance="simulated",
        outcomes=(
            make_outcome(t, r[0], on_time=True, excess=2.0, deadhead=6.0),
            make_outcome(t, r[1], on_time=True, excess=2.0, deadhead=6.0),
            make_outcome(t, r[2], on_time=True, excess=2.0, deadhead=6.0),
            make_outcome(t, r[3], on_time=True, excess=2.0, deadhead=6.0),
            make_outcome(t, r[4], on_time=False, excess=2.0, deadhead=6.0),
            make_outcome(t, r[5], served=False, deadhead=None),
        ),
        available_vehicle_minutes=600.0,
        productive_vehicle_minutes=450.0,
    )
    return baseline, milexium


def test_metric_math_baseline_worse_milexium_better() -> None:
    baseline, milexium = _paired_day()
    comparison = compare_schedules(
        baseline, milexium, replay_instant=REPLAY_INSTANT,
        request_set_label="harland-2026-07-23",
    )

    served = _metric(comparison, "served_trips")
    assert (served.baseline, served.milexium, served.delta) == (4.0, 5.0, 1.0)
    assert served.favors_milexium is True

    denials = _metric(comparison, "denials")
    assert (denials.baseline, denials.milexium, denials.delta) == (2.0, 1.0, -1.0)
    assert denials.favors_milexium is True  # fewer denials is better

    otp = _metric(comparison, "on_time_pickup_rate")
    assert otp.baseline == pytest.approx(0.5)
    assert otp.milexium == pytest.approx(0.8)
    assert otp.delta == pytest.approx(0.3)
    assert otp.favors_milexium is True

    excess = _metric(comparison, "mean_excess_ride_time_minutes")
    assert excess.baseline == pytest.approx(5.0)
    assert excess.milexium == pytest.approx(2.0)
    assert excess.delta == pytest.approx(-3.0)
    assert excess.favors_milexium is True  # less excess ride time is better

    deadhead = _metric(comparison, "total_deadhead_minutes")
    assert (deadhead.baseline, deadhead.milexium, deadhead.delta) == (40.0, 30.0, -10.0)
    assert deadhead.favors_milexium is True

    util = _metric(comparison, "utilization")
    assert util.baseline == pytest.approx(0.5)
    assert util.milexium == pytest.approx(0.75)
    assert util.delta == pytest.approx(0.25)
    assert util.basis == "modelled_fleet_accounting"
    assert util.favors_milexium is True


def test_comparing_a_schedule_to_itself_yields_zero_deltas() -> None:
    baseline, _ = _paired_day()
    comparison = compare_schedules(
        baseline, baseline, replay_instant=REPLAY_INSTANT,
        request_set_label="self",
    )
    for metric in comparison.metrics:
        assert metric.delta == 0.0, metric.name
        assert metric.baseline == metric.milexium
        assert metric.favors_milexium is None  # a zero delta favors neither


def test_utilization_is_modelled_and_null_without_fleet_accounting() -> None:
    tenant = example_tenant()
    r = make_request_ids(tenant.tenant_id, 2)
    t = tenant.tenant_id
    no_fleet = ScheduleOutcomeSet(
        schedule_label="no-fleet-accounting",
        provenance="simulated",
        outcomes=(make_outcome(t, r[0]), make_outcome(t, r[1])),
    )
    comparison = compare_schedules(
        no_fleet, no_fleet, replay_instant=REPLAY_INSTANT, request_set_label="x",
    )
    util = _metric(comparison, "utilization")
    assert util.baseline is None and util.milexium is None and util.delta is None
    assert util.basis == "modelled_fleet_accounting"


def test_manifest_pins_request_set_and_replay_id_is_deterministic() -> None:
    baseline, milexium = _paired_day()
    kwargs = dict(replay_instant=REPLAY_INSTANT, request_set_label="harland-2026-07-23")
    a = compare_schedules(baseline, milexium, **kwargs)
    b = compare_schedules(baseline, milexium, **kwargs)

    assert a.manifest.request_count == 6
    assert a.manifest.request_set_sha256 == b.manifest.request_set_sha256
    assert a.manifest.replay_id == b.manifest.replay_id  # reproducible identity
    assert a.manifest.baseline_provenance == "simulated"
    assert len(a.manifest.metric_definitions) == len(a.metrics)


def test_mismatched_request_sets_are_rejected() -> None:
    tenant = example_tenant()
    r = make_request_ids(tenant.tenant_id, 3)
    t = tenant.tenant_id
    left = ScheduleOutcomeSet(
        schedule_label="a", provenance="simulated",
        outcomes=(make_outcome(t, r[0]), make_outcome(t, r[1])),
    )
    right = ScheduleOutcomeSet(
        schedule_label="b", provenance="simulated",
        outcomes=(make_outcome(t, r[0]), make_outcome(t, r[2])),
    )
    with pytest.raises(ReplayError):
        compare_schedules(left, right, replay_instant=REPLAY_INSTANT, request_set_label="x")


def test_duplicate_outcome_for_a_request_is_rejected() -> None:
    tenant = example_tenant()
    r = make_request_ids(tenant.tenant_id, 1)
    t = tenant.tenant_id
    dup = ScheduleOutcomeSet(
        schedule_label="dup", provenance="simulated",
        outcomes=(make_outcome(t, r[0]), make_outcome(t, r[0])),
    )
    with pytest.raises(ReplayError):
        compare_schedules(dup, dup, replay_instant=REPLAY_INSTANT, request_set_label="x")


def test_is_modelled_comparison_flag_follows_provenance() -> None:
    baseline, milexium = _paired_day()
    assert compare_schedules(
        baseline, milexium, replay_instant=REPLAY_INSTANT, request_set_label="x",
    ).is_modelled_comparison is True


def test_interpretation_carries_the_modelled_not_causal_boundary() -> None:
    baseline, milexium = _paired_day()
    comparison = compare_schedules(
        baseline, milexium, replay_instant=REPLAY_INSTANT, request_set_label="x",
    )
    text = comparison.interpretation.lower()
    assert comparison.interpretation == MODELLED_COMPARISON_NOTE
    assert "modelled comparison" in text
    assert "not causal proof" in text
    assert "aggregate demand" in text  # public data validates aggregate, not dispatch
    assert comparison.manifest.note == MODELLED_COMPARISON_NOTE


def test_causal_proof_can_never_be_claimed() -> None:
    baseline, milexium = _paired_day()
    comparison = compare_schedules(
        baseline, milexium, replay_instant=REPLAY_INSTANT, request_set_label="x",
    )
    assert comparison.causal_proof is False
    with pytest.raises(ValueError):
        ReplayComparison(
            manifest=comparison.manifest,
            metrics=comparison.metrics,
            is_modelled_comparison=True,
            causal_proof=True,
        )


def test_no_monetary_savings_field_anywhere() -> None:
    """The boundary forbids a dollar/savings figure -- prove no field or metric
    name smuggles one in."""
    banned = ("saving", "dollar", "usd", "money", "cost", "revenue", "profit")
    models = (ReplayComparison, MetricDelta)
    for model in models:
        for field_name in model.model_fields:
            assert not any(b in field_name.lower() for b in banned), field_name

    baseline, milexium = _paired_day()
    comparison = compare_schedules(
        baseline, milexium, replay_instant=REPLAY_INSTANT, request_set_label="x",
    )
    for metric in comparison.metrics:
        assert not any(b in metric.name.lower() for b in banned)
        assert metric.unit in ("trips", "fraction", "minutes")
