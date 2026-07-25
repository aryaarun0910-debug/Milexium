"""Capacity recommendation: the decision the forecast has to serve.

A demand forecast is not a product. "We predict 4,200 trips next month" is a
number; "you need 2,100 vehicle-revenue-hours to serve 71% of realised demand
under YOUR stated cost of a denied trip, and that figure carries NO coverage
guarantee because the serving window drifted" is a decision an operations
planner can act on and audit. This module is the distance between the two.

Four commitments, each one enforced in code rather than described in a
docstring:

1. FORECAST THE QUANTITY THE PLANNER COMMITS AGAINST. Operators do not commit
   to trips; they commit to vehicle-revenue-hours (VRH) and to vehicles
   operated in maximum service (VOMS). Both are what the National Transit
   Database actually records alongside ridership, and both are what a budget
   line and a driver roster are denominated in. `CapacityRecommendation` is
   denominated in vehicle-hours, with the demand forecast retained as the input
   it was derived from.

2. ASYMMETRIC COST IS THE POINT, AND IT IS STATED, NEVER DEFAULTED.
   Under-provisioning a paratransit service denies a disabled rider a trip they
   are legally entitled to under the ADA; over-provisioning wastes money. A
   squared-error objective treats those as equal, and its optimum is the
   conditional MEAN -- which is the cost-optimal decision ONLY when the two
   costs are identical. The correct decision is the classical newsvendor
   solution: provision to the `q*`-quantile of demand where

       q* = Cu / (Cu + Co)          (the critical ratio)

   with `Cu` the cost of one unit of unmet demand and `Co` the cost of one unit
   of unused capacity. `CostAsymmetry` has NO default values and no default
   constructor: every field is required, including who stated the numbers and
   on what basis. `recommend_capacity` takes `cost` as a required keyword
   argument. There is deliberately no code path that produces a capacity number
   without a stated cost structure, because a hidden default here does not
   merely pick a parameter -- it silently sets an operator's service policy,
   and 0.5 (the squared-error implicit default) is a policy almost no
   paratransit operator would sign.

3. THE INTERVAL'S GUARANTEE STATUS IS INHERITED, STRUCTURALLY. ADR-0049
   established that a conformal interval's coverage guarantee is WITHDRAWN when
   detected input drift contradicts exchangeability, and that the withdrawal
   travels attached to the forecast (`MonitoredForecast`). A capacity
   recommendation is derived FROM that interval, so it inherits that status --
   it cannot be sound where its input is not. `recommend_capacity` therefore
   accepts a `MonitoredForecast`, not a bare number, and
   `CapacityRecommendation.interval_guarantee` is a REQUIRED field validated
   against the caveat: a non-`unqualified` recommendation that carries no
   caveat, or that still claims an evidenced service level, will not construct.
   The failure is a `ValidationError`, not a missing sentence.

   The consequence is specific and worth stating plainly: under an
   `unsupported` interval the vehicle-hours figure is STILL RETURNED (report,
   do not decide -- ADR-0034 and ADR-0049), but `evidenced_service_level`
   becomes `None`. The number survives; the SERVICE-LEVEL CLAIM attached to it
   does not. "61 vehicle-hours" remains a planning figure. "61 vehicle-hours
   covers 95% of demand" is a coverage claim, and coverage is exactly what
   drift withdraws.

4. A SECOND, INDEPENDENT REASON THE CLAIM CAN FAIL. A one-sided conformal
   quantile at level `q*` needs `n` calibration residuals with
   `q* <= n / (n+1)`. Monthly agency data offers 12-24 residuals, so a 95%
   service level is simply not expressible from 12 months of history. This is
   not drift and is not fixed by monitoring; it is a finite-sample fact. It
   suppresses `evidenced_service_level` on its own
   (`ConformalQuantile.level_supported_by_sample`).

WHAT THIS MODULE IS NOT. It does not build a roster, does not solve for
vehicle blocks, and does not claim the recommended hours are schedulable --
converting hours into runnable blocks is Program A/F's problem and depends on
deadhead, breaks, and shift rules this module has no view of. It converts a
demand distribution and a stated cost structure into an hours figure, and is
honest about the exchange rate it used to do it.

Status: Demonstrated on public aggregate panels. NOTHING here is Validated: a
capacity claim requires consented operator data on DENIED trips, and no public
panel records them (see `ProductivityBasis` and `CENSORED_DEMAND_LIMITATION`).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.forecast.conformal import ConformalQuantile
from packages.forecast.serve_drift import (
    DriftVerdict,
    IntervalGuarantee,
    MonitoredForecast,
)

# The limitation that keeps every result on this data a METHOD claim. Public
# transit panels (NTD included) record DELIVERED service: trips carried and
# vehicle-hours operated. They do not record trips DENIED, refused at booking,
# or never requested because the rider learned the service was unavailable.
# Realised ridership is therefore a CENSORED observation of demand, censored
# from above by the capacity that was actually run. A backtest against it
# measures "can we predict the capacity an agency committed", NOT "can we
# predict the capacity an agency needed" -- and under-provisioning, the exact
# failure this module's cost asymmetry exists to price, is INVISIBLE in it.
CENSORED_DEMAND_LIMITATION = (
    "Public panels record DELIVERED service (trips carried, vehicle-hours operated), "
    "never DENIED trips. Realised ridership is demand censored from above by the "
    "capacity actually run, so under-provisioning -- the failure this cost asymmetry "
    "exists to price -- is unobservable in it. Any accuracy figure computed against "
    "such a panel is a claim about reproducing an operator's past commitment, not "
    "about meeting rider need. Closing this gap requires consented operator denial / "
    "unmet-trip records; until then no capacity result here can reach Validated."
)

# A point-estimate productivity ratio is itself an estimate, and the
# recommendation does not propagate its uncertainty into the service level.
PRODUCTIVITY_POINT_ESTIMATE_LIMITATION = (
    "The demand-to-vehicle-hours conversion uses a POINT estimate of productivity "
    "(trips per vehicle-revenue-hour). Its own sampling and month-to-month variation "
    "are recorded on the ProductivityBasis but are NOT propagated into the service "
    "level, so the stated level covers demand uncertainty only. In a month where "
    "realised productivity falls below the basis, the recommended hours under-serve "
    "by more than the stated level admits."
)

# Conformal coverage is marginal, and that is true even with no drift at all.
MARGINAL_COVERAGE_LIMITATION = (
    "Conformal coverage is MARGINAL -- an average over the calibration distribution, "
    "not a probability for any single month, zone or agency. An evidenced service "
    "level is not a promise about the next period, and absence of a drift flag is not "
    "evidence of exchangeability, only an absence of evidence against it."
)

SchedulabilityBasis = Literal["revenue_hours_only"]


# --------------------------------------------------------------------------- #
# 1. The cost structure -- stated, never defaulted
# --------------------------------------------------------------------------- #
class CostAsymmetry(BaseModel):
    """The planner's stated cost of getting capacity wrong in each direction.

    NO FIELD HAS A DEFAULT, and that is the design. A default cost asymmetry is
    a default service policy: at Cu == Co the critical ratio is 0.5 and the
    cost-optimal plan is the median forecast, which for a service carrying
    legally-entitled ADA trips is a policy essentially no operator would sign
    and no consultant would recommend. Making the caller supply the numbers
    forces the policy question into the open, where it belongs. `stated_by` and
    `basis` are required for the same reason -- an unattributed cost ratio is
    indistinguishable from an invented one, exactly as ADR-0049 argued for an
    unattributed drift reference.

    UNITS ARE NOT INTERCHANGEABLE, and the arithmetic respects that.
    `cost_per_unserved_trip` is per TRIP; `cost_per_idle_vehicle_hour` is per
    HOUR. Forming a ratio of the two directly would be a units error. The
    critical ratio therefore requires a `ProductivityBasis` to supply the
    exchange rate (trips per vehicle-hour), which is why `critical_ratio` is a
    METHOD taking that basis and not a bare property.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cost_per_unserved_trip: float = Field(
        gt=0.0,
        description="Cost of failing to serve one trip. For ADA paratransit this is not a "
        "fare: it is the operator's stated valuation of denying a legally-entitled trip, "
        "which may include complaint handling, FTA exposure and the policy weight the "
        "operator places on the denial itself.",
    )
    cost_per_idle_vehicle_hour: float = Field(
        gt=0.0,
        description="Cost of one vehicle-revenue-hour provisioned and not needed -- "
        "operator, fuel, and the marginal cost of holding the vehicle in service.",
    )
    stated_by: str = Field(
        min_length=1,
        description="Who stated these costs. Required: an unattributed cost ratio silently "
        "sets policy on an operator's behalf.",
    )
    basis: str = Field(
        min_length=1,
        description="How the numbers were arrived at (operator budget line, published "
        "settlement, illustrative placeholder). A placeholder is acceptable; concealing "
        "that it is one is not.",
    )
    stated_at: datetime | None = Field(
        default=None, description="When the statement was made, when that is known."
    )

    @classmethod
    def symmetric(cls, *, cost_per_unit: float, stated_by: str, basis: str) -> "CostAsymmetry":
        """Construct a deliberately SYMMETRIC cost structure with productivity
        of 1 trip/hour implied -- i.e. the implicit assumption of a
        squared-error objective, made explicit and attributable.

        This exists so that choosing symmetry is a recorded decision rather than
        the consequence of not choosing. It still demands `stated_by` and
        `basis`; there is no way to obtain a cost structure without signing for
        it.
        """
        return cls(
            cost_per_unserved_trip=cost_per_unit,
            cost_per_idle_vehicle_hour=cost_per_unit,
            stated_by=stated_by,
            basis=basis,
        )

    def cost_per_unused_trip_of_capacity(self, productivity: "ProductivityBasis") -> float:
        """`cost_per_idle_vehicle_hour` re-expressed per TRIP of excess capacity,
        using productivity as the exchange rate. Both costs are then in trip
        units and can legitimately be compared."""
        return self.cost_per_idle_vehicle_hour / productivity.trips_per_vehicle_hour

    def critical_ratio(self, productivity: "ProductivityBasis") -> float:
        """The newsvendor critical ratio `Cu / (Cu + Co)`: the demand quantile a
        cost-minimising planner provisions to.

        This is the whole argument against squared error in one line. Squared
        error's optimum is the conditional mean, which coincides with the
        cost-optimal decision only at `Cu == Co` (ratio 0.5). Any operator who
        believes a denied ADA trip costs more than an idle hour is, by their own
        statement, asking for a quantile above the median -- and a mean-optimal
        model cannot give them one.
        """
        cu = self.cost_per_unserved_trip
        co = self.cost_per_unused_trip_of_capacity(productivity)
        return cu / (cu + co)

    @staticmethod
    def implied_cost_ratio_for(service_level: float) -> float:
        """Inverse of `critical_ratio`: the Cu/Co ratio, BOTH IN TRIP UNITS,
        that would make `service_level` the cost-optimal choice.

        The number a planner should be shown when they name a service level out
        of habit or regulation. A 95% level is cost-optimal only if a denied
        trip is worth 19x a trip-equivalent of idle capacity; if their own
        stated costs imply 2.5x, they are choosing to over-provision relative
        to their own valuation -- which may be exactly right for a legal
        obligation, but should be a decision they are looking at.

        Unit-free and therefore static: once both costs are expressed per trip
        the productivity exchange rate has already been applied.
        """
        if not 0.0 < service_level < 1.0:
            raise ValueError(f"service_level must be in (0, 1); got {service_level}")
        return service_level / (1.0 - service_level)

    @property
    def is_symmetric(self) -> bool:
        """Symmetric in the RAW stated units. Note this is not the same as a
        0.5 critical ratio unless productivity is 1 trip/hour -- which is why
        the critical ratio needs the productivity basis."""
        return math.isclose(
            self.cost_per_unserved_trip, self.cost_per_idle_vehicle_hour, rel_tol=1e-9
        )

    def statement(self) -> str:
        """One-line attributable rendering, for the recommendation summary."""
        return (
            f"Cu={self.cost_per_unserved_trip:g}/unserved trip, "
            f"Co={self.cost_per_idle_vehicle_hour:g}/idle vehicle-hour "
            f"(stated by {self.stated_by}; basis: {self.basis})"
        )


