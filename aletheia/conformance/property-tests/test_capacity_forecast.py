"""Program E conformance: the capacity DECISION the forecast has to serve.

Packet MX-E-CAPACITY-FORECAST-010. The properties asserted here are the four
the packet names, plus the finite-sample failure the fourth uncovered:

1. THE QUANTITY IS THE ONE A PLANNER COMMITS AGAINST. Vehicle-revenue-hours and
   vehicles-in-service, derived from a demand forecast through a MEASURED
   productivity basis -- never a constant.

2. COST ASYMMETRY IS STATED, NEVER DEFAULTED. Asserted structurally, by
   signature inspection and by construction failure, not by reading the code:
   `CostAsymmetry` has no field defaults and `recommend_capacity` has no default
   for `cost`, so a later "convenience" default fails this suite rather than
   silently setting an operator's service policy. The newsvendor optimality of
   the critical ratio is proved by EXHAUSTIVE SEARCH over a plan grid -- and the
   same search shows the squared-error-optimal mean plan is NOT cost-optimal,
   which is the whole argument for the packet.

3. THE INTERVAL GUARANTEE IS INHERITED, STRUCTURALLY (the packet's central
   requirement). Every drift verdict here is produced by the real
   `assess_drift`, never hand-constructed, so the propagation is exercised
   end-to-end. A recommendation whose guarantee is not `unqualified` CANNOT be
   constructed carrying an evidenced service level and CANNOT be constructed
   without a caveat -- both directions raise `ValidationError`. And the hours
   figure is asserted IDENTICAL under drift and no-drift: the withdrawal removes
   the coverage claim, never the number (report, do not decide -- ADR-0034,
   ADR-0049).

4. A SECOND, INDEPENDENT WITHDRAWAL REASON. `n` calibration residuals cannot
   express a one-sided level above `n/(n+1)`. On monthly agency data that is the
   common case, and it suppresses the claim on its own, with its own reason.

REAL vs SYNTHETIC is labelled per section. The synthetic sections use seeded
draws sized ABOVE the PSI stability threshold measured in
`aletheia/benchmarks/quality/capacity_backtest.py` -- deliberately, so a drift assertion
here is about drift and not about a statistic misbehaving at small n. The real
section reads the committed, governed NTD demand-response panel.

Status: Demonstrated. Never operator-Validated -- see
`metis.forecast.capacity.CENSORED_DEMAND_LIMITATION`.
"""

from __future__ import annotations

import inspect
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from themis.canonical import ModelVersionId, TenantId, new_id
from themis.canonical.entities import ForecastVintage
from metis.forecast.capacity import (
    CENSORED_DEMAND_LIMITATION,
    MARGINAL_COVERAGE_LIMITATION,
    PRODUCTIVITY_POINT_ESTIMATE_LIMITATION,
    CapacityRecommendation,
    CostAsymmetry,
    ProductivityBasis,
    asymmetric_capacity_cost,
    empirical_service_level,
    expected_asymmetric_cost,
    recommend_capacity,
)
from metis.forecast.conformal import (
    ConformalQuantile,
    empirical_one_sided_coverage,
    fit_one_sided_conformal,
    fit_symmetric_conformal,
)
from metis.forecast.serve_drift import (
    MonitoredForecast,
    assess_drift,
    derive_reference_from_rows,
)

_REPO = Path(__file__).resolve().parents[3]
_NTD_PANEL = _REPO / "data" / "curated" / "panels" / "ntd_monthly_dr.csv.gz"

# Sized above the measured PSI-stability threshold on purpose (see
# aletheia/benchmarks/quality/capacity_backtest.py): at n=30 the PSI significant band
# fires on ~96% of pure noise, so a "no_drift" assertion at that size would be
# untestable and a "drift" assertion would be meaningless.
_N_ROWS = 600
_FEATURES = ("demand_lag", "temp_c")


def _rows(seed: int, *, shift: float = 0.0, n: int = _N_ROWS) -> list[dict]:
    rng = np.random.default_rng(seed)
    return [
        {
            "demand_lag": float(rng.normal(100.0 + shift, 12.0)),
            "temp_c": float(rng.normal(15.0 + shift / 10.0, 4.0)),
        }
        for _ in range(n)
    ]


def _reference(seed: int = 0):
    return derive_reference_from_rows(
        _rows(seed),
        _FEATURES,
        source_kind="synthetic",
        description="seeded synthetic reference (labelled synthetic on purpose)",
        derivation="numpy default_rng normal draws",
        max_sample=None,
    )


def _verdict(kind: str):
    """A REAL DriftVerdict from the real `assess_drift`. Hand-building a verdict
    would let these tests pass against a propagation path that never runs."""
    reference = _reference(0)
    if kind == "no_drift":
        return assess_drift(reference, _rows(1))
    if kind == "drift":
        return assess_drift(reference, _rows(2, shift=45.0))
    if kind == "insufficient_data":
        return assess_drift(reference, _rows(3, n=5))
    raise AssertionError(kind)


