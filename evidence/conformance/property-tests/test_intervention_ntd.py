"""The intervention evaluator on the real FTA NTD monthly demand-response panel.

Skips cleanly when the panel is not present, so CI stays green without the
corpus (the ADR-0056 precedent for `test_teardown_scale.py`).

WHAT THESE TESTS ASSERT is a property of the METHOD, not a finding about any
agency: NTD records no scheduling-software intervention, so every cut date here
is a placebo. The most valuable assertion in this file is
`test_a_placebo_cut_can_still_produce_a_significant_controlled_estimate` -- on
real public numbers, at a date where nothing happened, difference-in-differences
returns a larger and more "significant" effect than the uncontrolled arm, purely
because the treated agency was reverting to its own mean while its peers drifted
down. That is the artifact demonstrating its own most important limitation.
"""

from __future__ import annotations

import pytest

from app.replay import MANDATORY_CONFOUNDERS
from app.replay import intervention_demo as demo

pytestmark = pytest.mark.skipif(
    not demo.NTD_MONTHLY_DR_PANEL.exists(),
    reason=(
        f"NTD monthly demand-response panel not present at {demo.NTD_MONTHLY_DR_PANEL}; "
        "run realdata/fetch_ntd_monthly.py to acquire it"
    ),
)


@pytest.fixture(scope="module")
def candidates():
    found = demo.scan_for_reversion_candidates(
        history_start=demo.HISTORY_START,
        pre_start=demo.PRE_START,
        post_start=demo.PLACEBO_INTERVENTION_AT,
        post_end=demo.POST_END,
    )
    if not found:
        pytest.skip("no complete-coverage reporter in this panel vintage satisfies the scan")
    return found


@pytest.fixture(scope="module")
def chosen(candidates):
    return candidates[0]


@pytest.fixture(scope="module")
def uncontrolled(chosen):
    return demo.evaluate_demo_agency(
        ntd_id=chosen.ntd_id, type_of_service=chosen.type_of_service, controlled=False
    )


@pytest.fixture(scope="module")
def controlled(chosen):
    return demo.evaluate_demo_agency(
        ntd_id=chosen.ntd_id, type_of_service=chosen.type_of_service, controlled=True
    )


def test_the_panel_yields_a_real_monthly_series_with_exposure_and_fleet(chosen) -> None:
    series = demo.load_agency_series(
        ntd_id=chosen.ntd_id,
        type_of_service=chosen.type_of_service,
        history_start=demo.HISTORY_START,
        post_end=demo.POST_END,
    )
    assert series.provenance == "real_public"
    assert len(series.points) == 108  # 2008-01 .. 2016-12 inclusive
    assert all(p.value > 0 for p in series.points)
    assert all(p.exposure is not None and p.exposure > 0 for p in series.points)
    assert sum(1 for p in series.points if p.fleet_size is not None) == 108


def test_the_reversion_scan_is_deterministic_and_ordered_by_adversity(candidates) -> None:
    again = demo.scan_for_reversion_candidates(
        history_start=demo.HISTORY_START,
        pre_start=demo.PRE_START,
        post_start=demo.PLACEBO_INTERVENTION_AT,
        post_end=demo.POST_END,
    )
    assert [c.ntd_id for c in again] == [c.ntd_id for c in candidates]
    z_scores = [c.pre_window_z_score for c in candidates]
    assert z_scores == sorted(z_scores)
    assert all(c.observed_change > 0 for c in candidates)
    # The head of the list is the most adverse pre window -- the case where
    # mean-reversion is most likely to be the whole story, which is the one the
    # demonstration deliberately picks.
    assert candidates[0].pre_window_z_score < 0
    assert candidates[0].pre_window_z_score <= min(c.pre_window_z_score for c in candidates)
    # Reporters with a normal or good pre window are kept, not filtered away.
    assert any(c.pre_window_z_score >= 0 for c in candidates)


def test_the_uncontrolled_arm_reports_the_real_reversion_diagnostic(uncontrolled, chosen) -> None:
    reversion = uncontrolled.regression_to_the_mean
    assert reversion.assessable is True
    assert reversion.history_period_count == 72  # 2008-01 .. 2013-12
    assert reversion.pre_window_was_adverse is True
    assert reversion.long_run_mean == pytest.approx(chosen.long_run_mean, rel=1e-6)
    assert reversion.share_of_observed_change_explained_by_reversion == pytest.approx(
        chosen.share_explained_by_reversion, rel=1e-6
    )
    assert reversion.share_of_observed_change_explained_by_reversion > 1.0
    assert uncontrolled.regression_to_the_mean.residual_change_beyond_reversion < 0

    flagged = [c for c in uncontrolled.confounders if c.name == "regression_to_the_mean"][0]
    assert flagged.status == "present_uncontrolled"
    assert flagged.direction_of_bias == "would_flatter_the_intervention"