# --------------------------------------------------------------------------- #
# 2. The demand-to-hours exchange rate -- measured, with provenance
# --------------------------------------------------------------------------- #
class ProductivityBasis(BaseModel):
    """Trips per vehicle-revenue-hour: the exchange rate turning a demand
    forecast into the hours a planner commits.

    A magic constant here would quietly determine the entire recommendation, so
    this object carries the same provenance discipline `ReferenceProvenance`
    applies to a drift baseline: which series, over what window, how many
    observations, and the dispersion around the point estimate. Demand-response
    productivity genuinely varies -- rural agencies run near 1 trip/hour, dense
    urban ADA services 2-3 -- so a ratio borrowed from another agency is a
    fabrication, not an approximation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    trips_per_vehicle_hour: float = Field(
        gt=0.0, description="Point estimate used for the conversion."
    )
    source: str = Field(min_length=1, description="Series the ratio was measured from.")
    derivation: str = Field(
        min_length=1, description="How it was computed (statistic, filters, exclusions)."
    )
    n_observations: int = Field(
        ge=1, description="Observations behind the point estimate -- 1 is legal and revealing."
    )
    window_start: datetime | None = None
    window_end: datetime | None = None
    panel_path: str | None = None
    panel_sha256: str | None = Field(
        default=None, description="SHA-256 of the source panel, so the ratio cites pinned bytes."
    )
    p10_trips_per_vehicle_hour: float | None = Field(
        default=None, gt=0.0, description="10th percentile across the window, when measured."
    )
    p90_trips_per_vehicle_hour: float | None = Field(
        default=None, gt=0.0, description="90th percentile across the window, when measured."
    )

    @model_validator(mode="after")
    def _percentiles_ordered(self) -> "ProductivityBasis":
        lo, hi = self.p10_trips_per_vehicle_hour, self.p90_trips_per_vehicle_hour
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"p10 ({lo}) must be <= p90 ({hi})")
        return self

    @property
    def is_traceable(self) -> bool:
        """True when the ratio cites a pinned panel, not merely a named one."""
        return bool(self.panel_path and self.panel_sha256)

    @property
    def dispersion_ratio(self) -> float | None:
        """p90/p10 -- how much the exchange rate itself moves. Above ~1.5 the
        point estimate is carrying a lot of unmodelled variation and
        PRODUCTIVITY_POINT_ESTIMATE_LIMITATION is doing real work."""
        lo, hi = self.p10_trips_per_vehicle_hour, self.p90_trips_per_vehicle_hour
        if lo is None or hi is None:
            return None
        return hi / lo

    def vehicle_hours_for(self, trips: float) -> float:
        """Vehicle-revenue-hours needed to carry `trips` at this productivity."""
        if trips < 0:
            raise ValueError(f"trips must be non-negative; got {trips}")
        return trips / self.trips_per_vehicle_hour

    def trace(self) -> str:
        parts = [f"{self.trips_per_vehicle_hour:.4f} trips/VRH from {self.source}"]
        if self.window_start and self.window_end:
            parts.append(f"window={self.window_start.date()}..{self.window_end.date()}")
        parts.append(f"n={self.n_observations}")
        if self.panel_sha256:
            parts.append(f"sha256={self.panel_sha256[:16]}...")
        return " | ".join(parts)


# --------------------------------------------------------------------------- #
# 3. The recommendation -- inherits the guarantee it was derived under
# --------------------------------------------------------------------------- #
_UNEVIDENCED_LEVEL_NOTE = (
    "SERVICE LEVEL NOT EVIDENCED. The hours figure is returned unchanged and is "
    "usable as a planning quantity, but it does NOT carry the stated service level: "
    "{reasons} Treat {hours:.1f} vehicle-hours as a point-derived plan, not as "
    "capacity evidenced to cover {level:.1%} of demand."
)


class CapacityRecommendation(BaseModel):
    """The hours a planner commits, with everything needed to audit them.

    The invariants below are enforced by a validator, not by convention, and
    they are the packet's central requirement. A recommendation whose interval
    guarantee is not `unqualified` CANNOT be constructed carrying an evidenced
    service level, and CANNOT be constructed without a caveat explaining why.
    Deleting the caveat text raises `ValidationError`; the honesty is
    structural.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- what the planner commits ---
    required_vehicle_hours: float = Field(
        ge=0.0, description="Vehicle-revenue-hours to provision over the forecast horizon."
    )
    required_vehicles_in_service: int | None = Field(
        default=None,
        ge=0,
        description="Vehicles needed if the hours are spread over a stated peak span "
        "(ceil(hours / span)). None unless a span was supplied -- the module will not "
        "invent an operating span.",
    )
    peak_span_hours: float | None = Field(default=None, gt=0.0)

    # --- what it was derived from ---
    demand_point_estimate: float = Field(description="The model's point forecast of demand (trips).")
    demand_at_service_level: float = Field(
        ge=0.0,
        description="Demand quantile actually provisioned to -- the newsvendor quantity.",
    )
    service_level: float = Field(gt=0.0, lt=1.0, description="Level provisioned to.")
    cost_optimal_service_level: float = Field(
        gt=0.0, lt=1.0, description="The critical ratio implied by the stated costs."
    )
    service_level_source: Literal["cost_implied", "stated_policy"]
    implied_cost_ratio: float = Field(
        gt=0.0,
        description="Cu/Co (trip units) that would make `service_level` cost-optimal -- the "
        "number that exposes a service level chosen by habit rather than by cost.",
    )

    # --- the inherited epistemic status (the point of the packet) ---
    interval_guarantee: IntervalGuarantee = Field(
        description="INHERITED verbatim from the MonitoredForecast's DriftVerdict (ADR-0049). "
        "Required, never defaulted: a recommendation derived from an interval cannot be "
        "sounder than that interval."
    )
    drift_status: Literal["no_drift", "drift", "insufficient_data"]
    guarantee_caveat: str | None = Field(
        default=None,
        description="The withdrawal statement, carried through from the drift verdict and "
        "extended with what it means for THIS recommendation. None only when the guarantee "
        "is unqualified AND the calibration sample supports the level.",
    )
    evidenced_service_level: float | None = Field(
        default=None,
        description="The service level this recommendation may CLAIM. None whenever the "
        "guarantee is withdrawn or the calibration sample cannot express the level.",
    )
    sample_supports_level: bool = Field(
        description="False when n calibration residuals cannot express `service_level` "
        "(level > n/(n+1)) -- a finite-sample failure independent of drift."
    )
    n_calibration_residuals: int = Field(ge=1)
    max_expressible_level: float = Field(gt=0.0, lt=1.0)

    # --- provenance ---
    cost: CostAsymmetry
    productivity: ProductivityBasis
    schedulability_basis: SchedulabilityBasis = Field(
        default="revenue_hours_only",
        description="These are REVENUE hours. Deadhead, layover, breaks and shift rules are "
        "not included and the figure is not asserted to be schedulable into blocks.",
    )
    limitations: tuple[str, ...] = Field(
        default=(), description="Every caveat that applies, carried with the number."
    )

    @model_validator(mode="after")
    def _guarantee_status_is_honoured(self) -> "CapacityRecommendation":
        """The invariant the packet exists for.

        A recommendation may not claim a service level it cannot evidence, and
        may not omit the explanation. Both directions are checked: a withdrawn
        guarantee must suppress the claim AND carry a caveat; an unqualified
        one must actually assert the level it provisioned to, so the honest
        path cannot be reached by simply blanking every field.
        """
        claimable = self.interval_guarantee == "unqualified" and self.sample_supports_level
        if not claimable:
            if self.evidenced_service_level is not None:
                raise ValueError(
                    "evidenced_service_level must be None when the interval guarantee is "
                    f"{self.interval_guarantee!r} or the calibration sample does not support "
                    f"the level (sample_supports_level={self.sample_supports_level}): a "
                    "capacity recommendation cannot claim coverage its interval does not carry."
                )
            if not self.guarantee_caveat:
                raise ValueError(
                    "guarantee_caveat is required when the interval guarantee is "
                    f"{self.interval_guarantee!r} or the sample cannot express the level -- "
                    "the withdrawal must be stated on the recommendation, not left to a docstring."
                )
        else:
            if self.evidenced_service_level is None:
                raise ValueError(
                    "an unqualified guarantee with a supporting sample must assert its "
                    "evidenced_service_level; a blank claim is not the same as an honest one."
                )
            if not math.isclose(self.evidenced_service_level, self.service_level, rel_tol=1e-9):
                raise ValueError(
                    f"evidenced_service_level ({self.evidenced_service_level}) must equal the "
                    f"level provisioned to ({self.service_level})."
                )
        if self.sample_supports_level != (self.service_level <= self.max_expressible_level):
            raise ValueError(
                f"sample_supports_level ({self.sample_supports_level}) contradicts "
                f"service_level {self.service_level} vs max_expressible_level "
                f"{self.max_expressible_level}."
            )
        if (self.required_vehicles_in_service is None) != (self.peak_span_hours is None):
            raise ValueError(
                "required_vehicles_in_service and peak_span_hours must be supplied together."
            )
        return self

    @property
    def service_level_is_evidenced(self) -> bool:
        return self.evidenced_service_level is not None

    @property
    def over_provisions_relative_to_stated_cost(self) -> bool:
        """True when the planner asked for a level above what their own stated
        costs justify -- legitimate for a legal obligation, but they should be
        looking at it."""
        return self.service_level > self.cost_optimal_service_level + 1e-12

    def expected_cost_against(self, realised_demand: float) -> float:
        """Realised asymmetric cost of this plan against an actual demand."""
        return asymmetric_capacity_cost(
            plan_vehicle_hours=self.required_vehicle_hours,
            realised_demand_trips=realised_demand,
            cost=self.cost,
            productivity=self.productivity,
        )

    def summary(self) -> str:
        """One line carrying the number and its status inseparably -- the same
        discipline as `MonitoredForecast.summary()`. A caller cannot quote the
        hours without the qualification travelling with them."""
        head = (
            f"provision {self.required_vehicle_hours:.1f} vehicle-hours"
            + (
                f" ({self.required_vehicles_in_service} vehicles over "
                f"{self.peak_span_hours:g}h)"
                if self.required_vehicles_in_service is not None
                else ""
            )
            + f" for demand p{self.service_level:.0%}={self.demand_at_service_level:.1f} trips "
            f"(point {self.demand_point_estimate:.1f}) drift={self.drift_status}"
        )
        if self.service_level_is_evidenced:
            return (
                f"{head} | service level {self.evidenced_service_level:.1%} EVIDENCED "
                f"(marginal, not a per-period probability) | {self.cost.statement()} | "
                f"{self.productivity.trace()}"
            )
        return f"{head} | {self.guarantee_caveat} | {self.cost.statement()} | {self.productivity.trace()}"