def _monitored(verdict, point: float = 4200.0) -> MonitoredForecast:
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    return MonitoredForecast(
        vintage=ForecastVintage(
            tenant_id=new_id(TenantId),
            model_version_id=new_id(ModelVersionId),
            horizon_start=now,
            horizon_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
            issued_at=now,
            point_estimate=point,
        ),
        drift=verdict,
    )


def _productivity(trips_per_hour: float = 2.0) -> ProductivityBasis:
    return ProductivityBasis(
        trips_per_vehicle_hour=trips_per_hour,
        source="synthetic fixture",
        derivation="fixed for the test",
        n_observations=48,
    )


def _cost(unserved: float = 75.0, idle: float = 60.0) -> CostAsymmetry:
    return CostAsymmetry(
        cost_per_unserved_trip=unserved,
        cost_per_idle_vehicle_hour=idle,
        stated_by="test fixture",
        basis="illustrative; not an operator statement",
    )


def _quantile_at(level: float, *, seed: int = 5, n: int = 400) -> ConformalQuantile:
    rng = np.random.default_rng(seed)
    return fit_one_sided_conformal(rng.normal(0.0, 300.0, size=n), target_level=level)


# =========================================================================== #
# 1. COST ASYMMETRY IS STATED, NEVER DEFAULTED  (SYNTHETIC / structural)
# =========================================================================== #
def test_cost_asymmetry_cannot_be_constructed_without_stating_anything():
    """The packet's requirement 2, at its bluntest: there is no zero-argument
    cost structure. A default here would silently set service policy."""
    with pytest.raises(ValidationError):
        CostAsymmetry()


@pytest.mark.parametrize(
    "omit",
    ["cost_per_unserved_trip", "cost_per_idle_vehicle_hour", "stated_by", "basis"],
)
def test_every_cost_field_is_required_including_the_attribution(omit: str):
    """Attribution is not decoration. An unattributed cost ratio is
    indistinguishable from an invented one -- the same argument ADR-0049 made
    for an unattributed drift reference."""
    kwargs = {
        "cost_per_unserved_trip": 75.0,
        "cost_per_idle_vehicle_hour": 60.0,
        "stated_by": "someone",
        "basis": "somehow",
    }
    kwargs.pop(omit)
    with pytest.raises(ValidationError):
        CostAsymmetry(**kwargs)


@pytest.mark.parametrize("field", ["cost", "productivity", "demand_quantile"])
def test_recommend_capacity_has_no_default_for_the_policy_inputs(field: str):
    """Guards the future, not the present. This fails the moment someone adds a
    convenience default -- which is exactly how a hidden policy default gets
    introduced, one helpful commit at a time."""
    parameter = inspect.signature(recommend_capacity).parameters[field]
    assert parameter.default is inspect.Parameter.empty, (
        f"{field} acquired a default value; a defaulted cost structure, productivity basis "
        f"or demand quantile decides an operator's service policy on their behalf"
    )
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_symmetric_cost_is_available_but_must_still_be_signed_for():
    """Choosing symmetry must be a recorded decision, not the consequence of not
    choosing. `symmetric()` exists and still demands attribution."""
    with pytest.raises(TypeError):
        CostAsymmetry.symmetric(cost_per_unit=10.0)  # type: ignore[call-arg]
    cost = CostAsymmetry.symmetric(
        cost_per_unit=10.0, stated_by="test", basis="deliberate symmetry"
    )
    assert cost.is_symmetric
    assert math.isclose(cost.critical_ratio(_productivity(1.0)), 0.5)


def test_cost_structure_is_frozen_and_rejects_unknown_fields():
    cost = _cost()
    with pytest.raises(ValidationError):
        cost.cost_per_unserved_trip = 1.0
    with pytest.raises(ValidationError):
        CostAsymmetry(
            cost_per_unserved_trip=1.0,
            cost_per_idle_vehicle_hour=1.0,
            stated_by="x",
            basis="y",
            sneaky_default=True,
        )


# =========================================================================== #
# 2. THE NEWSVENDOR ARGUMENT  (SYNTHETIC / proved by exhaustive search)
# =========================================================================== #
def test_critical_ratio_needs_productivity_because_the_units_differ():
    """$/trip and $/vehicle-hour are not the same unit. Doubling productivity
    halves the cost of a trip-equivalent of idle capacity, which RAISES the
    critical ratio. A ratio formed from the raw stated numbers would be a units
    error, and this pins that it is not being made."""
    cost = _cost(unserved=75.0, idle=60.0)
    low = cost.critical_ratio(_productivity(1.0))
    high = cost.critical_ratio(_productivity(2.0))
    assert math.isclose(low, 75.0 / (75.0 + 60.0))
    assert math.isclose(high, 75.0 / (75.0 + 30.0))
    assert high > low


def test_critical_ratio_rises_with_the_cost_of_denying_a_trip():
    productivity = _productivity(2.0)
    ratios = [
        _cost(unserved=u, idle=60.0).critical_ratio(productivity)
        for u in (10.0, 50.0, 100.0, 500.0)
    ]
    assert ratios == sorted(ratios)
    assert all(0.0 < r < 1.0 for r in ratios)


