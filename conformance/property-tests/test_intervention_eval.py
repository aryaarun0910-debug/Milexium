"""Before/after intervention evaluation (Program H, v0.1).

Covers the pre-registration mechanics, the pre/post and difference-in-differences
arithmetic, the regression-to-the-mean diagnostic, the seven mandatory
confounders -- and, load-bearing, the refusals: that an uncontrolled before/after
CANNOT be typed into a causal or a confounders-addressed claim, that no
confounder can be marked ruled out, and that the estimate cannot be quoted
without its qualification.

The tests that matter here are the ones that fail when the refusal is removed.
"""

from __future__ import annotations

import math
import typing
from datetime import datetime, timedelta, timezone

import pytest

from packages.replay import (
    ASSOCIATION_NOTE,
    MANDATORY_CONFOUNDERS,
    MIN_HISTORY_PERIODS_FOR_REVERSION,
    MIN_PERIODS_PER_WINDOW,
    REFUSALS,
    AssociationEstimate,
    ConfounderAssessment,
    DemandMix,
    InterventionError,
    InterventionEvaluation,
    MetricSeries,
    MetricSpec,
    PreRegistration,
    ReversionDiagnostic,
    SeriesPoint,
    ServiceChange,
    Window,
    evaluate_intervention,
    pre_register,
    pre_register_family,
    series_fingerprint,
)
from packages.replay import intervention as iv