# --------------------------------------------------------------------------- #
# 4. The asymmetric objective itself
# --------------------------------------------------------------------------- #
def asymmetric_capacity_cost(
    *,
    plan_vehicle_hours: float,
    realised_demand_trips: float,
    cost: CostAsymmetry,
    productivity: ProductivityBasis,
) -> float:
    """Realised cost of a capacity plan under a STATED asymmetry.

    Shortfall is priced per unserved TRIP; surplus per idle VEHICLE-HOUR. The
    two are converted through the same productivity basis used to build the
    plan, so the objective and the decision speak one unit system.

    This is the newsvendor loss, and it is the metric a capacity claim should be
    scored on. Squared error is not: it is minimised by the conditional mean
    regardless of which direction of error hurts, which is precisely the
    property that makes it wrong here.
    """
    if plan_vehicle_hours < 0:
        raise ValueError(f"plan_vehicle_hours must be non-negative; got {plan_vehicle_hours}")
    if realised_demand_trips < 0:
        raise ValueError(f"realised_demand_trips must be non-negative; got {realised_demand_trips}")
    served_capacity_trips = plan_vehicle_hours * productivity.trips_per_vehicle_hour
    unserved_trips = max(realised_demand_trips - served_capacity_trips, 0.0)
    surplus_trips = max(served_capacity_trips - realised_demand_trips, 0.0)
    idle_hours = surplus_trips / productivity.trips_per_vehicle_hour
    return (
        cost.cost_per_unserved_trip * unserved_trips
        + cost.cost_per_idle_vehicle_hour * idle_hours
    )