def test_the_critical_ratio_quantile_minimises_expected_asymmetric_cost():
    """The packet's requirement 2, proved rather than asserted.

    Exhaustive search over a fine grid of candidate plans against an empirical
    demand distribution: the plan at the critical-ratio quantile is within one
    grid step of the cost-minimising plan. This is the classical newsvendor
    result, and it is what licenses provisioning to `Cu/(Cu+Co)` instead of to
    the mean.
    """
    rng = np.random.default_rng(11)
    demand = rng.gamma(shape=9.0, scale=120.0, size=4000)
    productivity = _productivity(2.0)
    cost = _cost(unserved=75.0, idle=60.0)
    q_star = cost.critical_ratio(productivity)

    optimal_demand = float(np.quantile(demand, q_star))
    optimal_plan = productivity.vehicle_hours_for(optimal_demand)

    grid = np.linspace(optimal_plan * 0.5, optimal_plan * 1.5, 201)
    costs = [
        expected_asymmetric_cost(
            plan_vehicle_hours=float(p),
            demand_scenarios=demand,
            cost=cost,
            productivity=productivity,
        )
        for p in grid
    ]
    best = float(grid[int(np.argmin(costs))])
    step = float(grid[1] - grid[0])
    assert abs(best - optimal_plan) <= 2 * step, (
        f"critical-ratio plan {optimal_plan:.2f} is not the grid minimum {best:.2f}; "
        f"the newsvendor derivation is wrong"
    )


def test_the_squared_error_optimal_plan_is_strictly_worse_under_asymmetry():
    """The other half of the argument, and the reason a mean-optimal model is
    the wrong tool: provisioning to the MEAN (what squared error targets) costs
    strictly more than provisioning to the critical ratio whenever the costs are
    asymmetric."""
    rng = np.random.default_rng(12)
    demand = rng.gamma(shape=9.0, scale=120.0, size=4000)
    productivity = _productivity(2.0)
    cost = _cost(unserved=75.0, idle=60.0)

    mean_plan = productivity.vehicle_hours_for(float(np.mean(demand)))
    q_plan = productivity.vehicle_hours_for(
        float(np.quantile(demand, cost.critical_ratio(productivity)))
    )
    mean_cost = expected_asymmetric_cost(
        plan_vehicle_hours=mean_plan,
        demand_scenarios=demand,
        cost=cost,
        productivity=productivity,
    )
    q_cost = expected_asymmetric_cost(
        plan_vehicle_hours=q_plan,
        demand_scenarios=demand,
        cost=cost,
        productivity=productivity,
    )
    assert q_cost < mean_cost
    assert (mean_cost - q_cost) / mean_cost > 0.01, (
        "the asymmetry must make a material difference, otherwise this whole packet is "
        "decoration"
    )


def test_under_symmetric_costs_the_mean_plan_is_not_beaten_by_a_tail_quantile():
    """The control on the previous test. If a high quantile also won under
    SYMMETRIC costs, the gain would be an artefact of the loss function's shape
    rather than of the asymmetry."""
    rng = np.random.default_rng(13)
    demand = rng.gamma(shape=9.0, scale=120.0, size=4000)
    productivity = _productivity(1.0)
    cost = CostAsymmetry.symmetric(cost_per_unit=60.0, stated_by="test", basis="control")
    assert math.isclose(cost.critical_ratio(productivity), 0.5)

    median_plan = productivity.vehicle_hours_for(float(np.median(demand)))
    tail_plan = productivity.vehicle_hours_for(float(np.quantile(demand, 0.9)))
    kwargs = {"demand_scenarios": demand, "cost": cost, "productivity": productivity}
    assert expected_asymmetric_cost(plan_vehicle_hours=median_plan, **kwargs) < (
        expected_asymmetric_cost(plan_vehicle_hours=tail_plan, **kwargs)
    )


def test_implied_cost_ratio_inverts_the_critical_ratio():
    """The number to show a planner who names a service level out of habit: 95%
    is cost-optimal only at a 19:1 cost ratio."""
    assert math.isclose(CostAsymmetry.implied_cost_ratio_for(0.95), 19.0, rel_tol=1e-9)
    assert math.isclose(CostAsymmetry.implied_cost_ratio_for(0.5), 1.0, rel_tol=1e-9)
    for level in (0.6, 0.75, 0.9, 0.99):
        ratio = CostAsymmetry.implied_cost_ratio_for(level)
        cost = _cost(unserved=ratio, idle=1.0)
        assert math.isclose(cost.critical_ratio(_productivity(1.0)), level, rel_tol=1e-9)


def test_asymmetric_cost_prices_the_two_directions_differently():
    productivity = _productivity(2.0)
    cost = _cost(unserved=75.0, idle=60.0)
    # 10 vehicle-hours short == 20 unserved trips == 20 * 75
    short = asymmetric_capacity_cost(
        plan_vehicle_hours=90.0, realised_demand_trips=200.0, cost=cost, productivity=productivity
    )
    # 10 vehicle-hours surplus == 10 * 60
    over = asymmetric_capacity_cost(
        plan_vehicle_hours=110.0, realised_demand_trips=200.0, cost=cost, productivity=productivity
    )
    assert math.isclose(short, 20.0 * 75.0)
    assert math.isclose(over, 10.0 * 60.0)
    assert short != over, "a symmetric objective would make these equal -- that is the bug"
    assert math.isclose(
        asymmetric_capacity_cost(
            plan_vehicle_hours=100.0,
            realised_demand_trips=200.0,
            cost=cost,
            productivity=productivity,
        ),
        0.0,
    )