def test_a_placebo_cut_can_still_produce_a_significant_controlled_estimate(
    uncontrolled, controlled
) -> None:
    """The limitation that matters, demonstrated on real public data.

    Nothing happened to this agency in January 2016. The uncontrolled arm
    correctly declines to call the movement. Adding a peer control panel -- the
    STRONGER design -- produces a larger estimate that clears the corrected
    alpha, because the treated agency was climbing back to its own long-run mean
    while its peers drifted down. The evaluator must still refuse to attribute
    it, and the refusal has to come from the regression-to-the-mean confounder,
    not from the p-value.
    """
    assert uncontrolled.design == "uncontrolled_pre_post"
    assert controlled.design == "difference_in_differences"

    assert controlled.association.estimate > uncontrolled.association.estimate
    assert controlled.association.p_value < uncontrolled.association.p_value
    assert controlled.difference_in_differences.control_change < 0
    assert controlled.evidence_strength == "stronger_controlled_association"

    # ...and the strongest verdict is still out of reach, because of reversion.
    assert "regression_to_the_mean" in controlled.unresolved_confounders
    assert controlled.attribution_verdict == "association_only_confounded"
    assert controlled.causal_proof is False


def test_the_autocorrelation_discount_is_load_bearing_on_the_real_series(uncontrolled) -> None:
    """Real monthly operational series are autocorrelated; the naive p-value
    would be the optimistic one, and the module must not use it."""
    association = uncontrolled.association
    assert association.lag1_autocorrelation is not None
    assert association.lag1_autocorrelation > 0
    assert association.p_value_autocorrelation_adjusted > association.p_value_iid
    assert association.p_value == association.p_value_autocorrelation_adjusted
    assert association.effective_pre_periods < uncontrolled.pre_window_summary.period_count


def test_both_arms_name_every_mandatory_confounder(uncontrolled, controlled) -> None:
    for evaluation in (uncontrolled, controlled):
        assert tuple(c.name for c in evaluation.confounders) == MANDATORY_CONFOUNDERS
        # Real filings answer fleet size and calendar alignment; nothing in this
        # public panel answers concurrent service changes or demand mix.
        by_name = {c.name: c.status for c in evaluation.confounders}
        assert by_name["fleet_change"] == "quantified_not_removed"
        assert by_name["seasonality"] == "partially_addressed_by_design"
        assert by_name["concurrent_service_change"] == "cannot_rule_out"
        assert by_name["demand_mix_shift"] == "cannot_rule_out"


def test_the_control_panel_follows_the_registered_peer_rule(chosen, controlled) -> None:
    control, peer_count = demo.load_peer_control_series(
        treated_ntd_id=chosen.ntd_id,
        type_of_service=chosen.type_of_service,
        history_start=demo.HISTORY_START,
        post_end=demo.POST_END,
    )
    assert peer_count >= 5
    assert control.provenance == "real_public"
    assert len(control.points) == 108
    assert str(peer_count) in controlled.pre_registration.control_plan
    assert "not randomly assigned" in controlled.pre_registration.control_plan
    assert controlled.difference_in_differences.control_label == control.label


def test_the_registration_is_prospective_and_pinned_to_the_panel_vintage(
    uncontrolled, controlled
) -> None:
    digest = demo.panel_sha256()
    for evaluation in (uncontrolled, controlled):
        assert evaluation.manifest.registration_timing == "prospective"
        assert evaluation.manifest.data_provenance == "real_public"
        assert digest[:16] in evaluation.manifest.dataset_label
        assert "PLACEBO" in evaluation.pre_registration.intervention_label
    # The two arms are different registrations and must not share an id.
    assert (
        uncontrolled.manifest.registration_sha256 != controlled.manifest.registration_sha256
    )
    assert uncontrolled.manifest.evaluation_id != controlled.manifest.evaluation_id


def test_the_summary_line_of_the_real_run_carries_its_own_refutation(uncontrolled) -> None:
    line = uncontrolled.summary()
    assert "not a causal estimate" in line
    assert "mean-reversion alone predicts" in line
    assert "regression_to_the_mean" in line