def expected_asymmetric_cost(
    *,
    plan_vehicle_hours: float,
    demand_scenarios: Iterable[float],
    cost: CostAsymmetry,
    productivity: ProductivityBasis,
) -> float:
    """Mean asymmetric cost of a plan over an empirical demand distribution.

    Used to demonstrate -- by exhaustive search over a plan grid, not by
    assertion -- that the critical-ratio quantile is the cost-minimising plan
    and the mean is not.
    """
    scenarios = list(demand_scenarios)
    if not scenarios:
        raise ValueError("need at least one demand scenario")
    total = sum(
        asymmetric_capacity_cost(
            plan_vehicle_hours=plan_vehicle_hours,
            realised_demand_trips=float(d),
            cost=cost,
            productivity=productivity,
        )
        for d in scenarios
    )
    return total / len(scenarios)


def empirical_service_level(
    *,
    plan_vehicle_hours: Sequence[float],
    realised_demand_trips: Sequence[float],
    productivity: ProductivityBasis,
) -> float:
    """Fraction of periods whose realised demand fitted inside the plan -- the
    MEASURED service level, which is the number to report rather than the
    stated one."""
    if len(plan_vehicle_hours) != len(realised_demand_trips):
        raise ValueError(
            f"plan and realised series must be the same length; got "
            f"{len(plan_vehicle_hours)} and {len(realised_demand_trips)}"
        )
    if not plan_vehicle_hours:
        raise ValueError("need at least one period")
    met = sum(
        1
        for plan, actual in zip(plan_vehicle_hours, realised_demand_trips, strict=True)
        if plan * productivity.trips_per_vehicle_hour >= actual
    )
    return met / len(plan_vehicle_hours)