# =========================================================================== #
# 3. THE GUARANTEE IS INHERITED, STRUCTURALLY  (SYNTHETIC / the central claim)
# =========================================================================== #
def test_drift_fixtures_produce_the_three_distinct_statuses():
    """Non-vacuity guard for every parametrised test below. If all three
    fixtures collapsed to one status, the propagation tests would be asserting
    the same case three times and proving nothing."""
    statuses = {kind: _verdict(kind).status for kind in ("no_drift", "drift", "insufficient_data")}
    assert statuses == {
        "no_drift": "no_drift",
        "drift": "drift",
        "insufficient_data": "insufficient_data",
    }
    guarantees = {
        kind: _verdict(kind).interval_guarantee
        for kind in ("no_drift", "drift", "insufficient_data")
    }
    assert guarantees == {
        "no_drift": "unqualified",
        "drift": "unsupported",
        "insufficient_data": "not_assessed",
    }


@pytest.mark.parametrize(
    ("kind", "expected_guarantee", "claimable"),
    [
        ("no_drift", "unqualified", True),
        ("drift", "unsupported", False),
        ("insufficient_data", "not_assessed", False),
    ],
)
def test_recommendation_inherits_the_interval_guarantee(
    kind: str, expected_guarantee: str, claimable: bool
):
    """THE PACKET'S CENTRAL REQUIREMENT. The guarantee status of the interval
    travels onto the capacity recommendation derived from it, and it decides
    whether a service level may be claimed at all."""
    verdict = _verdict(kind)
    cost, productivity = _cost(), _productivity()
    level = cost.critical_ratio(productivity)
    rec = recommend_capacity(
        _monitored(verdict),
        cost=cost,
        productivity=productivity,
        demand_quantile=_quantile_at(level),
    )
    assert rec.interval_guarantee == expected_guarantee
    assert rec.drift_status == verdict.status
    assert rec.service_level_is_evidenced is claimable
    if claimable:
        assert rec.evidenced_service_level == pytest.approx(level)
        assert rec.guarantee_caveat is None
    else:
        assert rec.evidenced_service_level is None
        assert rec.guarantee_caveat, "a withdrawn guarantee must be explained on the object"
        assert verdict.interval_caveat is not None
        assert verdict.interval_caveat in rec.guarantee_caveat, (
            "the recommendation must CARRY the drift verdict's own caveat, not paraphrase it"
        )


def test_the_hours_figure_is_identical_under_drift_and_no_drift():
    """Report, do not decide (ADR-0034 / ADR-0049). What the withdrawal removes
    is the coverage CLAIM, never the number -- a monitor that silently changed
    the recommended capacity would be worse than one that warns, because the
    planner could no longer tell what the model actually said."""
    cost, productivity = _cost(), _productivity()
    level = cost.critical_ratio(productivity)
    quantile = _quantile_at(level)
    recs = {
        kind: recommend_capacity(
            _monitored(_verdict(kind)),
            cost=cost,
            productivity=productivity,
            demand_quantile=quantile,
        )
        for kind in ("no_drift", "drift", "insufficient_data")
    }
    hours = {k: r.required_vehicle_hours for k, r in recs.items()}
    assert len(set(hours.values())) == 1, f"the monitor changed the recommendation: {hours}"
    assert len({r.demand_at_service_level for r in recs.values()}) == 1
    assert all(r.required_vehicle_hours > 0 for r in recs.values())


@pytest.mark.parametrize("guarantee", ["unsupported", "not_assessed"])
def test_a_withdrawn_guarantee_cannot_carry_an_evidenced_service_level(guarantee: str):
    """Structural, not documentary: the object refuses to exist."""
    with pytest.raises(ValidationError, match="cannot claim coverage"):
        CapacityRecommendation(
            required_vehicle_hours=61.0,
            demand_point_estimate=4200.0,
            demand_at_service_level=4400.0,
            service_level=0.71,
            cost_optimal_service_level=0.71,
            service_level_source="cost_implied",
            implied_cost_ratio=2.45,
            interval_guarantee=guarantee,
            drift_status="drift",
            guarantee_caveat="stated",
            evidenced_service_level=0.71,
            sample_supports_level=True,
            n_calibration_residuals=400,
            max_expressible_level=400 / 401,
            cost=_cost(),
            productivity=_productivity(),
        )


@pytest.mark.parametrize("caveat", [None, ""])
def test_a_withdrawn_guarantee_cannot_omit_the_explanation(caveat):
    with pytest.raises(ValidationError, match="guarantee_caveat is required"):
        CapacityRecommendation(
            required_vehicle_hours=61.0,
            demand_point_estimate=4200.0,
            demand_at_service_level=4400.0,
            service_level=0.71,
            cost_optimal_service_level=0.71,
            service_level_source="cost_implied",
            implied_cost_ratio=2.45,
            interval_guarantee="unsupported",
            drift_status="drift",
            guarantee_caveat=caveat,
            evidenced_service_level=None,
            sample_supports_level=True,
            n_calibration_residuals=400,
            max_expressible_level=400 / 401,
            cost=_cost(),
            productivity=_productivity(),
        )