def utc(year: int, month: int, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


OTP = MetricSpec(
    name="on_time_pickup_rate",
    unit="fraction",
    higher_is_better=True,
    definition="served trips picked up inside the negotiated window / served trips",
)
COST = MetricSpec(
    name="cost_per_trip",
    unit="USD",
    higher_is_better=False,
    definition="operating expense attributable to demand response / unlinked passenger trips",
)
DENIALS = MetricSpec(
    name="denial_rate",
    unit="fraction",
    higher_is_better=False,
    definition="requests refused / requests received",
)

HISTORY_START = utc(2021, 1)
PRE_START = utc(2024, 1)
INTERVENTION_AT = utc(2025, 1)
POST_END = utc(2026, 1)
PRE_WINDOW = Window(starts_at=PRE_START, ends_at=INTERVENTION_AT)
POST_WINDOW = Window(starts_at=INTERVENTION_AT, ends_at=POST_END)


def registration(
    *,
    design: str = "uncontrolled_pre_post",
    registered_at: datetime = utc(2024, 12),
    metric: MetricSpec = OTP,
    expected_direction: str = "increase",
    pre_window: Window = PRE_WINDOW,
    post_window: Window = POST_WINDOW,
    family_metrics: tuple[str, ...] | None = None,
) -> PreRegistration:
    return pre_register(
        registered_at=registered_at,
        intervention_label="scheduling system go-live",
        intervention_at=INTERVENTION_AT,
        metric=metric,
        expected_direction=expected_direction,  # type: ignore[arg-type]
        pre_window=pre_window,
        post_window=post_window,
        design=design,  # type: ignore[arg-type]
        control_plan="fixed in advance",
        family_metrics=family_metrics,
    )


def months(start: datetime, count: int) -> list[datetime]:
    stamps = []
    year, month = start.year, start.month
    for _ in range(count):
        stamps.append(datetime(year, month, 1, tzinfo=timezone.utc))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return stamps


def series(
    values_by_start: list[tuple[datetime, float]],
    *,
    metric_name: str = OTP.name,
    label: str = "treated agency",
    exposure: float | None = None,
    fleet_size: float | None = None,
    provenance: str = "synthetic",
) -> MetricSeries:
    return MetricSeries(
        label=label,
        metric_name=metric_name,
        provenance=provenance,  # type: ignore[arg-type]
        points=tuple(
            SeriesPoint(period_start=start, value=value, exposure=exposure, fleet_size=fleet_size)
            for start, value in values_by_start
        ),
    )


def flat_then_step(
    *,
    history_value: float,
    pre_value: float,
    post_value: float,
    wobble: float = 0.004,
    history_months: int = 36,
) -> MetricSeries:
    """A deterministic series: `history_months` of history, 12 pre months, 12
    post months, each level plus a small repeating wobble so the windows have
    dispersion without a random seed."""
    points: list[tuple[datetime, float]] = []
    history_start = PRE_START - timedelta(days=31 * history_months)
    history_start = datetime(history_start.year, history_start.month, 1, tzinfo=timezone.utc)
    for index, start in enumerate(months(history_start, history_months)):
        points.append((start, history_value + wobble * ((index % 3) - 1)))
    for index, start in enumerate(months(PRE_START, 12)):
        points.append((start, pre_value + wobble * ((index % 3) - 1)))
    for index, start in enumerate(months(INTERVENTION_AT, 12)):
        points.append((start, post_value + wobble * ((index % 3) - 1)))
    seen: dict[datetime, float] = {}
    for start, value in points:
        seen[start] = value
    return series(sorted(seen.items()), exposure=1000.0, fleet_size=50.0)


def evaluate(
    treated: MetricSeries,
    *,
    reg: PreRegistration | None = None,
    **kwargs,
) -> InterventionEvaluation:
    return evaluate_intervention(
        reg or registration(),
        treated,
        dataset_label="synthetic fixture",
        data_provenance="synthetic",
        **kwargs,
    )


def confounder(evaluation: InterventionEvaluation, name: str) -> ConfounderAssessment:
    (found,) = [c for c in evaluation.confounders if c.name == name]
    return found


# ---------------------------------------------------------------------------
# Pre-registration
# ---------------------------------------------------------------------------


def test_registration_hash_is_deterministic_in_the_registered_fields() -> None:
    a, b = registration(), registration()
    assert a.registration_sha256 == b.registration_sha256
    assert len(a.registration_sha256) == 64

    # A different post window is a different registration and a different hash.
    other = registration(post_window=Window(starts_at=INTERVENTION_AT, ends_at=utc(2026, 7)))
    assert other.registration_sha256 != a.registration_sha256


def test_a_registration_whose_hash_no_longer_matches_its_fields_is_rejected() -> None:
    """The published hash is what makes a pre-registration checkable; a
    registration edited after publication must not construct."""
    original = registration()
    tampered = original.model_dump()
    tampered["expected_direction"] = "decrease"  # the story, retold
    with pytest.raises(ValueError, match="registration_sha256"):
        PreRegistration(**tampered)


def test_a_late_registration_cannot_call_itself_prospective() -> None:
    late = registration(registered_at=utc(2025, 6))  # post window opened 2025-01
    assert late.registration_timing == "retrospective_reconstruction"

    forged = late.model_dump()
    forged["registration_timing"] = "prospective"
    with pytest.raises(ValueError, match="cannot assert it predates"):
        PreRegistration(**forged)


def test_a_registration_on_the_day_the_post_window_opens_is_still_prospective() -> None:
    assert registration(registered_at=INTERVENTION_AT).registration_timing == "prospective"
    assert (
        registration(registered_at=INTERVENTION_AT + timedelta(seconds=1)).registration_timing
        == "retrospective_reconstruction"
    )


def test_registering_a_family_divides_alpha_across_every_metric_in_it() -> None:
    family = pre_register_family(
        registered_at=utc(2024, 12),
        intervention_label="go-live",
        intervention_at=INTERVENTION_AT,
        metrics=[OTP, COST, DENIALS],
        expected_directions={
            OTP.name: "increase",
            COST.name: "decrease",
            DENIALS.name: "decrease",
        },
        pre_window=PRE_WINDOW,
        post_window=POST_WINDOW,
        design="uncontrolled_pre_post",
        control_plan="none",
    )
    assert len(family) == 3
    for member in family:
        assert member.family_size == 3
        assert member.family_metrics == (OTP.name, COST.name, DENIALS.name)
        assert member.corrected_alpha == pytest.approx(0.05 / 3)
    # A single registration is not silently discounted the same way.
    assert registration().corrected_alpha == pytest.approx(0.05)


def test_the_family_correction_reaches_the_reported_estimate() -> None:
    """Registering siblings must actually make the winner harder to call, not
    merely be recorded."""
    # Sized so the estimate clears 0.05 but not 0.05/3: exactly the band in which
    # registering siblings changes the answer.
    treated = flat_then_step(history_value=0.80, pre_value=0.80, post_value=0.824, wobble=0.03)
    alone = evaluate(treated)
    assert 0.05 / 3 < alone.association.p_value < 0.05
    family = pre_register_family(
        registered_at=utc(2024, 12),
        intervention_label="go-live",
        intervention_at=INTERVENTION_AT,
        metrics=[OTP, COST, DENIALS],
        expected_directions={OTP.name: "increase", COST.name: "decrease", DENIALS.name: "decrease"},
        pre_window=PRE_WINDOW,
        post_window=POST_WINDOW,
        design="uncontrolled_pre_post",
        control_plan="none",
    )
    shopped = evaluate(treated, reg=family[0])

    assert alone.association.p_value == pytest.approx(shopped.association.p_value)
    assert shopped.association.corrected_alpha < alone.association.corrected_alpha
    assert alone.association.distinguishable_from_no_change is True
    assert shopped.association.distinguishable_from_no_change is False
    assert alone.direction_verdict == "moved_in_pre_registered_direction"
    assert shopped.direction_verdict == "no_detectable_change"


def test_a_metric_outside_the_registered_family_cannot_be_registered() -> None:
    with pytest.raises(InterventionError, match="not in family_metrics"):
        registration(metric=OTP, family_metrics=(COST.name, DENIALS.name))


def test_family_size_and_family_metrics_cannot_disagree() -> None:
    forged = registration().model_dump()
    forged["family_size"] = 4  # four chances taken, one declared
    with pytest.raises(ValueError, match="family_size"):
        PreRegistration(**forged)


def test_a_family_without_a_direction_for_every_metric_is_rejected() -> None:
    with pytest.raises(InterventionError, match="no expected direction"):
        pre_register_family(
            registered_at=utc(2024, 12),
            intervention_label="go-live",
            intervention_at=INTERVENTION_AT,
            metrics=[OTP, COST],
            expected_directions={OTP.name: "increase"},
            pre_window=PRE_WINDOW,
            post_window=POST_WINDOW,
            design="uncontrolled_pre_post",
            control_plan="none",
        )


def test_a_pre_window_containing_the_intervention_is_rejected() -> None:
    with pytest.raises(ValueError, match="pre_window ends after the intervention"):
        registration(pre_window=Window(starts_at=PRE_START, ends_at=utc(2025, 6)))


def test_a_post_window_opening_before_the_intervention_is_rejected() -> None:
    with pytest.raises(ValueError, match="post_window starts before the intervention"):
        registration(post_window=Window(starts_at=utc(2024, 6), ends_at=POST_END))


def test_a_window_that_ends_before_it_starts_is_rejected() -> None:
    with pytest.raises(ValueError, match="ends at or before it starts"):
        Window(starts_at=utc(2025, 1), ends_at=utc(2024, 1))


# ---------------------------------------------------------------------------
# Design and series guards
# ---------------------------------------------------------------------------


def test_evaluating_a_metric_other_than_the_registered_one_is_rejected() -> None:
    treated = flat_then_step(history_value=0.8, pre_value=0.8, post_value=0.9)
    swapped = treated.model_copy(update={"metric_name": COST.name})
    with pytest.raises(InterventionError, match="the substitution the"):
        evaluate(swapped)


def test_adding_a_control_to_an_uncontrolled_registration_is_rejected() -> None:
    treated = flat_then_step(history_value=0.8, pre_value=0.8, post_value=0.9)
    control = treated.model_copy(update={"label": "peers"})
    with pytest.raises(InterventionError, match="requires a new pre-registration"):
        evaluate(treated, control=control)


def test_a_registered_did_design_without_a_control_is_rejected() -> None:
    treated = flat_then_step(history_value=0.8, pre_value=0.8, post_value=0.9)
    with pytest.raises(InterventionError, match="no control"):
        evaluate(treated, reg=registration(design="difference_in_differences"))


def test_a_series_with_two_values_for_one_period_is_rejected() -> None:
    with pytest.raises(ValueError, match="more than one point for the same"):
        series([(utc(2024, 1), 0.8), (utc(2024, 1), 0.9)])


def test_series_fingerprint_is_order_independent() -> None:
    forward = flat_then_step(history_value=0.8, pre_value=0.8, post_value=0.9)
    backward = forward.model_copy(update={"points": tuple(reversed(forward.points))})
    assert series_fingerprint(forward) == series_fingerprint(backward)
    changed = forward.model_copy(
        update={"points": forward.points[:-1] + (
            forward.points[-1].model_copy(update={"value": 0.99}),
        )}
    )
    assert series_fingerprint(changed) != series_fingerprint(forward)


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------


def test_the_estimate_is_the_difference_of_the_two_window_means() -> None:
    treated = flat_then_step(history_value=0.80, pre_value=0.70, post_value=0.79)
    evaluation = evaluate(treated)
    pre_values = [p.value for p in treated.points if PRE_WINDOW.contains(p.period_start)]
    post_values = [p.value for p in treated.points if POST_WINDOW.contains(p.period_start)]

    assert evaluation.pre_window_summary.period_count == 12
    assert evaluation.post_window_summary.period_count == 12
    assert evaluation.pre_window_summary.mean == pytest.approx(sum(pre_values) / 12)
    assert evaluation.post_window_summary.mean == pytest.approx(sum(post_values) / 12)
    assert evaluation.association.estimate == pytest.approx(
        sum(post_values) / 12 - sum(pre_values) / 12
    )
    assert evaluation.association.relative_change == pytest.approx(
        evaluation.association.estimate / abs(evaluation.pre_window_summary.mean)
    )


def test_welch_p_value_matches_an_independently_computed_reference() -> None:
    """The t-distribution is computed here rather than imported (the
    packages/core/drift.py precedent). Pin it against a hand-checked value."""
    # t = 3.0 on 8 df -> p = 0.0170716812337826 (scipy.stats.t.sf(3, 8) * 2).
    assert iv._t_two_sided_p(3.0, 8.0) == pytest.approx(0.0170716812337826, abs=1e-12)
    assert iv._t_two_sided_p(1.0, 10.0) == pytest.approx(0.340893132302258, abs=1e-12)
    assert iv._t_two_sided_p(0.0, 5.0) == pytest.approx(1.0)
    # Student-t critical values, checked against published tables.
    assert iv._t_critical(10.0, 0.05) == pytest.approx(2.2281388519, abs=1e-8)
    assert iv._t_critical(5.0, 0.01) == pytest.approx(4.0321429836, abs=1e-8)

    pre = [1.0, 2.0, 3.0, 4.0, 5.0]
    post = [4.0, 5.0, 6.0, 7.0, 8.0]
    result = iv._welch(pre, post, n_pre=5, n_post=5)
    assert result.difference == pytest.approx(3.0)
    assert result.standard_error == pytest.approx(math.sqrt(2.5 / 5 + 2.5 / 5))
    assert result.df == pytest.approx(8.0)
    assert result.p_value == pytest.approx(0.0170716812337826, abs=1e-12)


def test_the_more_conservative_p_value_is_the_one_acted_on() -> None:
    """An autocorrelated series must not be allowed to borrow significance from
    the independence assumption."""
    # A drifting pre window and a drifting post window: strongly positive rho.
    points = [(start, 0.70 + 0.002 * i) for i, start in enumerate(months(HISTORY_START, 36))]
    points += [(start, 0.70 + 0.002 * i) for i, start in enumerate(months(PRE_START, 12))]
    points += [(start, 0.78 + 0.002 * i) for i, start in enumerate(months(INTERVENTION_AT, 12))]
    evaluation = evaluate(series(points))
    association = evaluation.association

    assert association.lag1_autocorrelation is not None
    assert association.lag1_autocorrelation > iv.AUTOCORRELATION_ATTENTION
    assert association.p_value_autocorrelation_adjusted is not None
    assert association.p_value_autocorrelation_adjusted > association.p_value_iid
    assert association.p_value == association.p_value_autocorrelation_adjusted
    assert association.effective_pre_periods < 12
    assert "independence assumption is violated" in association.interval_caveat


def test_a_flat_series_reports_no_detectable_change() -> None:
    evaluation = evaluate(flat_then_step(history_value=0.80, pre_value=0.80, post_value=0.80))
    assert evaluation.association.estimate == pytest.approx(0.0, abs=1e-12)
    assert evaluation.association.distinguishable_from_no_change is False
    assert evaluation.direction_verdict == "no_detectable_change"
    assert evaluation.attribution_verdict == "insufficient_to_attribute"


def test_too_few_periods_a_side_refuses_to_produce_an_estimate() -> None:
    points = [(start, 0.8) for start in months(HISTORY_START, 36)]
    points += [(start, 0.8) for start in months(PRE_START, 12)]
    points += [(start, 0.9) for start in months(INTERVENTION_AT, MIN_PERIODS_PER_WINDOW - 1)]
    evaluation = evaluate(series(points))

    assert evaluation.post_window_summary.period_count == MIN_PERIODS_PER_WINDOW - 1
    assert evaluation.association.estimate is None
    assert evaluation.association.interval_low is None
    assert evaluation.association.p_value is None
    assert evaluation.direction_verdict == "insufficient_data"
    assert evaluation.evidence_strength == "insufficient"
    assert "a decoration" in evaluation.association.interval_caveat


def test_a_metric_moving_against_the_registered_direction_is_said_so() -> None:
    """The registration expected an increase. The metric fell. The evaluation
    must report that, not re-tell the story as a win on a different reading."""
    treated = flat_then_step(history_value=0.80, pre_value=0.80, post_value=0.60)
    evaluation = evaluate(treated)

    assert evaluation.association.estimate < 0
    assert evaluation.association.distinguishable_from_no_change is True
    assert evaluation.direction_matched_pre_registration is False
    assert evaluation.direction_verdict == "moved_against_pre_registered_direction"
    assert evaluation.attribution_verdict == "insufficient_to_attribute"


def test_a_decrease_metric_registered_to_fall_reads_a_fall_as_the_expected_direction() -> None:
    points = [(start, 40.0) for start in months(HISTORY_START, 36)]
    points += [(start, 40.0 + 0.1 * (i % 3)) for i, start in enumerate(months(PRE_START, 12))]
    points += [(start, 34.0 + 0.1 * (i % 3)) for i, start in enumerate(months(INTERVENTION_AT, 12))]
    evaluation = evaluate(
        series(points, metric_name=COST.name),
        reg=registration(metric=COST, expected_direction="decrease"),
    )
    assert evaluation.association.estimate < 0
    assert evaluation.direction_verdict == "moved_in_pre_registered_direction"
    assert evaluation.direction_matched_pre_registration is True


# ---------------------------------------------------------------------------
# The confounders
# ---------------------------------------------------------------------------


def test_every_mandatory_confounder_appears_in_every_evaluation() -> None:
    evaluation = evaluate(flat_then_step(history_value=0.8, pre_value=0.8, post_value=0.85))
    assert tuple(c.name for c in evaluation.confounders) == MANDATORY_CONFOUNDERS
    assert set(MANDATORY_CONFOUNDERS) >= {
        "seasonality",
        "concurrent_service_change",
        "demand_mix_shift",
        "fleet_change",
        "regression_to_the_mean",
    }


def test_an_evaluation_that_drops_a_mandatory_confounder_cannot_be_constructed() -> None:
    evaluation = evaluate(flat_then_step(history_value=0.8, pre_value=0.8, post_value=0.85))
    assert len(evaluation.confounders) == len(MANDATORY_CONFOUNDERS)
    for dropped in MANDATORY_CONFOUNDERS:
        kept = [c for c in evaluation.confounders if c.name != dropped]
        body = evaluation.model_dump()
        body["confounders"] = [c.model_dump() for c in kept]
        # Keep the summary consistent so the raise can only come from the
        # mandatory-confounder guard, not from the agreement guard.
        body["unresolved_confounders"] = [c.name for c in kept if c.unresolved]
        with pytest.raises(ValueError, match=f"omits mandatory confounder.*{dropped}"):
            InterventionEvaluation(**body)


def test_the_confounder_status_vocabulary_has_no_ruled_out_value() -> None:
    values = set(typing.get_args(iv.ConfounderStatus))
    assert values == {
        "cannot_rule_out",
        "present_uncontrolled",
        "quantified_not_removed",
        "partially_addressed_by_design",
        "declared_absent_unverified",
    }
    for forbidden in ("ruled_out", "controlled", "eliminated", "adjusted_away", "none"):
        assert forbidden not in values
        with pytest.raises(ValueError):
            ConfounderAssessment(
                name="seasonality", status=forbidden, why="x", direction_of_bias="unknown"
            )


def test_nothing_supplied_means_cannot_rule_out_not_absent() -> None:
    """The default when a caller says nothing must be the unfavourable one."""
    points = [(start, 0.8) for start in months(HISTORY_START, 36)]
    points += [(start, 0.8) for start in months(PRE_START, 12)]
    points += [(start, 0.85) for start in months(INTERVENTION_AT, 12)]
    bare = series(points)  # no exposure, no fleet_size
    evaluation = evaluate(bare)

    assert confounder(evaluation, "concurrent_service_change").status == "cannot_rule_out"
    assert confounder(evaluation, "demand_mix_shift").status == "cannot_rule_out"
    assert confounder(evaluation, "fleet_change").status == "cannot_rule_out"
    assert confounder(evaluation, "measurement_definition_change").status == "cannot_rule_out"
    assert confounder(evaluation, "secular_trend_and_external_shocks").status == "cannot_rule_out"


def test_investigated_and_declared_absent_is_a_different_state_from_nobody_looked() -> None:
    treated = flat_then_step(history_value=0.8, pre_value=0.8, post_value=0.85)
    silent = evaluate(treated, known_service_changes=None)
    declared = evaluate(treated, known_service_changes=())
    present = evaluate(
        treated,
        known_service_changes=(
            ServiceChange(
                label="service area extension",
                effective_at=utc(2025, 3),
                description="two new census tracts added",
                expected_direction_on_metric="increase",
            ),
        ),
    )
    assert confounder(silent, "concurrent_service_change").status == "cannot_rule_out"
    assert confounder(declared, "concurrent_service_change").status == "declared_absent_unverified"
    assert confounder(present, "concurrent_service_change").status == "present_uncontrolled"
    assert (
        confounder(present, "concurrent_service_change").direction_of_bias
        == "would_flatter_the_intervention"
    )
    assert "service area extension" in confounder(present, "concurrent_service_change").why


def test_a_declared_change_pushing_the_other_way_penalises_rather_than_flatters() -> None:
    treated = flat_then_step(history_value=0.8, pre_value=0.8, post_value=0.85)
    evaluation = evaluate(
        treated,
        known_service_changes=(
            ServiceChange(
                label="fleet reduction",
                effective_at=utc(2025, 2),
                description="eight vehicles withdrawn",
                expected_direction_on_metric="decrease",
            ),
        ),
    )
    assert (
        confounder(evaluation, "concurrent_service_change").direction_of_bias
        == "would_penalise_the_intervention"
    )


def test_misaligned_calendar_months_leave_seasonality_unresolved() -> None:
    """Six winter months against six summer months is a season, not a system."""
    pre = Window(starts_at=utc(2024, 7), ends_at=INTERVENTION_AT)
    post = Window(starts_at=INTERVENTION_AT, ends_at=utc(2025, 7))
    points = [(start, 0.8) for start in months(HISTORY_START, 36)]
    points += [(start, 0.80 + 0.004 * (i % 3)) for i, start in enumerate(months(utc(2024, 7), 6))]
    points += [(start, 0.85 + 0.004 * (i % 3)) for i, start in enumerate(months(INTERVENTION_AT, 6))]
    evaluation = evaluate(series(points), reg=registration(pre_window=pre, post_window=post))

    seasonality = confounder(evaluation, "seasonality")
    assert seasonality.status == "cannot_rule_out"
    assert "different calendar months" in seasonality.why
    assert "seasonality" in evaluation.unresolved_confounders


def test_calendar_aligned_windows_partially_address_seasonality_and_no_more() -> None:
    evaluation = evaluate(flat_then_step(history_value=0.8, pre_value=0.8, post_value=0.85))
    seasonality = confounder(evaluation, "seasonality")
    assert seasonality.status == "partially_addressed_by_design"
    assert "unusually severe" in seasonality.why
    assert "seasonality" not in evaluation.unresolved_confounders


def test_fleet_change_is_quantified_only_when_fleet_sizes_are_supplied() -> None:
    points_pre = [(start, 0.8) for start in months(HISTORY_START, 36)]
    points_pre += [(start, 0.80) for start in months(PRE_START, 12)]
    points_post = [(start, 0.85) for start in months(INTERVENTION_AT, 12)]
    grown = MetricSeries(
        label="grew its fleet",
        metric_name=OTP.name,
        provenance="synthetic",
        points=tuple(
            [SeriesPoint(period_start=s, value=v, fleet_size=50.0) for s, v in points_pre]
            + [SeriesPoint(period_start=s, value=v, fleet_size=65.0) for s, v in points_post]
        ),
    )
    evaluation = evaluate(grown)
    fleet = confounder(evaluation, "fleet_change")
    assert fleet.status == "quantified_not_removed"
    assert "50" in fleet.why and "65" in fleet.why
    assert "fleet_change" not in evaluation.unresolved_confounders


def test_demand_mix_is_measured_and_explicitly_not_adjusted_for() -> None:
    treated = flat_then_step(history_value=0.8, pre_value=0.8, post_value=0.85)
    evaluation = evaluate(
        treated,
        demand_mix=DemandMix(
            pre={"ambulatory": 0.70, "wheelchair": 0.30},
            post={"ambulatory": 0.55, "wheelchair": 0.45},
            source="operator trip file",
        ),
    )
    mix = confounder(evaluation, "demand_mix_shift")
    assert mix.status == "quantified_not_removed"
    assert "does NOT adjust" in mix.why
    values = {d.name: d.value for d in mix.diagnostics}
    assert values["demand_mix_total_variation_distance"] == "0.1500"


def test_a_metric_produced_by_the_system_under_evaluation_is_flagged_as_flattering() -> None:
    treated = flat_then_step(history_value=0.8, pre_value=0.8, post_value=0.85)
    self_reported = evaluate(treated, metric_measured_by="system_under_evaluation")
    independent = evaluate(treated, metric_measured_by="independent_of_intervention")

    flagged = confounder(self_reported, "measurement_definition_change")
    assert flagged.status == "present_uncontrolled"
    assert flagged.direction_of_bias == "would_flatter_the_intervention"
    assert "measurement_definition_change" in self_reported.unresolved_confounders
    assert (
        confounder(independent, "measurement_definition_change").status
        == "declared_absent_unverified"
    )
    assert "measurement_definition_change" not in independent.unresolved_confounders


def test_the_top_level_unresolved_list_cannot_disagree_with_the_assessments() -> None:
    evaluation = evaluate(flat_then_step(history_value=0.8, pre_value=0.8, post_value=0.85))
    assert evaluation.unresolved_confounders == tuple(
        c.name for c in evaluation.confounders if c.unresolved
    )
    body = evaluation.model_dump()
    body["unresolved_confounders"] = []  # a clean-looking headline over a dirty detail
    with pytest.raises(ValueError, match="must not be able to disagree"):
        InterventionEvaluation(**body)


# ---------------------------------------------------------------------------
# Regression to the mean -- the one that matters most
# ---------------------------------------------------------------------------


def test_a_bad_pre_window_makes_mean_reversion_explain_the_whole_improvement() -> None:
    """The failure mode the packet exists for: three good years, one bad year,
    a procurement, and a rebound that is entirely the agency's own average."""
    treated = flat_then_step(history_value=0.80, pre_value=0.70, post_value=0.79)
    evaluation = evaluate(treated)
    reversion = evaluation.regression_to_the_mean

    assert reversion.assessable is True
    assert reversion.long_run_mean == pytest.approx(0.80, abs=1e-6)
    assert reversion.pre_window_was_adverse is True
    assert reversion.pre_window_deviation_from_long_run == pytest.approx(-0.10, abs=1e-6)
    assert reversion.predicted_change_from_reversion == pytest.approx(0.10, abs=1e-6)
    assert reversion.share_of_observed_change_explained_by_reversion == pytest.approx(
        10.0 / 9.0, abs=1e-6
    )
    assert reversion.residual_change_beyond_reversion == pytest.approx(-0.01, abs=1e-6)

    flagged = confounder(evaluation, "regression_to_the_mean")
    assert flagged.status == "present_uncontrolled"
    assert flagged.direction_of_bias == "would_flatter_the_intervention"
    assert "the whole of it" in flagged.why
    assert "regression_to_the_mean" in evaluation.unresolved_confounders


def test_reversion_is_measured_against_the_agencys_own_history_not_a_constant() -> None:
    """Change the history level and the diagnostic must move with it."""
    low = evaluate(flat_then_step(history_value=0.72, pre_value=0.70, post_value=0.79))
    high = evaluate(flat_then_step(history_value=0.90, pre_value=0.70, post_value=0.79))

    assert low.regression_to_the_mean.long_run_mean == pytest.approx(0.72, abs=1e-6)
    assert high.regression_to_the_mean.long_run_mean == pytest.approx(0.90, abs=1e-6)
    assert low.regression_to_the_mean.predicted_change_from_reversion == pytest.approx(0.02, abs=1e-6)
    assert high.regression_to_the_mean.predicted_change_from_reversion == pytest.approx(0.20, abs=1e-6)
    assert (
        low.regression_to_the_mean.share_of_observed_change_explained_by_reversion
        < high.regression_to_the_mean.share_of_observed_change_explained_by_reversion
    )


def test_a_normal_pre_window_does_not_manufacture_a_reversion_flag() -> None:
    evaluation = evaluate(flat_then_step(history_value=0.80, pre_value=0.80, post_value=0.86))
    reversion = evaluation.regression_to_the_mean
    assert reversion.assessable is True
    assert reversion.pre_window_was_adverse is False
    flagged = confounder(evaluation, "regression_to_the_mean")
    assert flagged.status == "quantified_not_removed"
    assert flagged.direction_of_bias == "would_penalise_the_intervention"
    assert "regression_to_the_mean" not in evaluation.unresolved_confounders


def test_without_enough_history_reversion_is_unresolved_not_absent() -> None:
    short = flat_then_step(
        history_value=0.80, pre_value=0.70, post_value=0.79,
        history_months=MIN_HISTORY_PERIODS_FOR_REVERSION - 1,
    )
    evaluation = evaluate(short)
    reversion = evaluation.regression_to_the_mean

    assert reversion.assessable is False
    assert reversion.long_run_mean is None
    assert reversion.share_of_observed_change_explained_by_reversion is None
    assert "not possible to say" in (reversion.reason_if_not_assessable or "")
    assert confounder(evaluation, "regression_to_the_mean").status == "cannot_rule_out"
    assert "regression_to_the_mean" in evaluation.unresolved_confounders


def test_no_caller_argument_can_mark_regression_to_the_mean_resolved() -> None:
    """Every other confounder can be answered by supplying data. This one is
    computed from the series, so there must be no keyword that switches it off."""
    treated = flat_then_step(history_value=0.80, pre_value=0.70, post_value=0.79)
    kwargs = dict(
        known_service_changes=(),
        demand_mix=DemandMix(pre={"a": 1.0}, post={"a": 1.0}, source="operator"),
        metric_measured_by="independent_of_intervention",
        procurement_followed_adverse_period=False,
    )
    evaluation = evaluate(treated, **kwargs)
    assert confounder(evaluation, "regression_to_the_mean").status == "present_uncontrolled"
    assert "regression_to_the_mean" in evaluation.unresolved_confounders
    assert evaluation.attribution_verdict != "association_only_confounders_addressed"

    signature = set(iv.evaluate_intervention.__code__.co_varnames)
    for forbidden in ("ignore_reversion", "reversion_ruled_out", "skip_confounders"):
        assert forbidden not in signature


def test_a_declared_procurement_after_a_bad_period_forces_the_flag() -> None:
    """Even where the numbers alone would not flag it, the caller telling us the
    procurement followed a bad period must not be quietly ignored."""
    treated = flat_then_step(history_value=0.80, pre_value=0.80, post_value=0.86)
    without = evaluate(treated)
    with_declaration = evaluate(treated, procurement_followed_adverse_period=True)

    assert confounder(without, "regression_to_the_mean").status == "quantified_not_removed"
    flagged = confounder(with_declaration, "regression_to_the_mean")
    assert flagged.status == "present_uncontrolled"
    assert flagged.direction_of_bias == "would_flatter_the_intervention"
    assert "textbook setup" in flagged.why
    assert with_declaration.regression_to_the_mean.procurement_followed_adverse_period is True


# ---------------------------------------------------------------------------
# Difference-in-differences
# ---------------------------------------------------------------------------


def _did_pair(
    *, sector_shift: float, treated_lift: float, wobble: float = 0.004
) -> tuple[MetricSeries, MetricSeries]:
    treated_points: list[tuple[datetime, float]] = []
    control_points: list[tuple[datetime, float]] = []
    for index, start in enumerate(months(HISTORY_START, 36) + months(PRE_START, 12)):
        treated_points.append((start, 0.75 + wobble * ((index % 3) - 1)))
        control_points.append((start, 0.75 + wobble * ((index % 4) - 1.5)))
    for index, start in enumerate(months(INTERVENTION_AT, 12)):
        treated_points.append((start, 0.75 + sector_shift + treated_lift + wobble * ((index % 3) - 1)))
        control_points.append((start, 0.75 + sector_shift + wobble * ((index % 4) - 1.5)))
    return (
        series(treated_points, exposure=1000.0, fleet_size=50.0),
        series(control_points, label="peer panel", provenance="real_public"),
    )


def test_did_removes_a_sector_wide_shift_the_uncontrolled_arm_would_have_claimed() -> None:
    treated, control = _did_pair(sector_shift=0.05, treated_lift=0.02)
    uncontrolled = evaluate(treated)
    controlled = evaluate(
        treated, reg=registration(design="difference_in_differences"), control=control
    )

    assert uncontrolled.association.estimate == pytest.approx(0.07, abs=1e-3)
    assert controlled.association.estimate == pytest.approx(0.02, abs=1e-3)
    assert controlled.difference_in_differences is not None
    assert controlled.difference_in_differences.control_change == pytest.approx(0.05, abs=1e-3)
    assert controlled.evidence_strength == "stronger_controlled_association"
    assert uncontrolled.evidence_strength == "weak_uncontrolled_association"
    assert (
        confounder(controlled, "secular_trend_and_external_shocks").status
        == "partially_addressed_by_design"
    )
    assert (
        confounder(uncontrolled, "secular_trend_and_external_shocks").status == "cannot_rule_out"
    )


def test_parallel_trends_can_be_contradicted_and_is_never_reported_as_verified() -> None:
    values = set(typing.get_args(iv.ParallelTrendsCheck))
    assert "verified" not in values and "holds" not in values and "satisfied" not in values

    treated, control = _did_pair(sector_shift=0.0, treated_lift=0.02)
    reg = registration(design="difference_in_differences")
    flat = evaluate(treated, reg=reg, control=control)
    assert flat.difference_in_differences.parallel_trends == "not_contradicted_in_pre_period"

    # Now give the treated series a pre-period drift the control does not share.
    drifting_points = []
    for point in treated.points:
        if PRE_WINDOW.contains(point.period_start):
            index = sum(
                1 for p in treated.points
                if PRE_WINDOW.contains(p.period_start) and p.period_start < point.period_start
            )
            drifting_points.append(point.model_copy(update={"value": point.value + 0.01 * index}))
        else:
            drifting_points.append(point)
    drifting = treated.model_copy(update={"points": tuple(drifting_points)})
    diverging = evaluate(drifting, reg=reg, control=control)
    assert diverging.difference_in_differences.parallel_trends == "contradicted_in_pre_period"
    assert diverging.difference_in_differences.pre_period_difference_slope > 0


def test_did_does_not_resolve_regression_to_the_mean() -> None:
    """Ashenfelter's dip: peers did not share the treated agency's bad period, so
    its rebound survives the subtraction and can make the CONTROLLED estimate the
    larger of the two. The strongest verdict must stay out of reach."""
    treated_points: list[tuple[datetime, float]] = []
    control_points: list[tuple[datetime, float]] = []
    for index, start in enumerate(months(HISTORY_START, 36)):
        treated_points.append((start, 0.80 + 0.004 * ((index % 3) - 1)))
        control_points.append((start, 0.80 + 0.004 * ((index % 4) - 1.5)))
    for index, start in enumerate(months(PRE_START, 12)):
        treated_points.append((start, 0.70 + 0.004 * ((index % 3) - 1)))  # the dip
        control_points.append((start, 0.80 + 0.004 * ((index % 4) - 1.5)))
    for index, start in enumerate(months(INTERVENTION_AT, 12)):
        treated_points.append((start, 0.79 + 0.004 * ((index % 3) - 1)))  # the rebound
        control_points.append((start, 0.78 + 0.004 * ((index % 4) - 1.5)))  # peers drift down
    treated = series(treated_points, exposure=1000.0, fleet_size=50.0)
    control = series(control_points, label="peer panel", provenance="real_public")

    evaluation = evaluate(
        treated,
        reg=registration(design="difference_in_differences"),
        control=control,
        known_service_changes=(),
        demand_mix=DemandMix(pre={"a": 1.0}, post={"a": 1.0}, source="operator"),
        metric_measured_by="independent_of_intervention",
    )
    uncontrolled = evaluate(treated)

    assert evaluation.association.estimate > uncontrolled.association.estimate
    assert evaluation.regression_to_the_mean.share_of_observed_change_explained_by_reversion > 1.0
    assert confounder(evaluation, "regression_to_the_mean").status == "present_uncontrolled"
    assert evaluation.unresolved_confounders == ("regression_to_the_mean",)
    assert evaluation.attribution_verdict == "association_only_confounded"
    assert "does NOT remove regression to the mean" in evaluation.difference_in_differences.note


def test_unaligned_control_periods_are_counted_and_dropped_not_interpolated() -> None:
    treated, control = _did_pair(sector_shift=0.0, treated_lift=0.02)
    trimmed = control.model_copy(
        update={
            "points": tuple(
                p for p in control.points if p.period_start not in months(INTERVENTION_AT, 3)
            )
        }
    )
    evaluation = evaluate(
        treated, reg=registration(design="difference_in_differences"), control=trimmed
    )
    did = evaluation.difference_in_differences
    assert did.aligned_period_count == 21  # 12 pre + 9 post
    assert did.treated_periods_without_control == 3
    assert did.control_periods_without_treated == 0


def test_a_control_too_short_to_fit_a_pre_trend_says_so() -> None:
    pre = Window(starts_at=utc(2024, 10), ends_at=INTERVENTION_AT)
    treated, control = _did_pair(sector_shift=0.0, treated_lift=0.02)
    evaluation = evaluate(
        treated,
        reg=registration(design="difference_in_differences", pre_window=pre),
        control=control,
    )
    assert evaluation.pre_window_summary.period_count == 3
    assert evaluation.difference_in_differences.parallel_trends == "insufficient_pre_periods"


# ---------------------------------------------------------------------------
# The refusals -- enforced in types, not in prose
# ---------------------------------------------------------------------------


def test_causal_proof_can_never_be_claimed() -> None:
    evaluation = evaluate(flat_then_step(history_value=0.8, pre_value=0.8, post_value=0.9))
    assert evaluation.causal_proof is False
    body = evaluation.model_dump()
    body["causal_proof"] = True
    with pytest.raises(ValueError, match="never claim causal proof"):
        InterventionEvaluation(**body)


def test_a_randomised_experiment_can_never_be_claimed() -> None:
    evaluation = evaluate(flat_then_step(history_value=0.8, pre_value=0.8, post_value=0.9))
    assert evaluation.is_randomised_experiment is False
    body = evaluation.model_dump()
    body["is_randomised_experiment"] = True
    with pytest.raises(ValueError, match="randomly assigned"):
        InterventionEvaluation(**body)


def test_an_uncontrolled_before_after_cannot_reach_the_strongest_verdict() -> None:
    """The central structural claim: supply everything, get a clean series, and
    the uncontrolled design still cannot be typed into 'confounders addressed'."""
    treated = flat_then_step(history_value=0.80, pre_value=0.80, post_value=0.90)
    evaluation = evaluate(
        treated,
        known_service_changes=(),
        demand_mix=DemandMix(pre={"a": 1.0}, post={"a": 1.0}, source="operator"),
        metric_measured_by="independent_of_intervention",
    )
    # Everything answerable has been answered...
    assert evaluation.unresolved_confounders == ("secular_trend_and_external_shocks",)
    assert evaluation.design == "uncontrolled_pre_post"
    assert evaluation.attribution_verdict == "association_only_confounded"

    # ...and it still cannot be forged into the stronger claim, on either count.
    body = evaluation.model_dump()
    body["attribution_verdict"] = "association_only_confounders_addressed"
    with pytest.raises(ValueError, match="requires a difference_in_differences design"):
        InterventionEvaluation(**body)

    body["evidence_strength"] = "stronger_controlled_association"
    with pytest.raises(ValueError):
        InterventionEvaluation(**body)


def test_the_strongest_verdict_requires_zero_unresolved_confounders() -> None:
    treated, control = _did_pair(sector_shift=0.0, treated_lift=0.05)
    reg = registration(design="difference_in_differences")
    clean = evaluate(
        treated,
        reg=reg,
        control=control,
        known_service_changes=(),
        demand_mix=DemandMix(pre={"a": 1.0}, post={"a": 1.0}, source="operator"),
        metric_measured_by="independent_of_intervention",
    )
    # Reachable -- otherwise the guard below would be vacuous.
    assert clean.unresolved_confounders == ()
    assert clean.attribution_verdict == "association_only_confounders_addressed"

    # One unanswered question is enough to lose it.
    partial = evaluate(treated, reg=reg, control=control, known_service_changes=())
    assert "demand_mix_shift" in partial.unresolved_confounders
    assert partial.attribution_verdict == "association_only_confounded"

    body = partial.model_dump()
    body["attribution_verdict"] = "association_only_confounders_addressed"
    with pytest.raises(ValueError, match="contradicted by unresolved confounders"):
        InterventionEvaluation(**body)


def test_stronger_controlled_evidence_cannot_be_claimed_without_a_control() -> None:
    evaluation = evaluate(flat_then_step(history_value=0.8, pre_value=0.8, post_value=0.9))
    body = evaluation.model_dump()
    body["evidence_strength"] = "stronger_controlled_association"
    with pytest.raises(ValueError, match="requires a control series"):
        InterventionEvaluation(**body)


def test_design_and_the_control_block_cannot_disagree() -> None:
    treated, control = _did_pair(sector_shift=0.0, treated_lift=0.02)
    controlled = evaluate(
        treated, reg=registration(design="difference_in_differences"), control=control
    )
    body = controlled.model_dump()
    body["difference_in_differences"] = None
    body["evidence_strength"] = "weak_uncontrolled_association"  # isolate the design check
    with pytest.raises(ValueError, match="must agree"):
        InterventionEvaluation(**body)

    # ...and the mirror image: a control block under an uncontrolled design.
    uncontrolled = evaluate(treated)
    forged = uncontrolled.model_dump()
    forged["difference_in_differences"] = controlled.difference_in_differences.model_dump()
    with pytest.raises(ValueError, match="must agree"):
        InterventionEvaluation(**forged)


def test_no_vocabulary_in_this_module_contains_a_causal_value() -> None:
    causal_words = ("caus", "proof", "proven", "experiment", "randomis", "randomiz", "conclusive")
    vocabularies = {
        "ComparisonDesign": iv.ComparisonDesign,
        "AttributionVerdict": iv.AttributionVerdict,
        "EvidenceStrength": iv.EvidenceStrength,
        "DirectionVerdict": iv.DirectionVerdict,
        "ConfounderStatus": iv.ConfounderStatus,
        "ParallelTrendsCheck": iv.ParallelTrendsCheck,
    }
    for name, alias in vocabularies.items():
        for value in typing.get_args(alias):
            assert not any(word in value.lower() for word in causal_words), f"{name}.{value}"

    # And every attribution verdict either refuses or says association.
    for value in typing.get_args(iv.AttributionVerdict):
        assert "association" in value or value == "insufficient_to_attribute"


def test_no_monetary_or_saving_field_reaches_the_output() -> None:
    """The teardown may value empty time; an intervention evaluation must not
    produce a saving figure at all (blueprint/01)."""
    banned = ("saving", "payback", "roi", "dollar", "usd", "money", "profit", "avoidable")
    models = (
        InterventionEvaluation,
        AssociationEstimate,
        ReversionDiagnostic,
        ConfounderAssessment,
        iv.DifferenceInDifferences,
        iv.WindowSummary,
        iv.InterventionManifest,
        PreRegistration,
    )
    for model in models:
        for field_name in model.model_fields:
            assert not any(word in field_name.lower() for word in banned), f"{model.__name__}.{field_name}"


def test_the_output_carries_its_own_refusals() -> None:
    evaluation = evaluate(flat_then_step(history_value=0.8, pre_value=0.8, post_value=0.9))
    assert evaluation.refuses_to_claim == REFUSALS
    assert evaluation.interpretation == ASSOCIATION_NOTE
    assert evaluation.manifest.note == ASSOCIATION_NOTE
    joined = " ".join(REFUSALS).lower()
    for expected in ("causal effect", "saving", "experiment", "confounder", "pre-registered"):
        assert expected in joined


def test_the_estimate_cannot_be_quoted_without_its_qualification() -> None:
    """ADR-0049's discipline: there is no renderer that emits the number alone."""
    treated = flat_then_step(history_value=0.80, pre_value=0.70, post_value=0.79)
    line = evaluate(treated).summary()

    assert line.count("\n") == 0
    assert "+0.09" in line
    assert "uncontrolled_pre_post" in line
    assert "association_only_confounded" in line
    assert "regression_to_the_mean" in line
    assert "mean-reversion alone predicts 111% of it" in line
    assert "not a causal estimate" in line

    renderers = [
        name for name in dir(InterventionEvaluation)
        if not name.startswith("_") and callable(getattr(InterventionEvaluation, name, None))
    ]
    assert set(renderers) & {"summary"} == {"summary"}
    for banned in ("headline", "estimate_only", "as_claim", "to_marketing"):
        assert banned not in renderers


# ---------------------------------------------------------------------------
# Manifest and evidence
# ---------------------------------------------------------------------------


def test_the_evaluation_id_is_deterministic_in_the_registration_and_the_data() -> None:
    treated = flat_then_step(history_value=0.8, pre_value=0.8, post_value=0.9)
    a, b = evaluate(treated), evaluate(treated)
    assert a.manifest.evaluation_id == b.manifest.evaluation_id

    nudged = treated.model_copy(
        update={"points": treated.points[:-1] + (
            treated.points[-1].model_copy(update={"value": 0.95}),
        )}
    )
    assert evaluate(nudged).manifest.evaluation_id != a.manifest.evaluation_id


def test_the_manifest_counts_the_data_the_registration_excluded() -> None:
    """A reader must be able to see that more data existed than was used."""
    points = [(start, 0.80) for start in months(HISTORY_START, 36)]
    points += [(start, 0.80) for start in months(PRE_START, 12)]
    points += [(start, 0.90) for start in months(INTERVENTION_AT, 12)]
    points += [(start, 0.99) for start in months(POST_END, 9)]  # the good year that came later
    evaluation = evaluate(series(points))

    assert evaluation.manifest.periods_after_post_window == 9
    assert evaluation.manifest.periods_before_pre_window == 36
    assert evaluation.manifest.washout_period_count == 0
    assert evaluation.post_window_summary.period_count == 12
    excluded = {i.name: i for i in evaluation.manifest.inputs}
    assert excluded["periods_after_post_window_excluded"].value == "9"
    assert "new registration" in excluded["periods_after_post_window_excluded"].source


def test_a_washout_gap_between_the_go_live_and_the_post_window_is_recorded() -> None:
    post = Window(starts_at=utc(2025, 4), ends_at=utc(2026, 4))
    points = [(start, 0.80) for start in months(HISTORY_START, 36)]
    points += [(start, 0.80) for start in months(PRE_START, 12)]
    points += [(start, 0.70) for start in months(INTERVENTION_AT, 3)]  # learning curve
    points += [(start, 0.90) for start in months(utc(2025, 4), 12)]
    evaluation = evaluate(series(points), reg=registration(post_window=post))

    assert evaluation.manifest.washout_period_count == 3
    assert evaluation.post_window_summary.period_count == 12
    assert evaluation.pre_window_summary.period_count == 12


def test_the_manifest_pins_the_registration_and_both_series() -> None:
    treated, control = _did_pair(sector_shift=0.02, treated_lift=0.02)
    reg = registration(design="difference_in_differences")
    evaluation = evaluate(treated, reg=reg, control=control)

    assert evaluation.manifest.registration_sha256 == reg.registration_sha256
    assert evaluation.manifest.registration_timing == "prospective"
    assert evaluation.manifest.treated_series_sha256 == series_fingerprint(treated)
    assert evaluation.manifest.control_series_sha256 == series_fingerprint(control)
    assert evaluation.manifest.replay_version == iv.REPLAY_VERSION
    assert evaluation.manifest.data_provenance == "synthetic"


def test_the_method_names_the_did_step_only_under_a_did_design() -> None:
    treated, control = _did_pair(sector_shift=0.0, treated_lift=0.02)
    uncontrolled = evaluate(treated)
    controlled = evaluate(
        treated, reg=registration(design="difference_in_differences"), control=control
    )
    uncontrolled_steps = " ".join(s.step for s in uncontrolled.manifest.method)
    controlled_steps = " ".join(s.step for s in controlled.manifest.method)

    assert "difference-in-differences" not in uncontrolled_steps
    assert "difference-in-differences" in controlled_steps
    for evaluation in (uncontrolled, controlled):
        joined = " ".join(s.detail for s in evaluation.manifest.method)
        assert "UNWEIGHTED" in joined
        assert "MORE CONSERVATIVE" in joined
        assert "No causal effect is estimated" in joined
        assert evaluation.manifest.method[0].step.startswith("1.")


def test_the_data_provenance_vocabulary_has_no_operator_value() -> None:
    """Reused from the teardown precisely so it cannot be widened here: there is
    no consented operator export in this repo, and nothing may imply one."""
    assert set(typing.get_args(iv.DataProvenance)) == {"real_public", "synthetic"}
    with pytest.raises(ValueError):
        series([(utc(2024, 1), 0.8)], provenance="operator")


def test_exposure_is_reported_as_a_demand_signal_and_never_weights_the_mean() -> None:
    """Weighting would silently change the estimand; the method step says it is
    not done, and this proves the code agrees."""
    base = [(start, 0.80) for start in months(HISTORY_START, 36)]
    base += [(start, 0.80) for start in months(PRE_START, 12)]
    post_stamps = months(INTERVENTION_AT, 12)
    points = [
        SeriesPoint(period_start=s, value=v, exposure=100.0) for s, v in base
    ] + [
        SeriesPoint(
            period_start=s,
            value=0.99 if index == 0 else 0.80,
            # One enormous month that would dominate any weighted mean.
            exposure=100000.0 if index == 0 else 100.0,
        )
        for index, s in enumerate(post_stamps)
    ]
    evaluation = evaluate(
        MetricSeries(label="lumpy", metric_name=OTP.name, provenance="synthetic", points=tuple(points))
    )
    unweighted = (0.99 + 0.80 * 11) / 12
    assert evaluation.post_window_summary.mean == pytest.approx(unweighted)
    assert evaluation.post_window_summary.exposure_total == pytest.approx(100000.0 + 100.0 * 11)
    mix_diagnostics = {d.name for d in confounder(evaluation, "demand_mix_shift").diagnostics}
    assert "exposure_change_ratio" in mix_diagnostics