# --------------------------------------------------------------------------- #
# 5. The entry point
# --------------------------------------------------------------------------- #
def _caveat_for(
    *,
    verdict: DriftVerdict,
    quantile: ConformalQuantile,
    service_level: float,
    hours: float,
) -> str | None:
    """Assemble the withdrawal statement from every reason that applies.

    Both failure modes are reported when both hold. Collapsing them would tell
    a planner to wait for the drift to pass when the real problem is that they
    have twelve months of history.
    """
    reasons: list[str] = []
    if verdict.interval_guarantee != "unqualified" and verdict.interval_caveat:
        reasons.append(verdict.interval_caveat)
    shortfall = quantile.sample_shortfall_reason
    if shortfall:
        reasons.append(shortfall)
    if not reasons:
        return None
    return _UNEVIDENCED_LEVEL_NOTE.format(
        reasons=" ".join(reasons), hours=hours, level=service_level
    )


def recommend_capacity(
    forecast: MonitoredForecast,
    *,
    cost: CostAsymmetry,
    productivity: ProductivityBasis,
    demand_quantile: ConformalQuantile,
    service_level: float | None = None,
    peak_span_hours: float | None = None,
    extra_limitations: Sequence[str] = (),
) -> CapacityRecommendation:
    """Turn a monitored demand forecast into the vehicle-hours a planner commits.

    `forecast` is a `MonitoredForecast`, NOT a bare number, and that is the
    structural mechanism behind requirement 3: the drift verdict's
    `interval_guarantee` is copied onto the recommendation, so there is no way
    to obtain a capacity figure that has forgotten the epistemic status of the
    interval it came from. A caller who has only a point estimate must first
    obtain a verdict -- and a verdict on an unassessable window is honestly
    `not_assessed`, which withdraws the claim rather than granting it.

    `cost` is REQUIRED and has no default anywhere in this call chain
    (`conformance/property-tests/test_capacity_forecast.py` asserts that by
    signature inspection, so a later convenience default fails the suite).

    `service_level` may be omitted, in which case the cost-optimal critical
    ratio `Cu / (Cu + Co)` is used. That is a DERIVATION from the stated costs,
    not a default: the policy input is still the costs, which the caller had to
    state. Supplying a level explicitly is the "stated_policy" path, and the
    recommendation then records both the level used and the level the costs
    imply, so a divergence is visible instead of silent.

    `demand_quantile` must have been fitted at the level actually being
    provisioned to; a mismatch raises rather than quietly provisioning to the
    wrong quantile. This is the easiest way to get a newsvendor decision
    subtly wrong, so it is checked.
    """
    verdict = forecast.drift
    resolved_level = service_level if service_level is not None else cost.critical_ratio(productivity)
    source: Literal["cost_implied", "stated_policy"] = (
        "stated_policy" if service_level is not None else "cost_implied"
    )
    if not 0.0 < resolved_level < 1.0:
        raise ValueError(f"service level must be in (0, 1); got {resolved_level}")
    if not math.isclose(demand_quantile.target_level, resolved_level, rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError(
            f"demand_quantile was fitted at level {demand_quantile.target_level} but the "
            f"recommendation provisions to {resolved_level}. Refit the conformal quantile at "
            f"the level being provisioned to -- provisioning to a quantile fitted elsewhere is "
            f"a silent newsvendor error."
        )

    point = forecast.point_estimate
    demand_at_level = demand_quantile.apply(point)
    hours = productivity.vehicle_hours_for(demand_at_level)
    vehicles = (
        int(math.ceil(hours / peak_span_hours)) if peak_span_hours is not None else None
    )

    caveat = _caveat_for(
        verdict=verdict, quantile=demand_quantile, service_level=resolved_level, hours=hours
    )
    claimable = (
        verdict.interval_guarantee == "unqualified" and demand_quantile.level_supported_by_sample
    )
    limitations = [
        CENSORED_DEMAND_LIMITATION,
        PRODUCTIVITY_POINT_ESTIMATE_LIMITATION,
        MARGINAL_COVERAGE_LIMITATION,
        *extra_limitations,
    ]
    if not productivity.is_traceable:
        limitations.append(
            "The productivity basis does not cite a pinned panel (path + SHA-256), so the "
            "demand-to-hours exchange rate is named but not traceable."
        )

    return CapacityRecommendation(
        required_vehicle_hours=hours,
        required_vehicles_in_service=vehicles,
        peak_span_hours=peak_span_hours,
        demand_point_estimate=point,
        demand_at_service_level=demand_at_level,
        service_level=resolved_level,
        cost_optimal_service_level=cost.critical_ratio(productivity),
        service_level_source=source,
        implied_cost_ratio=CostAsymmetry.implied_cost_ratio_for(resolved_level),
        interval_guarantee=verdict.interval_guarantee,
        drift_status=verdict.status,
        guarantee_caveat=caveat,
        evidenced_service_level=resolved_level if claimable else None,
        sample_supports_level=demand_quantile.level_supported_by_sample,
        n_calibration_residuals=demand_quantile.n_calibration,
        max_expressible_level=demand_quantile.max_expressible_level,
        cost=cost,
        productivity=productivity,
        limitations=tuple(limitations),
    )