def test_an_unqualified_guarantee_must_actually_assert_its_level():
    """The other direction, and the reason the validator is not one-sided:
    blanking every field is not the same as being honest. A supported
    recommendation that declines to state its level would pass a one-sided check
    while telling the planner nothing."""
    with pytest.raises(ValidationError, match="must assert its"):
        CapacityRecommendation(
            required_vehicle_hours=61.0,
            demand_point_estimate=4200.0,
            demand_at_service_level=4400.0,
            service_level=0.71,
            cost_optimal_service_level=0.71,
            service_level_source="cost_implied",
            implied_cost_ratio=2.45,
            interval_guarantee="unqualified",
            drift_status="no_drift",
            guarantee_caveat=None,
            evidenced_service_level=None,
            sample_supports_level=True,
            n_calibration_residuals=400,
            max_expressible_level=400 / 401,
            cost=_cost(),
            productivity=_productivity(),
        )


def test_summary_renders_the_number_and_its_status_inseparably():
    """The same discipline as `MonitoredForecast.summary()`: a caller cannot
    quote the hours without the qualification travelling with them."""
    cost, productivity = _cost(), _productivity()
    level = cost.critical_ratio(productivity)
    drifted = recommend_capacity(
        _monitored(_verdict("drift")),
        cost=cost,
        productivity=productivity,
        demand_quantile=_quantile_at(level),
    )
    line = drifted.summary()
    assert f"{drifted.required_vehicle_hours:.1f}" in line
    assert "NOT SUPPORTED" in line
    assert "SERVICE LEVEL NOT EVIDENCED" in line
    assert cost.stated_by in line

    clean = recommend_capacity(
        _monitored(_verdict("no_drift")),
        cost=cost,
        productivity=productivity,
        demand_quantile=_quantile_at(level),
    )
    clean_line = clean.summary()
    assert "EVIDENCED" in clean_line
    assert "NOT EVIDENCED" not in clean_line
    assert "marginal" in clean_line, (
        "even an evidenced level must say it is marginal, not a per-period probability"
    )


def test_recommendation_always_carries_the_standing_limitations():
    cost, productivity = _cost(), _productivity()
    rec = recommend_capacity(
        _monitored(_verdict("no_drift")),
        cost=cost,
        productivity=productivity,
        demand_quantile=_quantile_at(cost.critical_ratio(productivity)),
    )
    for limitation in (
        CENSORED_DEMAND_LIMITATION,
        PRODUCTIVITY_POINT_ESTIMATE_LIMITATION,
        MARGINAL_COVERAGE_LIMITATION,
    ):
        assert limitation in rec.limitations
    assert any("not traceable" in item for item in rec.limitations), (
        "an untraceable productivity basis must be flagged, as ADR-0049 flags an untraceable "
        "drift reference"
    )


# =========================================================================== #
# 4. THE FINITE-SAMPLE CEILING  (SYNTHETIC / the second withdrawal reason)
# =========================================================================== #
@pytest.mark.parametrize(("n", "level", "supported"), [(12, 0.95, False), (400, 0.95, True)])
def test_a_level_above_n_over_n_plus_one_is_not_expressible(n: int, level: float, supported: bool):
    rng = np.random.default_rng(21)
    quantile = fit_one_sided_conformal(rng.normal(0, 100, size=n), target_level=level)
    assert quantile.max_expressible_level == pytest.approx(n / (n + 1))
    assert quantile.level_supported_by_sample is supported
    assert (quantile.sample_shortfall_reason is None) is supported


def test_an_inexpressible_level_withdraws_the_claim_even_with_no_drift():
    """Independent of drift, and not fixed by monitoring. Twelve monthly
    residuals cannot support a 95% service level however clean the data is."""
    cost, productivity = _cost(), _productivity()
    rng = np.random.default_rng(22)
    quantile = fit_one_sided_conformal(rng.normal(0, 300, size=12), target_level=0.95)
    rec = recommend_capacity(
        _monitored(_verdict("no_drift")),
        cost=cost,
        productivity=productivity,
        demand_quantile=quantile,
        service_level=0.95,
    )
    assert rec.interval_guarantee == "unqualified"
    assert rec.drift_status == "no_drift"
    assert rec.sample_supports_level is False
    assert rec.evidenced_service_level is None
    assert "CALIBRATION SAMPLE CANNOT EXPRESS THIS LEVEL" in rec.guarantee_caveat
    assert rec.required_vehicle_hours > 0, "the number survives; only the claim is withdrawn"


def test_both_withdrawal_reasons_are_reported_when_both_apply():
    """Collapsing them would tell a planner to wait for the drift to pass when
    the real problem is that they have twelve months of history."""
    cost, productivity = _cost(), _productivity()
    rng = np.random.default_rng(23)
    quantile = fit_one_sided_conformal(rng.normal(0, 300, size=12), target_level=0.95)
    rec = recommend_capacity(
        _monitored(_verdict("drift")),
        cost=cost,
        productivity=productivity,
        demand_quantile=quantile,
        service_level=0.95,
    )
    assert "CALIBRATION SAMPLE CANNOT EXPRESS THIS LEVEL" in rec.guarantee_caveat
    assert "INTERVAL COVERAGE GUARANTEE NOT SUPPORTED" in rec.guarantee_caveat


def test_sample_support_flag_cannot_contradict_the_levels():
    with pytest.raises(ValidationError, match="contradicts"):
        CapacityRecommendation(
            required_vehicle_hours=61.0,
            demand_point_estimate=4200.0,
            demand_at_service_level=4400.0,
            service_level=0.95,
            cost_optimal_service_level=0.71,
            service_level_source="stated_policy",
            implied_cost_ratio=19.0,
            interval_guarantee="unqualified",
            drift_status="no_drift",
            guarantee_caveat=None,
            evidenced_service_level=0.95,
            sample_supports_level=True,  # lie: 0.95 > 12/13
            n_calibration_residuals=12,
            max_expressible_level=12 / 13,
            cost=_cost(),
            productivity=_productivity(),
        )


# =========================================================================== #
# 5. THE ONE-SIDED CONFORMAL QUANTILE  (SYNTHETIC)
# =========================================================================== #
def test_one_sided_conformal_achieves_its_level_on_exchangeable_data():
    """Marginal validity under exchangeability -- the property the whole
    capacity claim rests on, measured rather than assumed."""
    rng = np.random.default_rng(31)
    residuals = rng.standard_t(df=5, size=2000) * 50.0
    for level in (0.6, 0.8, 0.9):
        quantile = fit_one_sided_conformal(residuals[:1000], target_level=level)
        holdout = residuals[1000:]
        achieved = empirical_one_sided_coverage(
            quantile,
            y_true=1000.0 + holdout,
            y_pred=np.full(holdout.shape, 1000.0),
            clip_nonnegative=False,
        )
        assert achieved >= level - 0.04, f"level {level}: achieved only {achieved}"
        assert achieved <= level + 0.06, f"level {level}: achieved {achieved}, badly overcovered"


def test_one_sided_and_symmetric_answer_different_questions():
    """Using the upper bound of a two-sided interval as a one-sided quantile is
    a real and easy mistake, and an expensive one: the symmetric construction
    pays for a left tail a capacity decision does not care about.

    On centred residuals the gap is exactly the standard-normal one: the
    one-sided 90% quantile is ~1.28 sigma while the symmetric 90% interval's
    upper offset is the 90th percentile of |r|, ~1.645 sigma. Provisioning to
    the latter over-provisions by ~28%.

    The second half is the honest qualification: on a strongly RIGHT-skewed
    residual distribution the two order statistics can coincide, because the
    magnitude ranking and the signed ranking agree once the right tail
    dominates. The two constructions are not universally different -- they
    answer different questions, which is a stronger and narrower claim.
    """
    rng = np.random.default_rng(32)
    sigma = 100.0
    centred = rng.normal(0.0, sigma, size=20000)
    one_sided = fit_one_sided_conformal(centred, target_level=0.9)
    symmetric = fit_symmetric_conformal(centred, target_coverage=0.9)
    assert one_sided.offset == pytest.approx(1.2816 * sigma, rel=0.05)
    assert symmetric.upper_offset == pytest.approx(1.6449 * sigma, rel=0.05)
    assert symmetric.upper_offset > one_sided.offset * 1.2, (
        "the symmetric interval must pay for the left tail a one-sided capacity decision "
        "does not need, and here that is a ~28% over-provision"
    )

    right_skewed = rng.gamma(shape=1.5, scale=80.0, size=3000) - 60.0
    assert fit_one_sided_conformal(right_skewed, target_level=0.9).offset == pytest.approx(
        fit_symmetric_conformal(right_skewed, target_coverage=0.9).upper_offset
    ), "expected coincidence when the right tail dominates the magnitude ranking"


def test_one_sided_offset_is_monotone_in_the_requested_level():
    rng = np.random.default_rng(33)
    residuals = rng.normal(0, 100, size=1000)
    offsets = [fit_one_sided_conformal(residuals, target_level=q).offset for q in (0.5, 0.7, 0.9, 0.99)]
    assert offsets == sorted(offsets)


@pytest.mark.parametrize("level", [0.0, 1.0, -0.1, 1.5])
def test_one_sided_conformal_rejects_impossible_levels(level: float):
    with pytest.raises(ValueError):
        fit_one_sided_conformal([1.0, 2.0, 3.0], target_level=level)


def test_conformal_quantile_clips_a_negative_bound_at_zero():
    quantile = fit_one_sided_conformal([-500.0] * 50, target_level=0.5)
    assert quantile.apply(100.0) == 0.0
    assert quantile.apply(100.0, clip_nonnegative=False) < 0.0


# =========================================================================== #
# 6. THE COMMITTED QUANTITY AND ITS EXCHANGE RATE  (SYNTHETIC)
# =========================================================================== #
def test_service_level_defaults_to_the_cost_implied_ratio_not_to_a_number():
    """Omitting `service_level` DERIVES it from the stated costs; it does not
    fall back to a constant. The policy input is still the costs, which the
    caller had to state."""
    cost, productivity = _cost(unserved=90.0, idle=45.0), _productivity(3.0)
    expected = cost.critical_ratio(productivity)
    rec = recommend_capacity(
        _monitored(_verdict("no_drift")),
        cost=cost,
        productivity=productivity,
        demand_quantile=_quantile_at(expected),
    )
    assert rec.service_level == pytest.approx(expected)
    assert rec.service_level_source == "cost_implied"
    assert rec.cost_optimal_service_level == pytest.approx(expected)
    assert rec.over_provisions_relative_to_stated_cost is False


def test_a_stated_policy_level_records_its_divergence_from_the_cost_optimum():
    """A planner may name 95% for legal reasons. The recommendation must show
    them that their own stated costs imply something lower -- silently honouring
    it would hide the policy decision they are making."""
    cost, productivity = _cost(), _productivity()
    rec = recommend_capacity(
        _monitored(_verdict("no_drift")),
        cost=cost,
        productivity=productivity,
        demand_quantile=_quantile_at(0.95),
        service_level=0.95,
    )
    assert rec.service_level_source == "stated_policy"
    assert rec.service_level == pytest.approx(0.95)
    assert rec.cost_optimal_service_level < 0.95
    assert rec.over_provisions_relative_to_stated_cost is True
    assert rec.implied_cost_ratio == pytest.approx(19.0)


def test_a_quantile_fitted_at_the_wrong_level_is_refused():
    """The easiest way to get a newsvendor decision subtly wrong is to
    provision to a quantile fitted somewhere else. It raises rather than
    quietly using the wrong one."""
    cost, productivity = _cost(), _productivity()
    with pytest.raises(ValueError, match="silent newsvendor error"):
        recommend_capacity(
            _monitored(_verdict("no_drift")),
            cost=cost,
            productivity=productivity,
            demand_quantile=_quantile_at(0.80),
            service_level=0.95,
        )


def test_hours_and_vehicles_follow_the_measured_productivity():
    cost = _cost()
    fast, slow = _productivity(4.0), _productivity(1.0)
    level = cost.critical_ratio(fast)
    rec_fast = recommend_capacity(
        _monitored(_verdict("no_drift")),
        cost=cost,
        productivity=fast,
        demand_quantile=_quantile_at(level),
        peak_span_hours=10.0,
    )
    assert rec_fast.required_vehicle_hours == pytest.approx(
        rec_fast.demand_at_service_level / 4.0
    )
    assert rec_fast.required_vehicles_in_service == math.ceil(
        rec_fast.required_vehicle_hours / 10.0
    )
    level_slow = cost.critical_ratio(slow)
    rec_slow = recommend_capacity(
        _monitored(_verdict("no_drift")),
        cost=cost,
        productivity=slow,
        demand_quantile=_quantile_at(level_slow),
    )
    assert rec_slow.required_vehicle_hours > rec_fast.required_vehicle_hours
    assert rec_slow.required_vehicles_in_service is None, (
        "no operating span was stated, so no vehicle count may be invented"
    )


def test_vehicles_and_span_must_be_supplied_together():
    with pytest.raises(ValidationError, match="supplied together"):
        CapacityRecommendation(
            required_vehicle_hours=61.0,
            required_vehicles_in_service=7,
            peak_span_hours=None,
            demand_point_estimate=4200.0,
            demand_at_service_level=4400.0,
            service_level=0.71,
            cost_optimal_service_level=0.71,
            service_level_source="cost_implied",
            implied_cost_ratio=2.45,
            interval_guarantee="unqualified",
            drift_status="no_drift",
            evidenced_service_level=0.71,
            sample_supports_level=True,
            n_calibration_residuals=400,
            max_expressible_level=400 / 401,
            cost=_cost(),
            productivity=_productivity(),
        )


def test_productivity_basis_records_dispersion_and_traceability():
    loose = ProductivityBasis(
        trips_per_vehicle_hour=2.0,
        source="s",
        derivation="d",
        n_observations=100,
        p10_trips_per_vehicle_hour=1.5,
        p90_trips_per_vehicle_hour=3.0,
    )
    assert loose.dispersion_ratio == pytest.approx(2.0)
    assert loose.is_traceable is False
    assert loose.vehicle_hours_for(100.0) == pytest.approx(50.0)
    with pytest.raises(ValidationError):
        ProductivityBasis(
            trips_per_vehicle_hour=2.0,
            source="s",
            derivation="d",
            n_observations=1,
            p10_trips_per_vehicle_hour=3.0,
            p90_trips_per_vehicle_hour=1.5,
        )


def test_empirical_service_level_measures_what_actually_fitted():
    productivity = _productivity(2.0)
    plans = [50.0, 50.0, 50.0, 50.0]  # 100 trips of capacity each
    actual = [90.0, 100.0, 101.0, 200.0]
    assert empirical_service_level(
        plan_vehicle_hours=plans,
        realised_demand_trips=actual,
        productivity=productivity,
    ) == pytest.approx(0.5)


# =========================================================================== #
# 7. REAL GOVERNED DATA  (Demonstrated -- NTD demand-response panel)
# =========================================================================== #
@pytest.mark.skipif(not _NTD_PANEL.exists(), reason="governed NTD DR panel absent")
def test_productivity_is_measurable_from_the_real_governed_panel():
    """The exchange rate is not a constant: it is measured per series from the
    only governed panel that records both demand and the capacity operated to
    meet it. This asserts the measurement is real and that the spread across
    agencies is wide enough that borrowing one agency's ratio for another would
    be a fabrication."""
    import pandas as pd

    from metis.forecast.serve_drift import sha256_of_file

    df = pd.read_csv(_NTD_PANEL)
    df = df[(df["vrh"] > 0) & (df["upt"] > 0)]
    assert not df.empty

    ratios = (df["upt"] / df["vrh"]).groupby(df["ntd_id"]).median()
    assert len(ratios) > 300, f"expected hundreds of agencies, got {len(ratios)}"
    p10, p90 = float(ratios.quantile(0.10)), float(ratios.quantile(0.90))
    assert 0.1 < p10 < p90 < 20.0
    assert p90 / p10 > 2.0, (
        "if productivity were near-constant across agencies a shared constant would be "
        "defensible; it is not, so it must be measured per series"
    )

    basis = ProductivityBasis(
        trips_per_vehicle_hour=float(ratios.median()),
        source="NTD monthly demand-response panel (upt/vrh)",
        derivation="median of per-agency median monthly upt/vrh",
        n_observations=int(len(ratios)),
        panel_path="data/curated/panels/ntd_monthly_dr.csv.gz",
        panel_sha256=sha256_of_file(_NTD_PANEL),
        p10_trips_per_vehicle_hour=p10,
        p90_trips_per_vehicle_hour=p90,
    )
    assert basis.is_traceable
    assert basis.panel_sha256 == sha256_of_file(_NTD_PANEL)


@pytest.mark.skipif(not _NTD_PANEL.exists(), reason="governed NTD DR panel absent")
def test_a_real_series_yields_a_recommendation_that_cannot_claim_its_level():
    """End-to-end on real governed data, at the real monthly grain.

    Thirty monthly observations cannot support the drift monitor's PSI, so the
    verdict is honestly `insufficient_data`, the guarantee is `not_assessed`,
    and the recommendation carries hours WITHOUT a service-level claim. That is
    the true state of a monthly capacity recommendation on public data, and the
    system states it rather than printing a level it cannot evidence.
    """
    import pandas as pd

    df = pd.read_csv(_NTD_PANEL)
    df["date"] = pd.to_datetime(df["date"])
    counts = df.groupby(["ntd_id", "tos"]).size()
    key = counts[counts >= 120].index[0]
    series = df[(df["ntd_id"] == key[0]) & (df["tos"] == key[1])].sort_values("date")
    series = series[(series["upt"] > 0) & (series["vrh"] > 0)]
    if len(series) < 100:
        pytest.skip("chosen series too sparse after filtering")

    upt = [float(v) for v in series["upt"]]
    vrh = [float(v) for v in series["vrh"]]
    valid_start = len(upt) - 30
    productivity = ProductivityBasis(
        trips_per_vehicle_hour=float(np.median([u / h for u, h in zip(upt[:valid_start], vrh[:valid_start])])),
        source=f"NTD DR ntd_id={key[0]} tos={key[1]}",
        derivation="median upt/vrh strictly before the validation window",
        n_observations=valid_start,
        panel_path="data/curated/panels/ntd_monthly_dr.csv.gz",
    )
    cost = _cost()
    level = cost.critical_ratio(productivity)

    residuals = [upt[t] - upt[t - 12] for t in range(valid_start - 36, valid_start)]
    quantile = fit_one_sided_conformal(residuals, target_level=level)

    rows = [
        {"demand_lag": float(upt[t - 12]), "temp_c": float(upt[t - 1])}
        for t in range(valid_start - 36, valid_start)
    ]
    reference = derive_reference_from_rows(
        rows,
        _FEATURES,
        source_kind="committed_panel",
        description="real NTD DR calibration window",
        derivation="lagged demand over the conformal calibration window",
        panel_path=_NTD_PANEL,
        max_sample=None,
    )
    serving = [
        {"demand_lag": float(upt[t - 12]), "temp_c": float(upt[t - 1])}
        for t in range(valid_start, len(upt))
    ]
    verdict = assess_drift(reference, serving, min_rows=400, target_coverage=level)
    assert verdict.status == "insufficient_data"
    assert verdict.interval_guarantee == "not_assessed"

    rec = recommend_capacity(
        _monitored(verdict, point=float(upt[-13])),
        cost=cost,
        productivity=productivity,
        demand_quantile=quantile,
    )
    assert rec.required_vehicle_hours > 0
    assert rec.evidenced_service_level is None
    assert "NOT ASSESSED" in rec.guarantee_caveat
    assert reference.provenance.is_traceable
    assert CENSORED_DEMAND_LIMITATION in rec.limitations
