"""Program H (partial): before/after evaluation of a scheduling intervention.

An agency swaps scheduling systems. On-time performance improves. Nobody can say
how much of that was the software and how much was the weather, a service
change, a fleet change, a demand-mix shift, or **regression to the mean** --
because the procurement was very often triggered by a bad quarter, and a bad
quarter is followed by a better one whether or not anything is bought.

This module computes the pre/post comparison anyway, because the comparison is
worth having, and then spends most of its output saying what the comparison
cannot support. Three commitments carry that:

- **PRE-REGISTRATION.** ``pre_register`` / ``pre_register_family`` fix the metric,
  the windows and the expected DIRECTION of the effect, hash them into a
  ``registration_sha256`` that can be published before the post period exists,
  and stamp ``registered_at``. A registration made after the post window opened
  cannot call itself prospective -- ``registration_timing`` is recomputed by a
  validator and construction raises on a mismatched claim. ``family_size`` is
  fixed at registration and drives the multiplicity correction, so registering
  four metrics and reporting the winner costs the winner its alpha.

- **THE CONFOUNDERS ARE THE OUTPUT.** ``MANDATORY_CONFOUNDERS`` -- seasonality,
  concurrent service change, demand-mix shift, fleet change, regression to the
  mean, secular trend / external shocks, and measurement-definition change --
  must ALL appear in every ``InterventionEvaluation``; a model validator raises
  if one is missing. Each carries a ``ConfounderStatus`` from a vocabulary with
  no ``"ruled_out"`` value, a ``direction_of_bias``, and the diagnostics behind
  it. Unresolved ones are also lifted to a top-level ``unresolved_confounders``
  so a truncated read cannot miss them, and ``summary()`` renders the estimate
  and the unresolved list on ONE line so a caller cannot quote the number
  without the qualification travelling with it (the ADR-0049 discipline).

- **THE VERDICT VOCABULARY REFUSES.** ``AttributionVerdict`` has no value that
  means "caused by"; its strongest value is
  ``"association_only_confounders_addressed"`` and reaching it REQUIRES a
  difference-in-differences design with zero unresolved confounders -- a
  validator raises otherwise, so an uncontrolled before/after literally cannot
  be typed into a stronger claim. ``EvidenceStrength`` has no ``"causal"``
  value, ``ComparisonDesign`` has no ``"randomised_experiment"`` value,
  ``causal_proof=True`` raises and ``is_randomised_experiment=True`` raises.

FRAMING (binding, ADR-0019 + blueprint/01, reused from
``packages.replay.comparison`` rather than restated): a pre/post difference is
an ASSOCIATION. Difference-in-differences against peer agencies is a stronger
association and still not an experiment -- it rests on a parallel-trends
assumption that can only ever be *not contradicted* in the pre period, never
verified, which is why ``ParallelTrendsCheck`` has no ``"verified"`` value.

EVIDENCE DISCIPLINE: every evaluation carries an ``InterventionManifest`` with a
deterministic ``evaluation_id``, order-independent series fingerprints, the
pre-registration hash, every input as ``(name, value, source)`` and numbered
method steps -- reusing ``teardown.InputRecord`` / ``teardown.MethodStep``
rather than defining a second evidence vocabulary.

Status: **Demonstrated**. There is no consented operator data in this repo, so
``DataProvenance`` is imported from ``teardown`` precisely because it has no
``"operator"`` value. Public NTD panels and synthetic series support method
claims only; nothing here is Validated and nothing here can become Validated
without an operator export and a real, dated intervention.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from datetime import timedelta
from typing import Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.canonical.events import canonical_json
from packages.canonical.time import UtcDateTime
from packages.replay.comparison import MODELLED_COMPARISON_NOTE, REPLAY_VERSION
from packages.replay.teardown import DataProvenance, InputRecord, MethodStep

INTERVENTION_VERSION = "0.1.0"

DEFAULT_ALPHA = 0.05
"""Family-wise error rate the pre-registration defaults to, before the
Bonferroni division by ``family_size``. A convention, not a law of nature."""

MIN_PERIODS_PER_WINDOW = 3
"""Fewer than three periods either side and a window mean has no dispersion to
speak of. Below this the evaluation reports ``insufficient_data`` rather than a
confident-looking interval computed from two points."""

MIN_HISTORY_PERIODS_FOR_REVERSION = 6
"""Periods of pre-window history needed before this module will estimate an
agency's own long-run mean. Below it, regression to the mean is reported as
``cannot_rule_out`` -- not as absent."""

MIN_PRE_PERIODS_FOR_TREND_CHECK = 4
"""Aligned treated-minus-control pre periods needed to fit a trend at all."""

AUTOCORRELATION_ATTENTION = 0.3
"""Lag-1 autocorrelation above which the independence assumption behind the
naive p-value is reported as materially violated. A rule of thumb."""

MAX_WINDOW_DAYS = 3653
"""A comparison window longer than ten years is a mis-specified window, not a
before/after. Rejected at construction."""

ASSOCIATION_NOTE = (
    "Association, not causation. This is a before/after comparison of an "
    "operational metric across a scheduling change. A difference between two "
    "periods is consistent with the intervention having worked and equally "
    "consistent with seasonality, a concurrent service change, a demand-mix "
    "shift, a fleet change, an external shock, a changed definition of the "
    "metric, or regression to the mean -- an agency that procures new software "
    "after a bad period improves somewhat regardless. This evaluation names "
    "every one of those in a structured field and states which of them the data "
    "supplied cannot rule out. It is not an experiment, it does not estimate a "
    "causal effect, and no arrangement of its inputs will make it do so."
)

PRE_REGISTRATION_NOTE = (
    "Pre-registered comparison. The metric, the pre and post windows, the "
    "expected direction of the effect and the number of metrics in the family "
    "were fixed and hashed before the post period was read. The hash can be "
    "published in advance and re-derived from the recorded fields. If the "
    "registration was reconstructed after the post window opened it says so "
    "(registration_timing='retrospective_reconstruction') and the evaluation is "
    "weaker for it: a metric chosen once the answer is visible is not evidence."
)

REGRESSION_TO_THE_MEAN_NOTE = (
    "Regression to the mean is the single most likely way a before/after "
    "software evaluation misleads. Procurement is usually triggered by a bad "
    "period, and a bad period is followed by a better one with or without an "
    "intervention. Where enough pre-window history was supplied, this "
    "evaluation states how much of the observed change a simple return to the "
    "agency's OWN long-run average would have predicted, and what is left over. "
    "Where history was not supplied, it says the confounder cannot be ruled out "
    "rather than assuming it away."
)

DIFFERENCE_IN_DIFFERENCES_NOTE = (
    "Difference-in-differences against a concurrent control series is stronger "
    "than an uncontrolled before/after -- it removes anything that moved both "
    "the treated agency and its peers over the same calendar -- and it is still "
    "not an experiment. Peers were not randomly assigned; the estimate rests on "
    "a parallel-trends assumption that can be contradicted by the pre period "
    "but never verified by it; and the interval below assumes the period-to-"
    "period differences are independent, which operational series are not. "
    "Critically, differencing against peers does NOT remove regression to the "
    "mean when the decision to intervene was itself triggered by an unusually "
    "bad period: that agency's rebound is its own and its peers do not share it, "
    "so it survives the subtraction and can make the controlled estimate LARGER "
    "than the uncontrolled one. Read the regression_to_the_mean block before "
    "reading this one."
)

REFUSALS: tuple[str, ...] = (
    "does not estimate a causal effect of the intervention",
    "does not claim the intervention caused the observed change",
    "does not report a saving, a payback period, or a monetary figure of any kind",
    "does not report an avoidable or recoverable share of the change",
    "does not describe itself as an experiment, a trial, or proof",
    "does not rule out any confounder it lacks the data to assess",
    "does not report a metric that was not pre-registered",
    "does not report a statistical test whose multiplicity correction ignores the "
    "other metrics registered alongside it",
)
"""What this artifact will not say, carried in the output itself so a reader
does not have to take the docstring's word for it. Each entry is enforced
somewhere in this module by a validator, an absent Literal value, or a raise --
not by convention."""


class InterventionError(Exception):
    """Raised when an intervention evaluation cannot be run honestly -- a
    registration that does not verify, a design that does not match the series
    supplied, or a metric that was never registered."""


# --------------------------------------------------------------------------
# Vocabularies. What is ABSENT from each of these is load-bearing.
# --------------------------------------------------------------------------

Direction = Literal["increase", "decrease"]
"""The pre-registered direction of the expected effect on the metric's own
scale. Fixed before the post period is read; if the metric moves the other way,
the evaluation says so instead of re-telling the story."""

ComparisonDesign = Literal["uncontrolled_pre_post", "difference_in_differences"]
"""How the comparison is identified. There is deliberately NO
"randomised_experiment" or "controlled_trial" value: this repo has never run
one, and a label that could assert one would be the easiest possible way to
imply otherwise (the same reason DataProvenance has no "operator" value)."""

RegistrationTiming = Literal["prospective", "retrospective_reconstruction"]
"""Whether the registration predates the post window. Derived from
``registered_at`` versus ``post_window.starts_at`` and re-checked by a
validator -- it cannot be asserted."""

MetricSource = Literal[
    "system_under_evaluation",
    "independent_of_intervention",
    "unknown",
]
"""Who produces the metric in the post period. "system_under_evaluation" is the
dangerous one: new scheduling software usually also becomes the thing that
computes on-time performance, and a changed definition of "on time" moves the
number with no change in service. Defaults to "unknown", which is treated as
unresolved -- never as safe."""

ConfounderStatus = Literal[
    "cannot_rule_out",
    "present_uncontrolled",
    "quantified_not_removed",
    "partially_addressed_by_design",
    "declared_absent_unverified",
]
"""How much is known about one confounder. There is deliberately NO "ruled_out"
and no "controlled" value: nothing in an observational before/after rules a
confounder out. "declared_absent_unverified" records that somebody looked and
said no, which is different from nobody looking and different again from
verification. "quantified_not_removed" records that a number was put on it and
left in the reader's hands."""

UNRESOLVED_CONFOUNDER_STATUSES: tuple[str, ...] = (
    "cannot_rule_out",
    "present_uncontrolled",
)
"""The statuses that block the strongest attribution verdict."""

BiasDirection = Literal[
    "would_flatter_the_intervention",
    "would_penalise_the_intervention",
    "unknown",
]
"""Which way a confounder pushes the estimate if it is real. Regression to the
mean following an adverse pre period always flatters the intervention, and
saying so is more useful than a p-value."""

DirectionVerdict = Literal[
    "insufficient_data",
    "no_detectable_change",
    "moved_in_pre_registered_direction",
    "moved_against_pre_registered_direction",
]
"""What the numbers did. A description of two window means, nothing more."""

AttributionVerdict = Literal[
    "insufficient_to_attribute",
    "association_only_confounded",
    "association_only_confounders_addressed",
]
"""What may be said about WHY. Every value contains the word association or
refuses outright; there is no value meaning "caused by", and the strongest one
is reachable only under difference-in-differences with no unresolved
confounder -- enforced by a validator on InterventionEvaluation, not by
documentation."""

EvidenceStrength = Literal[
    "insufficient",
    "weak_uncontrolled_association",
    "stronger_controlled_association",
]
"""How much the design can bear. No "causal", no "conclusive", no "proof"."""

ParallelTrendsCheck = Literal[
    "not_assessed",
    "insufficient_pre_periods",
    "not_contradicted_in_pre_period",
    "contradicted_in_pre_period",
]
"""The difference-in-differences identifying assumption. There is deliberately
NO "verified" value: a flat pre-period difference is consistent with parallel
trends and does not establish them for the post period, which is the period
that matters and the one that cannot be checked."""


# Mandatory confounder names. Every evaluation carries all of them.
SEASONALITY = "seasonality"
CONCURRENT_SERVICE_CHANGE = "concurrent_service_change"
DEMAND_MIX_SHIFT = "demand_mix_shift"
FLEET_CHANGE = "fleet_change"
REGRESSION_TO_THE_MEAN = "regression_to_the_mean"
SECULAR_TREND = "secular_trend_and_external_shocks"
MEASUREMENT_DEFINITION_CHANGE = "measurement_definition_change"

MANDATORY_CONFOUNDERS: tuple[str, ...] = (
    SEASONALITY,
    CONCURRENT_SERVICE_CHANGE,
    DEMAND_MIX_SHIFT,
    FLEET_CHANGE,
    REGRESSION_TO_THE_MEAN,
    SECULAR_TREND,
    MEASUREMENT_DEFINITION_CHANGE,
)
"""The confounders that must be named in EVERY evaluation, present or absent,
assessable or not. An InterventionEvaluation missing any of them raises at
construction -- which is what "named in the output, not buried" means when it
is a type rather than a promise."""


class _Intervention(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


class MetricSpec(_Intervention):
    """The metric being evaluated, defined precisely enough to be recomputed.

    ``higher_is_better`` reads the metric's own scale (on-time rate: True; cost
    per trip and denial rate: False). It is NOT the pre-registered direction --
    a registrant may legitimately expect a metric to worsen -- so both are
    recorded separately.
    """

    name: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    higher_is_better: bool
    definition: str = Field(
        min_length=1,
        description="How the metric is computed from the source records, verbatim.",
    )


class Window(_Intervention):
    """A half-open comparison window ``[starts_at, ends_at)``."""

    starts_at: UtcDateTime
    ends_at: UtcDateTime

    @model_validator(mode="after")
    def _is_a_window(self) -> "Window":
        if self.ends_at <= self.starts_at:
            raise ValueError(
                f"window ends at or before it starts ({self.ends_at.isoformat()} <= "
                f"{self.starts_at.isoformat()})"
            )
        if self.ends_at - self.starts_at > timedelta(days=MAX_WINDOW_DAYS):
            raise ValueError(
                f"window spans more than {MAX_WINDOW_DAYS} days; that is a "
                "mis-specified window, not a before/after comparison"
            )
        return self

    def contains(self, moment: UtcDateTime) -> bool:
        return self.starts_at <= moment < self.ends_at

    @property
    def days(self) -> float:
        return (self.ends_at - self.starts_at).total_seconds() / 86400.0


class SeriesPoint(_Intervention):
    """One period of an operational metric series.

    ``exposure`` is the size of the period (trips, vehicle-hours) and is used
    ONLY as a demand-shift diagnostic -- window means in this module are
    unweighted, and step 2 of the method says so. ``fleet_size`` feeds the fleet
    -change confounder; absent, that confounder reports cannot_rule_out.
    """

    period_start: UtcDateTime
    value: float
    exposure: float | None = Field(default=None, ge=0.0)
    fleet_size: float | None = Field(default=None, ge=0.0)


class MetricSeries(_Intervention):
    """One agency's series for one metric, plus where the numbers came from."""

    label: str = Field(min_length=1)
    metric_name: str = Field(min_length=1)
    provenance: DataProvenance
    points: tuple[SeriesPoint, ...]

    @model_validator(mode="after")
    def _one_value_per_period(self) -> "MetricSeries":
        starts = [p.period_start for p in self.points]
        if len(set(starts)) != len(starts):
            raise ValueError(
                f"series '{self.label}' has more than one point for the same "
                "period_start; a period with two values is a join defect, not a series"
            )
        return self


class ServiceChange(_Intervention):
    """A concurrent change the operator knows about, declared by the caller.

    ``expected_direction_on_metric`` is the caller's own read of which way it
    pushes the metric; when every declared change agrees, the confounder's
    ``direction_of_bias`` inherits it.
    """

    label: str = Field(min_length=1)
    effective_at: UtcDateTime
    description: str = Field(min_length=1)
    expected_direction_on_metric: Direction | None = None


class DemandMix(_Intervention):
    """The composition of demand either side of the cut, as shares.

    Shares need not sum to one (a caller may supply the two categories they
    track); the diagnostic is total variation distance over the union of keys,
    which is well defined either way and is reported, never adjusted for.
    """

    pre: Mapping[str, float]
    post: Mapping[str, float]
    source: str = Field(min_length=1)

    @model_validator(mode="after")
    def _shares_are_non_negative(self) -> "DemandMix":
        for label, mapping in (("pre", self.pre), ("post", self.post)):
            if not mapping:
                raise ValueError(f"demand mix '{label}' is empty; omit DemandMix entirely instead")
            for key, share in mapping.items():
                if share < 0:
                    raise ValueError(f"demand mix '{label}' share for {key!r} is negative ({share})")
        return self


# --------------------------------------------------------------------------
# Pre-registration
# --------------------------------------------------------------------------


class PreRegistration(_Intervention):
    """The comparison, fixed and hashed before the post period is read.

    ``registration_sha256`` is deterministic in every other field, so it can be
    published in advance and re-derived later by anyone; a mismatched value
    raises. ``registration_timing`` is recomputed from ``registered_at`` versus
    ``post_window.starts_at`` and raises on a mismatched claim, so a
    registration written after the answer was visible cannot call itself
    prospective. ``family_size`` is the number of metrics registered together
    and drives the Bonferroni correction: registering four metrics and reporting
    the best one costs that one its alpha, in the artifact, automatically.
    """

    intervention_version: str
    registered_at: UtcDateTime
    registration_timing: RegistrationTiming
    intervention_label: str = Field(min_length=1)
    intervention_at: UtcDateTime
    metric: MetricSpec
    expected_direction: Direction
    pre_window: Window
    post_window: Window
    design: ComparisonDesign
    control_plan: str = Field(
        min_length=1,
        description="What the control series is, or why there is none -- fixed in advance.",
    )
    family_size: int = Field(ge=1)
    family_metrics: tuple[str, ...]
    alpha: float = Field(gt=0.0, lt=1.0)
    analysis_plan: tuple[str, ...]
    registration_sha256: str
    note: str = PRE_REGISTRATION_NOTE

    @model_validator(mode="after")
    def _registration_is_internally_honest(self) -> "PreRegistration":
        if self.pre_window.ends_at > self.intervention_at:
            raise ValueError(
                "pre_window ends after the intervention "
                f"({self.pre_window.ends_at.isoformat()} > {self.intervention_at.isoformat()}); "
                "a 'before' window that contains the change is not a before window"
            )
        if self.post_window.starts_at < self.intervention_at:
            raise ValueError(
                "post_window starts before the intervention "
                f"({self.post_window.starts_at.isoformat()} < {self.intervention_at.isoformat()})"
            )
        if self.metric.name not in self.family_metrics:
            raise ValueError(
                f"metric {self.metric.name!r} is not in the registered family "
                f"{self.family_metrics}; a metric outside the family has no "
                "multiplicity correction and must not be evaluated"
            )
        if len(self.family_metrics) != self.family_size:
            raise ValueError(
                f"family_size ({self.family_size}) does not match family_metrics "
                f"({len(self.family_metrics)}); the correction would understate the "
                "number of chances taken"
            )
        if len(set(self.family_metrics)) != len(self.family_metrics):
            raise ValueError("family_metrics contains a duplicate; the family size would be wrong")

        expected_timing = _registration_timing(self.registered_at, self.post_window)
        if self.registration_timing != expected_timing:
            raise ValueError(
                f"registration_timing claims {self.registration_timing!r} but "
                f"registered_at={self.registered_at.isoformat()} against "
                f"post_window.starts_at={self.post_window.starts_at.isoformat()} makes it "
                f"{expected_timing!r}; a registration cannot assert it predates data it postdates"
            )

        expected_hash = _registration_hash(self)
        if self.registration_sha256 != expected_hash:
            raise ValueError(
                "registration_sha256 does not match the registered fields; the "
                "published hash and the registration have diverged"
            )
        return self

    @property
    def corrected_alpha(self) -> float:
        """Bonferroni across the registered family. Registering more metrics
        makes each one harder to call, which is the entire point."""
        return self.alpha / self.family_size


def _registration_timing(registered_at: UtcDateTime, post_window: Window) -> RegistrationTiming:
    if registered_at <= post_window.starts_at:
        return "prospective"
    return "retrospective_reconstruction"


def _registration_hash(registration: "PreRegistration") -> str:
    payload = {
        "intervention_version": registration.intervention_version,
        "registered_at": registration.registered_at.isoformat(),
        "intervention_label": registration.intervention_label,
        "intervention_at": registration.intervention_at.isoformat(),
        "metric": registration.metric.model_dump(mode="json"),
        "expected_direction": registration.expected_direction,
        "pre_window": registration.pre_window.model_dump(mode="json"),
        "post_window": registration.post_window.model_dump(mode="json"),
        "design": registration.design,
        "control_plan": registration.control_plan,
        "family_size": registration.family_size,
        "family_metrics": list(registration.family_metrics),
        "alpha": registration.alpha,
        "analysis_plan": list(registration.analysis_plan),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


_DEFAULT_ANALYSIS_PLAN: tuple[str, ...] = (
    "Compare the unweighted mean of the metric over the pre window against the "
    "unweighted mean over the post window; the estimate is post minus pre on the "
    "metric's own scale.",
    "Interval and p-value from Welch's two-sample t-test (unequal variances), "
    "then re-run with the sample sizes discounted for lag-1 autocorrelation; the "
    "MORE CONSERVATIVE of the two p-values is the one acted on.",
    "Call the change distinguishable from no change only below alpha divided by "
    "the number of metrics registered in this family (Bonferroni).",
    "Under difference_in_differences, analyse the treated-minus-control "
    "difference series so that the correlation between the two within a period "
    "is carried, and test parallel trends by fitting a slope to that difference "
    "over the pre window only.",
    "Assess every confounder in MANDATORY_CONFOUNDERS and report each with a "
    "status from a vocabulary that has no 'ruled out' value.",
    "Report the association. Do not estimate a causal effect.",
)


def pre_register(
    *,
    registered_at: UtcDateTime,
    intervention_label: str,
    intervention_at: UtcDateTime,
    metric: MetricSpec,
    expected_direction: Direction,
    pre_window: Window,
    post_window: Window,
    design: ComparisonDesign,
    control_plan: str,
    alpha: float = DEFAULT_ALPHA,
    family_metrics: Sequence[str] | None = None,
    analysis_plan: Sequence[str] | None = None,
) -> PreRegistration:
    """Fix one comparison before the post period is read.

    ``family_metrics`` names every metric registered alongside this one; it
    defaults to this metric alone, which is the honest default only when this
    really is the only metric being looked at. Use ``pre_register_family`` when
    it is not -- see its docstring for why the difference matters.
    """
    metrics = tuple(family_metrics) if family_metrics is not None else (metric.name,)
    if metric.name not in metrics:
        raise InterventionError(
            f"metric {metric.name!r} is not in family_metrics {metrics}; a metric "
            "evaluated outside its registered family carries no multiplicity correction"
        )

    draft = {
        "intervention_version": INTERVENTION_VERSION,
        "registered_at": registered_at,
        "registration_timing": _registration_timing(registered_at, post_window),
        "intervention_label": intervention_label,
        "intervention_at": intervention_at,
        "metric": metric,
        "expected_direction": expected_direction,
        "pre_window": pre_window,
        "post_window": post_window,
        "design": design,
        "control_plan": control_plan,
        "family_size": len(metrics),
        "family_metrics": metrics,
        "alpha": alpha,
        "analysis_plan": tuple(analysis_plan) if analysis_plan is not None else _DEFAULT_ANALYSIS_PLAN,
    }
    # Construct once with a placeholder to compute the hash over the real fields,
    # then re-construct with it: the hash is over the registration, not over itself.
    placeholder = PreRegistration.model_construct(**draft, registration_sha256="")
    return PreRegistration(**draft, registration_sha256=_registration_hash(placeholder))


def pre_register_family(
    *,
    registered_at: UtcDateTime,
    intervention_label: str,
    intervention_at: UtcDateTime,
    metrics: Sequence[MetricSpec],
    expected_directions: Mapping[str, Direction],
    pre_window: Window,
    post_window: Window,
    design: ComparisonDesign,
    control_plan: str,
    alpha: float = DEFAULT_ALPHA,
    analysis_plan: Sequence[str] | None = None,
) -> tuple[PreRegistration, ...]:
    """Register several metrics at once, with the family size baked into each.

    This exists because the failure mode is not usually a fabricated number, it
    is four honest numbers and a press release about the best one. Registering
    the family makes that arithmetically expensive: every returned registration
    carries ``family_size = len(metrics)``, so each metric's corrected alpha is
    ``alpha / family_size`` and the artifact names the siblings even when only
    one of them is reported.
    """
    if not metrics:
        raise InterventionError("cannot register an empty family of metrics")
    names = tuple(m.name for m in metrics)
    if len(set(names)) != len(names):
        raise InterventionError(f"duplicate metric name in family {names}")
    missing = [n for n in names if n not in expected_directions]
    if missing:
        raise InterventionError(
            f"no expected direction registered for {missing}; the direction of the "
            "expected effect is part of the pre-registration, not a later reading"
        )
    return tuple(
        pre_register(
            registered_at=registered_at,
            intervention_label=intervention_label,
            intervention_at=intervention_at,
            metric=metric,
            expected_direction=expected_directions[metric.name],
            pre_window=pre_window,
            post_window=post_window,
            design=design,
            control_plan=control_plan,
            alpha=alpha,
            family_metrics=names,
            analysis_plan=analysis_plan,
        )
        for metric in metrics
    )


# --------------------------------------------------------------------------
# Statistics. Pure Python -- packages/core/drift.py set the precedent of
# computing the distribution directly rather than adding scipy.
# --------------------------------------------------------------------------


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _sample_variance(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mu = _mean(values)
    return sum((v - mu) ** 2 for v in values) / (len(values) - 1)


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-16:
            break
    return h


def _regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    # `front` is invariant under (a, b, x) -> (b, a, 1-x), so the reflected
    # branch reuses it rather than recomputing.
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _t_two_sided_p(t: float, df: float) -> float:
    """Two-sided p-value for Student's t. Matches scipy.stats.t.sf*2 to ~1e-12
    over the range this module uses; scipy is deliberately not a dependency."""
    if df <= 0:
        return 1.0
    if math.isinf(t):
        return 0.0
    return _regularized_incomplete_beta(df / 2.0, 0.5, df / (df + t * t))


def _t_critical(df: float, alpha: float) -> float:
    """Two-sided critical value by bisection on the (monotone) p-value."""
    lo, hi = 0.0, 400.0
    for _ in range(120):
        mid = (lo + hi) / 2.0
        if _t_two_sided_p(mid, df) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _lag1_autocorrelation(pre: Sequence[float], post: Sequence[float]) -> float | None:
    """Pooled lag-1 autocorrelation of the within-window residuals.

    Each window is demeaned separately so the level shift under test is not
    itself read as autocorrelation, and the pair straddling the two windows is
    skipped. None when there are too few pairs to estimate anything.
    """
    residuals = []
    for window in (pre, post):
        if len(window) >= 2:
            mu = _mean(window)
            residuals.append([v - mu for v in window])
    pairs = sum(len(r) - 1 for r in residuals)
    if pairs < 3:
        return None
    denominator = sum(v * v for r in residuals for v in r)
    if denominator <= 0.0:
        return None
    numerator = sum(r[i] * r[i + 1] for r in residuals for i in range(len(r) - 1))
    return max(-0.99, min(0.99, numerator / denominator))


class _WelchResult:
    __slots__ = ("difference", "standard_error", "df", "p_value", "degenerate")

    def __init__(
        self, difference: float, standard_error: float, df: float, p_value: float, degenerate: bool
    ) -> None:
        self.difference = difference
        self.standard_error = standard_error
        self.df = df
        self.p_value = p_value
        self.degenerate = degenerate


def _welch(pre: Sequence[float], post: Sequence[float], *, n_pre: float, n_post: float) -> _WelchResult:
    """Welch's unequal-variance t-test of post minus pre.

    ``n_pre``/``n_post`` are passed separately from ``len()`` so the same code
    can be re-run with sample sizes discounted for autocorrelation.
    """
    difference = _mean(post) - _mean(pre)
    v_pre, v_post = _sample_variance(pre), _sample_variance(post)
    term_pre = v_pre / n_pre if n_pre > 0 else 0.0
    term_post = v_post / n_post if n_post > 0 else 0.0
    standard_error = math.sqrt(term_pre + term_post)

    if standard_error <= 0.0:
        # Both windows constant. A difference between two constants is real
        # arithmetic with no sampling uncertainty to report, and is flagged as
        # degenerate rather than dressed up with an interval.
        return _WelchResult(difference, 0.0, 0.0, 0.0 if difference != 0.0 else 1.0, True)

    numerator = (term_pre + term_post) ** 2
    denominator = 0.0
    if n_pre > 1:
        denominator += term_pre**2 / (n_pre - 1)
    if n_post > 1:
        denominator += term_post**2 / (n_post - 1)
    df = numerator / denominator if denominator > 0 else 1.0
    t_statistic = difference / standard_error
    return _WelchResult(difference, standard_error, df, _t_two_sided_p(t_statistic, df), False)


def _ols_slope_p_value(values: Sequence[float]) -> tuple[float, float] | None:
    """Slope of ``values`` against their own index, and its two-sided p-value.

    Used only for the parallel-trends pre-period check. None when there are too
    few points, or when the fit is exact (no residual variance to test against).
    """
    n = len(values)
    if n < 3:
        return None
    xs = list(range(n))
    x_bar, y_bar = _mean([float(x) for x in xs]), _mean(values)
    sxx = sum((x - x_bar) ** 2 for x in xs)
    if sxx <= 0:
        return None
    slope = sum((xs[i] - x_bar) * (values[i] - y_bar) for i in range(n)) / sxx
    intercept = y_bar - slope * x_bar
    residual_ss = sum((values[i] - (intercept + slope * xs[i])) ** 2 for i in range(n))
    df = n - 2
    if residual_ss <= 0.0 or df <= 0:
        return None
    standard_error = math.sqrt(residual_ss / df / sxx)
    return slope, _t_two_sided_p(slope / standard_error, float(df))


# --------------------------------------------------------------------------
# Result models
# --------------------------------------------------------------------------


class ConfounderAssessment(_Intervention):
    """One named confounder, its status, which way it would bias the estimate,
    and the numbers behind that judgement.

    ``why`` is written to be read out loud to somebody who knows the service.
    ``diagnostics`` reuses ``teardown.InputRecord`` so every figure carries the
    source it came from.
    """

    name: str = Field(min_length=1)
    status: ConfounderStatus
    why: str = Field(min_length=1)
    direction_of_bias: BiasDirection
    diagnostics: tuple[InputRecord, ...] = ()

    @property
    def unresolved(self) -> bool:
        return self.status in UNRESOLVED_CONFOUNDER_STATUSES


class ReversionDiagnostic(_Intervention):
    """Regression to the mean, quantified where the history allows it.

    ``predicted_change_from_reversion`` is the change a do-nothing agency would
    have shown by simply returning to its own long-run average.
    ``share_of_observed_change_explained_by_reversion`` at or above 1.0 means the
    entire observed improvement sits inside what mean-reversion alone predicts --
    the finding that should stop a procurement story, printed as a number.
    """

    assessable: bool
    reason_if_not_assessable: str | None
    history_period_count: int
    long_run_mean: float | None
    long_run_stdev: float | None
    pre_window_deviation_from_long_run: float | None
    pre_window_z_score: float | None
    pre_window_was_adverse: bool | None
    predicted_change_from_reversion: float | None
    share_of_observed_change_explained_by_reversion: float | None
    residual_change_beyond_reversion: float | None
    procurement_followed_adverse_period: bool | None
    note: str = REGRESSION_TO_THE_MEAN_NOTE


class WindowSummary(_Intervention):
    """One window's arithmetic, so a reader can redo it."""

    label: str
    period_count: int
    mean: float | None
    stdev: float | None
    minimum: float | None
    maximum: float | None
    exposure_total: float | None
    mean_fleet_size: float | None
    calendar_months: tuple[int, ...]


class AssociationEstimate(_Intervention):
    """The pre/post difference and its uncertainty. An association, nothing more.

    ``p_value`` is the more conservative of the independence-assuming Welch
    p-value and the same test re-run with sample sizes discounted for lag-1
    autocorrelation, because operational series are autocorrelated and the naive
    interval is optimistic. Both are reported so the discount is auditable.
    ``distinguishable_from_no_change`` is named to avoid the word significant,
    which readers hear as important and as caused.
    """

    estimate: float | None
    unit: str
    estimate_of: str
    relative_change: float | None
    confidence_level: float
    interval_low: float | None
    interval_high: float | None
    p_value_iid: float | None
    p_value_autocorrelation_adjusted: float | None
    p_value: float | None
    corrected_alpha: float
    family_size: int
    distinguishable_from_no_change: bool | None
    lag1_autocorrelation: float | None
    effective_pre_periods: float | None
    effective_post_periods: float | None
    variance_degenerate: bool
    interval_caveat: str


class DifferenceInDifferences(_Intervention):
    """The treated-minus-control estimate, and the assumption it rests on.

    Computed on the difference series (treated minus control at each aligned
    period) so the correlation between an agency and its peers within a period
    is carried rather than assumed away. ``parallel_trends`` can be contradicted
    by the pre period and never verified by it.
    """

    control_label: str
    control_provenance: DataProvenance
    aligned_period_count: int
    treated_periods_without_control: int
    control_periods_without_treated: int
    control_pre_mean: float | None
    control_post_mean: float | None
    control_change: float | None
    parallel_trends: ParallelTrendsCheck
    pre_period_difference_slope: float | None
    pre_period_difference_slope_p_value: float | None
    note: str = DIFFERENCE_IN_DIFFERENCES_NOTE


class InterventionManifest(_Intervention):
    """Pins what an evaluation used and how, so it is reproducible and auditable.

    ``evaluation_id`` is deterministic in the registration hash and the series
    fingerprints: the same registration over the same numbers pins the same id.
    """

    intervention_version: str
    replay_version: str
    evaluation_id: str
    dataset_label: str
    data_provenance: DataProvenance
    registration_sha256: str
    registration_timing: RegistrationTiming
    treated_series_sha256: str
    control_series_sha256: str | None
    treated_point_count: int
    washout_period_count: int
    periods_after_post_window: int
    periods_before_pre_window: int
    inputs: tuple[InputRecord, ...]
    method: tuple[MethodStep, ...]
    note: str = ASSOCIATION_NOTE
    replay_discipline_note: str = MODELLED_COMPARISON_NOTE


class InterventionEvaluation(_Intervention):
    """The structured, deliberately unimpressed answer to "did it work?".

    The refusals are enforced here, in the type:

    - ``causal_proof=True`` raises; ``is_randomised_experiment=True`` raises.
    - ``attribution_verdict="association_only_confounders_addressed"`` raises
      unless the design is difference-in-differences AND no confounder is
      unresolved -- so an uncontrolled before/after cannot be typed into the
      strongest available claim, whatever its p-value.
    - ``evidence_strength="stronger_controlled_association"`` raises without a
      control series.
    - an evaluation missing any of ``MANDATORY_CONFOUNDERS`` raises, and
      ``unresolved_confounders`` must agree with the assessments it summarises.
    """

    manifest: InterventionManifest
    pre_registration: PreRegistration
    design: ComparisonDesign
    pre_window_summary: WindowSummary
    post_window_summary: WindowSummary
    association: AssociationEstimate
    difference_in_differences: DifferenceInDifferences | None
    regression_to_the_mean: ReversionDiagnostic
    confounders: tuple[ConfounderAssessment, ...]
    unresolved_confounders: tuple[str, ...]
    direction_verdict: DirectionVerdict
    direction_matched_pre_registration: bool | None
    attribution_verdict: AttributionVerdict
    evidence_strength: EvidenceStrength
    refuses_to_claim: tuple[str, ...] = REFUSALS
    interpretation: str = ASSOCIATION_NOTE
    causal_proof: bool = False
    is_randomised_experiment: bool = False

    @field_validator("causal_proof")
    @classmethod
    def _never_claim_causation(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "an InterventionEvaluation must never claim causal proof "
                "(ADR-0019 / blueprint/01 boundary): an uncontrolled or "
                "quasi-experimental before/after identifies an association, and "
                "causal_proof is always False"
            )
        return value

    @field_validator("is_randomised_experiment")
    @classmethod
    def _never_claim_an_experiment(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "an InterventionEvaluation must never describe itself as a "
                "randomised experiment: no agency in this repo was randomly "
                "assigned to a scheduling system"
            )
        return value

    @model_validator(mode="after")
    def _refusals_are_structural(self) -> "InterventionEvaluation":
        names = tuple(c.name for c in self.confounders)
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate confounder assessment in {names}")
        missing = [name for name in MANDATORY_CONFOUNDERS if name not in names]
        if missing:
            raise ValueError(
                f"evaluation omits mandatory confounder(s) {missing}; every "
                "evaluation names all of MANDATORY_CONFOUNDERS whether or not the "
                "data supplied can say anything about them -- a confounder left "
                "out of the output is a confounder the reader will not think of"
            )

        unresolved = tuple(c.name for c in self.confounders if c.unresolved)
        if self.unresolved_confounders != unresolved:
            raise ValueError(
                f"unresolved_confounders {self.unresolved_confounders} does not "
                f"match the assessments {unresolved}; the top-level summary and "
                "the detail must not be able to disagree"
            )

        if self.attribution_verdict == "association_only_confounders_addressed":
            if self.design != "difference_in_differences":
                raise ValueError(
                    "attribution_verdict 'association_only_confounders_addressed' "
                    "requires a difference_in_differences design; an uncontrolled "
                    "before/after cannot support it however large the difference"
                )
            if unresolved:
                raise ValueError(
                    "attribution_verdict 'association_only_confounders_addressed' "
                    f"is contradicted by unresolved confounders {unresolved}"
                )
        if self.evidence_strength == "stronger_controlled_association":
            if self.design != "difference_in_differences" or self.difference_in_differences is None:
                raise ValueError(
                    "evidence_strength 'stronger_controlled_association' requires a "
                    "control series; there is none"
                )
        if (self.difference_in_differences is None) != (self.design == "uncontrolled_pre_post"):
            raise ValueError(
                "design and the presence of a difference_in_differences block must "
                f"agree: design={self.design!r} with "
                f"difference_in_differences={'absent' if self.difference_in_differences is None else 'present'}"
            )
        return self

    def summary(self) -> str:
        """The estimate and its qualifications on ONE line.

        Deliberately not separable: the ADR-0049 discipline is that a caller must
        not be able to quote the number without the caveat travelling with it, so
        there is no method that renders the estimate alone.
        """
        metric = self.pre_registration.metric
        if self.association.estimate is None:
            headline = f"{metric.name}: no estimate ({self.direction_verdict})"
        else:
            headline = (
                f"{metric.name} {self.association.estimate:+.4g} {metric.unit} "
                f"({self.pre_window_summary.mean:.4g} -> {self.post_window_summary.mean:.4g}), "
                f"{self.direction_verdict}"
            )
        unresolved = ", ".join(self.unresolved_confounders) or "none"
        reversion = self.regression_to_the_mean
        if reversion.share_of_observed_change_explained_by_reversion is not None:
            reversion_text = (
                f"mean-reversion alone predicts "
                f"{reversion.share_of_observed_change_explained_by_reversion:.0%} of it"
            )
        else:
            reversion_text = "regression to the mean not assessable"
        return (
            f"{headline} | design={self.design} | {self.attribution_verdict} | "
            f"evidence={self.evidence_strength} | unresolved confounders: {unresolved} | "
            f"{reversion_text} | not a causal estimate"
        )


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


def series_fingerprint(series: MetricSeries) -> str:
    """Order-independent checksum over a series -- the same points fingerprint
    identically however they were iterated."""
    ordered = sorted(
        [
            [p.period_start.isoformat(), p.value, p.exposure, p.fleet_size]
            for p in series.points
        ],
        key=lambda row: str(row[0]),
    )
    payload = {"label": series.label, "metric_name": series.metric_name, "points": ordered}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _round(value: float | None) -> float | None:
    """Fixed emitted precision, so a re-derivation matches digit for digit."""
    return None if value is None else round(value, 8)


def _round_p(value: float | None) -> float | None:
    """P-values keep significant figures rather than decimal places: rounding
    3e-12 to eight decimals prints 0.0, which reads as certainty."""
    return None if value is None else float(f"{value:.12g}")


def _window_points(series: MetricSeries, window: Window) -> list[SeriesPoint]:
    return sorted(
        (p for p in series.points if window.contains(p.period_start)),
        key=lambda p: p.period_start,
    )


def _summarise(label: str, points: Sequence[SeriesPoint]) -> WindowSummary:
    values = [p.value for p in points]
    exposures = [p.exposure for p in points if p.exposure is not None]
    fleets = [p.fleet_size for p in points if p.fleet_size is not None]
    return WindowSummary(
        label=label,
        period_count=len(points),
        mean=_round(_mean(values)) if values else None,
        stdev=_round(math.sqrt(_sample_variance(values))) if len(values) >= 2 else None,
        minimum=_round(min(values)) if values else None,
        maximum=_round(max(values)) if values else None,
        exposure_total=_round(sum(exposures)) if exposures else None,
        mean_fleet_size=_round(_mean(fleets)) if fleets else None,
        calendar_months=tuple(sorted({p.period_start.month for p in points})),
    )


def _reversion_diagnostic(
    *,
    history: Sequence[SeriesPoint],
    pre_mean: float | None,
    observed_change: float | None,
    higher_is_better: bool,
    procurement_followed_adverse_period: bool | None,
) -> ReversionDiagnostic:
    """Quantify how much of the observed change a return to the agency's own
    long-run average would have produced with no intervention at all."""
    base = dict(
        history_period_count=len(history),
        long_run_mean=None,
        long_run_stdev=None,
        pre_window_deviation_from_long_run=None,
        pre_window_z_score=None,
        pre_window_was_adverse=None,
        predicted_change_from_reversion=None,
        share_of_observed_change_explained_by_reversion=None,
        residual_change_beyond_reversion=None,
        procurement_followed_adverse_period=procurement_followed_adverse_period,
    )
    if len(history) < MIN_HISTORY_PERIODS_FOR_REVERSION or pre_mean is None:
        return ReversionDiagnostic(
            assessable=False,
            reason_if_not_assessable=(
                f"only {len(history)} period(s) of history before the pre window were "
                f"supplied; at least {MIN_HISTORY_PERIODS_FOR_REVERSION} are needed to "
                "estimate this agency's own long-run average, so it is not possible to "
                "say whether the pre window was a normal period or an unusually bad one"
            ),
            **base,
        )

    values = [p.value for p in history]
    long_run_mean = _mean(values)
    long_run_stdev = math.sqrt(_sample_variance(values))
    deviation = pre_mean - long_run_mean
    z_score = deviation / long_run_stdev if long_run_stdev > 0 else None
    was_adverse = deviation < 0 if higher_is_better else deviation > 0
    predicted = long_run_mean - pre_mean

    share = None
    residual = None
    if observed_change is not None:
        residual = observed_change - predicted
        if observed_change != 0.0:
            share = predicted / observed_change

    base.update(
        long_run_mean=_round(long_run_mean),
        long_run_stdev=_round(long_run_stdev),
        pre_window_deviation_from_long_run=_round(deviation),
        pre_window_z_score=_round(z_score),
        pre_window_was_adverse=was_adverse,
        predicted_change_from_reversion=_round(predicted),
        share_of_observed_change_explained_by_reversion=_round(share),
        residual_change_beyond_reversion=_round(residual),
    )
    return ReversionDiagnostic(assessable=True, reason_if_not_assessable=None, **base)


def _seasonality_confounder(
    pre: WindowSummary, post: WindowSummary, design: ComparisonDesign
) -> ConfounderAssessment:
    pre_months = Counter(pre.calendar_months)
    post_months = Counter(post.calendar_months)
    diagnostics = (
        InputRecord(name="pre_window_calendar_months", value=str(sorted(pre_months)), source="series period_start"),
        InputRecord(name="post_window_calendar_months", value=str(sorted(post_months)), source="series period_start"),
    )
    if pre_months and pre_months == post_months:
        return ConfounderAssessment(
            name=SEASONALITY,
            status="partially_addressed_by_design",
            why=(
                "the pre and post windows cover the identical set of calendar months, "
                "so month-of-year composition cannot by itself explain the change. It "
                "does not address a season that was unusually severe in one of the two "
                "years, which this design cannot separate from the intervention."
            ),
            direction_of_bias="unknown",
            diagnostics=diagnostics,
        )
    if design == "difference_in_differences":
        return ConfounderAssessment(
            name=SEASONALITY,
            status="partially_addressed_by_design",
            why=(
                "the windows are not calendar-aligned, but a concurrent control series "
                "runs over the same months, so seasonal movement COMMON to the treated "
                "agency and its peers differences out. Seasonal movement specific to "
                "this agency does not."
            ),
            direction_of_bias="unknown",
            diagnostics=diagnostics,
        )
    only_pre = sorted((pre_months - post_months).elements())
    only_post = sorted((post_months - pre_months).elements())
    return ConfounderAssessment(
        name=SEASONALITY,
        status="cannot_rule_out",
        why=(
            "the pre and post windows cover different calendar months "
            f"(only before: {only_pre}; only after: {only_post}) and no control series "
            "was supplied, so ordinary seasonal variation is confounded with the "
            "intervention and cannot be separated from it with the data given"
        ),
        direction_of_bias="unknown",
        diagnostics=diagnostics,
    )


def _service_change_confounder(
    changes: tuple[ServiceChange, ...] | None, expected_direction: Direction
) -> ConfounderAssessment:
    if changes is None:
        return ConfounderAssessment(
            name=CONCURRENT_SERVICE_CHANGE,
            status="cannot_rule_out",
            why=(
                "no declaration of concurrent service changes was supplied. A service "
                "area change, a fare change, a new contract or a policy change landing "
                "near the same date would move this metric on its own, and nothing here "
                "excludes one"
            ),
            direction_of_bias="unknown",
        )
    if not changes:
        return ConfounderAssessment(
            name=CONCURRENT_SERVICE_CHANGE,
            status="declared_absent_unverified",
            why=(
                "the operator declared no concurrent service changes over these windows. "
                "That is a statement by the party being evaluated and is recorded as "
                "such; nothing in this repo verifies it"
            ),
            direction_of_bias="unknown",
        )
    # If every declared change pushes the metric the way the registration hoped
    # it would go, the confounder flatters the intervention; if they all push the
    # other way it penalises it; a mixed or undeclared set stays unknown.
    directions = {c.expected_direction_on_metric for c in changes}
    bias: BiasDirection = "unknown"
    if len(directions) == 1 and None not in directions:
        only = directions.pop()
        bias = (
            "would_flatter_the_intervention"
            if only == expected_direction
            else "would_penalise_the_intervention"
        )
    return ConfounderAssessment(
        name=CONCURRENT_SERVICE_CHANGE,
        status="present_uncontrolled",
        why=(
            f"{len(changes)} concurrent change(s) were declared over these windows and "
            "this analysis does not adjust for any of them, so their effect is inside "
            "the estimate: "
            + "; ".join(f"{c.label} ({c.effective_at.date().isoformat()})" for c in changes)
        ),
        direction_of_bias=bias,
        diagnostics=tuple(
            InputRecord(
                name=f"concurrent_change:{c.label}",
                value=f"{c.effective_at.isoformat()} -- {c.description}",
                source="operator declaration",
            )
            for c in changes
        ),
    )


def _demand_mix_confounder(
    mix: DemandMix | None, pre: WindowSummary, post: WindowSummary
) -> ConfounderAssessment:
    diagnostics: list[InputRecord] = []
    exposure_ratio = None
    if pre.exposure_total and post.exposure_total and pre.exposure_total > 0:
        exposure_ratio = post.exposure_total / pre.exposure_total
        diagnostics.append(
            InputRecord(
                name="exposure_change_ratio",
                value=f"{exposure_ratio:.4f}",
                source="SeriesPoint.exposure (post total / pre total)",
            )
        )
    if mix is None:
        return ConfounderAssessment(
            name=DEMAND_MIX_SHIFT,
            status="cannot_rule_out",
            why=(
                "no demand composition was supplied for either window. A shift in who is "
                "riding -- ambulatory versus wheelchair, subscription versus same-day, "
                "long versus short, dialysis versus general -- changes what the metric "
                "measures without any change in scheduling quality"
                + (
                    f". Total exposure moved by a factor of {exposure_ratio:.3f} across "
                    "the cut, which is a volume signal and not a composition one"
                    if exposure_ratio is not None
                    else ""
                )
            ),
            direction_of_bias="unknown",
            diagnostics=tuple(diagnostics),
        )
    keys = sorted(set(mix.pre) | set(mix.post))
    total_variation = 0.5 * sum(abs(mix.pre.get(k, 0.0) - mix.post.get(k, 0.0)) for k in keys)
    diagnostics.append(
        InputRecord(
            name="demand_mix_total_variation_distance",
            value=f"{total_variation:.4f}",
            source=mix.source,
        )
    )
    diagnostics.extend(
        InputRecord(
            name=f"demand_mix:{k}",
            value=f"pre={mix.pre.get(k, 0.0):.4f} post={mix.post.get(k, 0.0):.4f}",
            source=mix.source,
        )
        for k in keys
    )
    return ConfounderAssessment(
        name=DEMAND_MIX_SHIFT,
        status="quantified_not_removed",
        why=(
            f"demand composition moved by a total variation distance of "
            f"{total_variation:.4f} across the cut. It is measured and reported; this "
            "analysis does NOT adjust the estimate for it, so the reader has to decide "
            "whether a shift that size could produce the change on its own"
        ),
        direction_of_bias="unknown",
        diagnostics=tuple(diagnostics),
    )


def _fleet_confounder(pre: WindowSummary, post: WindowSummary) -> ConfounderAssessment:
    if pre.mean_fleet_size is None or post.mean_fleet_size is None:
        return ConfounderAssessment(
            name=FLEET_CHANGE,
            status="cannot_rule_out",
            why=(
                "fleet size was not supplied for both windows. Vehicles added or "
                "withdrawn move on-time performance, cost per trip and denials directly, "
                "and are among the most common things to change at the same time as a "
                "scheduling system"
            ),
            direction_of_bias="unknown",
        )
    change = post.mean_fleet_size - pre.mean_fleet_size
    ratio = post.mean_fleet_size / pre.mean_fleet_size if pre.mean_fleet_size > 0 else None
    return ConfounderAssessment(
        name=FLEET_CHANGE,
        status="quantified_not_removed",
        why=(
            f"mean fleet size moved from {pre.mean_fleet_size:.4g} to "
            f"{post.mean_fleet_size:.4g} ({change:+.4g}"
            + (f", a factor of {ratio:.4f}" if ratio is not None else "")
            + "). It is measured and reported; the estimate is not adjusted for it"
        ),
        direction_of_bias="unknown",
        diagnostics=(
            InputRecord(name="pre_mean_fleet_size", value=f"{pre.mean_fleet_size:.6g}", source="SeriesPoint.fleet_size"),
            InputRecord(name="post_mean_fleet_size", value=f"{post.mean_fleet_size:.6g}", source="SeriesPoint.fleet_size"),
        ),
    )


def _reversion_confounder(diagnostic: ReversionDiagnostic) -> ConfounderAssessment:
    """Regression to the mean is assessed from the data, never from a caller's
    assertion: there is no argument a caller can pass that marks it addressed."""
    if diagnostic.procurement_followed_adverse_period:
        base_why = (
            "the caller declared that this procurement followed an adverse period, "
            "which is the textbook setup for regression to the mean: the agency would "
            "have improved somewhat with no intervention at all. "
        )
    else:
        base_why = ""

    if not diagnostic.assessable:
        return ConfounderAssessment(
            name=REGRESSION_TO_THE_MEAN,
            status="cannot_rule_out",
            why=base_why + (diagnostic.reason_if_not_assessable or "not assessable"),
            direction_of_bias=(
                "would_flatter_the_intervention"
                if diagnostic.procurement_followed_adverse_period
                else "unknown"
            ),
        )

    diagnostics = (
        InputRecord(name="long_run_mean", value=f"{diagnostic.long_run_mean}", source="pre-window history"),
        InputRecord(name="pre_window_deviation_from_long_run", value=f"{diagnostic.pre_window_deviation_from_long_run}", source="derived"),
        InputRecord(name="pre_window_z_score", value=f"{diagnostic.pre_window_z_score}", source="derived"),
        InputRecord(name="predicted_change_from_reversion", value=f"{diagnostic.predicted_change_from_reversion}", source="derived"),
        InputRecord(name="share_of_observed_change_explained_by_reversion", value=f"{diagnostic.share_of_observed_change_explained_by_reversion}", source="derived"),
        InputRecord(name="residual_change_beyond_reversion", value=f"{diagnostic.residual_change_beyond_reversion}", source="derived"),
    )
    share = diagnostic.share_of_observed_change_explained_by_reversion

    if diagnostic.pre_window_was_adverse or diagnostic.procurement_followed_adverse_period:
        if share is not None and share >= 1.0:
            why = (
                base_why
                + "the pre window was worse than this agency's own long-run average, and "
                f"a simple return to that average predicts {share:.0%} of the observed "
                "change -- that is, the whole of it. On these numbers the intervention "
                "has not been shown to add anything beyond mean-reversion. A control "
                "series does not fix this: peers did not share this agency's bad period, "
                "so its rebound survives the subtraction"
            )
        elif share is not None and share > 0.0:
            why = (
                base_why
                + "the pre window was worse than this agency's own long-run average; a "
                f"simple return to that average predicts {share:.0%} of the observed "
                "change, leaving "
                f"{diagnostic.residual_change_beyond_reversion} unexplained by reversion. "
                "The estimate is not adjusted for this"
            )
        else:
            why = (
                base_why
                + "the pre window was worse than this agency's own long-run average, so "
                "some improvement was expected with no intervention. The direction of "
                "the observed change does not line up with simple reversion, which is "
                "reported rather than interpreted"
            )
        return ConfounderAssessment(
            name=REGRESSION_TO_THE_MEAN,
            status="present_uncontrolled",
            why=why,
            direction_of_bias="would_flatter_the_intervention",
            diagnostics=diagnostics,
        )

    return ConfounderAssessment(
        name=REGRESSION_TO_THE_MEAN,
        status="quantified_not_removed",
        why=(
            "the pre window was NOT worse than this agency's own long-run average "
            f"(deviation {diagnostic.pre_window_deviation_from_long_run}, z="
            f"{diagnostic.pre_window_z_score}), so a bad-quarter rebound does not "
            "explain an improvement here. Mean-reversion is quantified and left in the "
            "output rather than declared absent"
        ),
        direction_of_bias="would_penalise_the_intervention",
        diagnostics=diagnostics,
    )


def _secular_trend_confounder(design: ComparisonDesign, control_label: str | None) -> ConfounderAssessment:
    if design == "difference_in_differences" and control_label is not None:
        return ConfounderAssessment(
            name=SECULAR_TREND,
            status="partially_addressed_by_design",
            why=(
                f"a concurrent control series ({control_label}) absorbs movement common "
                "to the treated agency and its peers over the same calendar -- weather, "
                "fuel price, a sector-wide demand recovery, a federal funding change. It "
                "does not absorb a shock specific to this agency, and it rests on the "
                "parallel-trends assumption reported alongside it"
            ),
            direction_of_bias="unknown",
        )
    return ConfounderAssessment(
        name=SECULAR_TREND,
        status="cannot_rule_out",
        why=(
            "no control series was supplied, so anything that moved the whole sector "
            "over these windows -- weather, fuel price, labour market, a demand recovery, "
            "a funding change -- is inside this estimate and indistinguishable from the "
            "intervention"
        ),
        direction_of_bias="unknown",
    )


def _measurement_confounder(measured_by: MetricSource) -> ConfounderAssessment:
    if measured_by == "system_under_evaluation":
        return ConfounderAssessment(
            name=MEASUREMENT_DEFINITION_CHANGE,
            status="present_uncontrolled",
            why=(
                "the post-period metric is produced by the software being evaluated. New "
                "scheduling systems usually also become the thing that computes on-time "
                "performance, and a changed definition of 'on time' -- a different clock, "
                "a different window, a different treatment of cancellations or no-shows -- "
                "moves the number with no change in the service a rider experiences. This "
                "is a like-for-like comparison only if the definition did not change, and "
                "nothing here establishes that"
            ),
            direction_of_bias="would_flatter_the_intervention",
        )
    if measured_by == "independent_of_intervention":
        return ConfounderAssessment(
            name=MEASUREMENT_DEFINITION_CHANGE,
            status="declared_absent_unverified",
            why=(
                "the metric is declared to be produced by a source independent of the "
                "intervention (an unchanged AVL feed, an NTD filing, a third-party "
                "monitor). Recorded as declared; nothing in this repo verifies that the "
                "definition held constant across the cut"
            ),
            direction_of_bias="unknown",
        )
    return ConfounderAssessment(
        name=MEASUREMENT_DEFINITION_CHANGE,
        status="cannot_rule_out",
        why=(
            "it was not stated who computes this metric in the post period. If the new "
            "system measures its own on-time performance, part or all of an apparent "
            "improvement can be a changed definition rather than changed service"
        ),
        direction_of_bias="unknown",
    )


def _method(design: ComparisonDesign, confidence_level: float) -> tuple[MethodStep, ...]:
    steps = [
        MethodStep(
            step="1. honour the registration",
            detail=(
                "Only points inside the pre-registered pre and post windows enter the "
                "estimate. Points between the windows (washout) and after the post window "
                "are counted in the manifest and excluded, so a reader can see that data "
                "existed which the registration did not use. The registration hash is "
                "re-derived and must match."
            ),
        ),
        MethodStep(
            step="2. window means",
            detail=(
                "Each window is summarised by the UNWEIGHTED mean of its period values. "
                "Exposure (trips, vehicle-hours) is carried as a demand-shift diagnostic "
                "and is deliberately NOT used to weight the mean: weighting would change "
                "the estimand from 'the typical period' to 'the typical trip' without the "
                "registration saying so."
            ),
        ),
        MethodStep(
            step="3. interval and p-value",
            detail=(
                f"Welch's unequal-variance t-test of post minus pre at "
                f"{confidence_level:.0%} confidence, then re-run with each window's sample "
                "size discounted by the pooled lag-1 autocorrelation of the within-window "
                "residuals (n_eff = n(1-rho)/(1+rho), applied only when rho > 0). The "
                "reported p_value is the MORE CONSERVATIVE of the two. The change is "
                "called distinguishable from no change only below alpha / family_size."
            ),
        ),
    ]
    if design == "difference_in_differences":
        steps.append(
            MethodStep(
                step="4. difference-in-differences",
                detail=(
                    "Treated and control are aligned on identical period_start values; "
                    "unaligned periods on either side are counted and dropped. The "
                    "estimate is the pre-to-post change in the treated-minus-control "
                    "difference series, so movement common to both cancels and the "
                    "within-period correlation between them is carried rather than "
                    "assumed away. Parallel trends is checked by fitting a slope to that "
                    "difference over the PRE window only: a slope indistinguishable from "
                    "zero leaves the assumption not contradicted, which is not the same "
                    "as verified and is never reported as such."
                ),
            )
        )
    steps.append(
        MethodStep(
            step=f"{5 if design == 'difference_in_differences' else 4}. confounders",
            detail=(
                "Every confounder in MANDATORY_CONFOUNDERS is assessed and reported with "
                "a status, a direction of bias and its diagnostics. Regression to the "
                "mean is computed from the supplied pre-window history -- the agency's "
                "own long-run average, the pre window's deviation from it, and the share "
                "of the observed change that a simple return to that average predicts. No "
                "caller argument can mark it resolved."
            ),
        )
    )
    steps.append(
        MethodStep(
            step=f"{6 if design == 'difference_in_differences' else 5}. verdict",
            detail=(
                "direction_verdict describes what the two window means did. "
                "attribution_verdict describes what may be said about why, from a "
                "vocabulary whose strongest value is "
                "'association_only_confounders_addressed' and which requires a "
                "difference-in-differences design with no unresolved confounder. No "
                "causal effect is estimated at any step."
            ),
        )
    )
    return tuple(steps)


def _evaluation_id(
    registration_sha256: str, treated_sha256: str, control_sha256: str | None
) -> str:
    payload = {
        "intervention_version": INTERVENTION_VERSION,
        "registration_sha256": registration_sha256,
        "treated_series_sha256": treated_sha256,
        "control_series_sha256": control_sha256,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def evaluate_intervention(
    pre_registration: PreRegistration,
    treated: MetricSeries,
    *,
    dataset_label: str,
    data_provenance: DataProvenance,
    control: MetricSeries | None = None,
    known_service_changes: tuple[ServiceChange, ...] | None = None,
    demand_mix: DemandMix | None = None,
    metric_measured_by: MetricSource = "unknown",
    procurement_followed_adverse_period: bool | None = None,
    confidence_level: float = 0.95,
) -> InterventionEvaluation:
    """Evaluate one pre-registered comparison, and say what it cannot support.

    ``known_service_changes`` distinguishes three states that a boolean would
    collapse: ``None`` (nobody looked -- ``cannot_rule_out``), ``()`` (the
    operator looked and declared none -- ``declared_absent_unverified``), and a
    non-empty tuple (declared and NOT adjusted for -- ``present_uncontrolled``).
    The same three-state honesty runs through ``demand_mix`` and
    ``metric_measured_by``; there is no argument that marks a confounder ruled
    out, because no argument could.

    Raises InterventionError when the series does not match the registration --
    a different metric, a control supplied against an uncontrolled registration,
    or a registered difference-in-differences with no control. Adding a control
    after registering an uncontrolled design is a design change and needs a new
    registration, not a keyword argument.
    """
    if treated.metric_name != pre_registration.metric.name:
        raise InterventionError(
            f"treated series carries metric {treated.metric_name!r} but the "
            f"registration fixed {pre_registration.metric.name!r}; evaluating a metric "
            "other than the registered one is exactly the substitution the "
            "pre-registration exists to prevent"
        )
    if pre_registration.design == "difference_in_differences" and control is None:
        raise InterventionError(
            "the registration fixed a difference_in_differences design but no control "
            "series was supplied"
        )
    if pre_registration.design == "uncontrolled_pre_post" and control is not None:
        raise InterventionError(
            "a control series was supplied against a registration that fixed an "
            "uncontrolled_pre_post design; adding a control after the fact changes the "
            "design and requires a new pre-registration"
        )
    if control is not None and control.metric_name != pre_registration.metric.name:
        raise InterventionError(
            f"control series carries metric {control.metric_name!r} but the registration "
            f"fixed {pre_registration.metric.name!r}"
        )
    if not 0.0 < confidence_level < 1.0:
        raise InterventionError(f"confidence_level must be within (0, 1), got {confidence_level}")

    pre_window, post_window = pre_registration.pre_window, pre_registration.post_window
    treated_pre = _window_points(treated, pre_window)
    treated_post = _window_points(treated, post_window)
    history = sorted(
        (p for p in treated.points if p.period_start < pre_window.starts_at),
        key=lambda p: p.period_start,
    )
    washout = [
        p for p in treated.points
        if pre_window.ends_at <= p.period_start < post_window.starts_at
    ]
    after = [p for p in treated.points if p.period_start >= post_window.ends_at]

    pre_summary = _summarise("pre", treated_pre)
    post_summary = _summarise("post", treated_post)

    enough = (
        len(treated_pre) >= MIN_PERIODS_PER_WINDOW and len(treated_post) >= MIN_PERIODS_PER_WINDOW
    )

    did_block: DifferenceInDifferences | None = None
    analysis_pre: list[float] = [p.value for p in treated_pre]
    analysis_post: list[float] = [p.value for p in treated_post]
    estimate_of = "post-window mean minus pre-window mean of the treated series"

    if control is not None:
        control_by_period = {p.period_start: p.value for p in control.points}
        aligned_pre = [
            (p.value - control_by_period[p.period_start])
            for p in treated_pre
            if p.period_start in control_by_period
        ]
        aligned_post = [
            (p.value - control_by_period[p.period_start])
            for p in treated_post
            if p.period_start in control_by_period
        ]
        control_pre = _window_points(control, pre_window)
        control_post = _window_points(control, post_window)
        treated_periods = {p.period_start for p in treated_pre} | {p.period_start for p in treated_post}
        control_periods = {p.period_start for p in control_pre} | {p.period_start for p in control_post}

        parallel: ParallelTrendsCheck = "insufficient_pre_periods"
        slope = slope_p = None
        if len(aligned_pre) >= MIN_PRE_PERIODS_FOR_TREND_CHECK:
            fit = _ols_slope_p_value(aligned_pre)
            if fit is None:
                parallel = "insufficient_pre_periods"
            else:
                slope, slope_p = fit
                parallel = (
                    "contradicted_in_pre_period"
                    if slope_p < pre_registration.alpha
                    else "not_contradicted_in_pre_period"
                )

        did_block = DifferenceInDifferences(
            control_label=control.label,
            control_provenance=control.provenance,
            aligned_period_count=len(aligned_pre) + len(aligned_post),
            treated_periods_without_control=len(treated_periods - control_periods),
            control_periods_without_treated=len(control_periods - treated_periods),
            control_pre_mean=_round(_mean([p.value for p in control_pre])) if control_pre else None,
            control_post_mean=_round(_mean([p.value for p in control_post])) if control_post else None,
            control_change=(
                _round(_mean([p.value for p in control_post]) - _mean([p.value for p in control_pre]))
                if control_pre and control_post
                else None
            ),
            parallel_trends=parallel,
            pre_period_difference_slope=_round(slope),
            pre_period_difference_slope_p_value=_round_p(slope_p),
        )
        analysis_pre, analysis_post = aligned_pre, aligned_post
        estimate_of = (
            "difference-in-differences: the pre-to-post change in the "
            "treated-minus-control difference series"
        )
        enough = (
            len(analysis_pre) >= MIN_PERIODS_PER_WINDOW
            and len(analysis_post) >= MIN_PERIODS_PER_WINDOW
        )

    # --- the association estimate -------------------------------------------------
    association = _estimate(
        analysis_pre,
        analysis_post,
        enough=enough,
        unit=pre_registration.metric.unit,
        estimate_of=estimate_of,
        confidence_level=confidence_level,
        corrected_alpha=pre_registration.corrected_alpha,
        family_size=pre_registration.family_size,
        design=pre_registration.design,
    )

    # --- confounders --------------------------------------------------------------
    # Regression to the mean is always about the TREATED agency's own series, so
    # it is measured against the raw treated change even under DiD, where the
    # headline estimate is a difference of differences.
    treated_change = (
        None
        if pre_summary.mean is None or post_summary.mean is None
        else post_summary.mean - pre_summary.mean
    )
    reversion = _reversion_diagnostic(
        history=history,
        pre_mean=pre_summary.mean,
        observed_change=treated_change,
        higher_is_better=pre_registration.metric.higher_is_better,
        procurement_followed_adverse_period=procurement_followed_adverse_period,
    )

    confounders = (
        _seasonality_confounder(pre_summary, post_summary, pre_registration.design),
        _service_change_confounder(known_service_changes, pre_registration.expected_direction),
        _demand_mix_confounder(demand_mix, pre_summary, post_summary),
        _fleet_confounder(pre_summary, post_summary),
        _reversion_confounder(reversion),
        _secular_trend_confounder(pre_registration.design, None if control is None else control.label),
        _measurement_confounder(metric_measured_by),
    )
    unresolved = tuple(c.name for c in confounders if c.unresolved)

    # --- verdicts -----------------------------------------------------------------
    direction_verdict, direction_matched = _direction_verdict(
        association, pre_registration.expected_direction
    )
    attribution = _attribution_verdict(direction_verdict, unresolved, pre_registration.design)
    strength = _evidence_strength(direction_verdict, pre_registration.design, control is not None)

    # --- manifest -----------------------------------------------------------------
    treated_sha = series_fingerprint(treated)
    control_sha = None if control is None else series_fingerprint(control)
    inputs = [
        InputRecord(name="treated_series_label", value=treated.label, source=dataset_label),
        InputRecord(name="treated_series_provenance", value=treated.provenance, source=dataset_label),
        InputRecord(name="metric", value=pre_registration.metric.name, source=pre_registration.metric.definition),
        InputRecord(name="intervention_at", value=pre_registration.intervention_at.isoformat(), source=pre_registration.intervention_label),
        InputRecord(name="pre_window", value=f"{pre_window.starts_at.isoformat()} .. {pre_window.ends_at.isoformat()}", source="pre-registration"),
        InputRecord(name="post_window", value=f"{post_window.starts_at.isoformat()} .. {post_window.ends_at.isoformat()}", source="pre-registration"),
        InputRecord(name="pre_window_periods", value=str(len(treated_pre)), source=dataset_label),
        InputRecord(name="post_window_periods", value=str(len(treated_post)), source=dataset_label),
        InputRecord(name="history_periods_before_pre_window", value=str(len(history)), source=dataset_label),
        InputRecord(name="washout_periods_excluded", value=str(len(washout)), source="pre-registration"),
        InputRecord(
            name="periods_after_post_window_excluded",
            value=str(len(after)),
            source=(
                "pre-registration: data outside the registered window exists and was not "
                "used; extending the window now would be a new registration"
            ),
        ),
        InputRecord(name="family_size", value=str(pre_registration.family_size), source="pre-registration"),
        InputRecord(name="corrected_alpha", value=f"{pre_registration.corrected_alpha:.6g}", source="Bonferroni over the registered family"),
        InputRecord(name="metric_measured_by", value=metric_measured_by, source="caller declaration"),
    ]
    if control is not None:
        inputs.append(InputRecord(name="control_series_label", value=control.label, source=dataset_label))
        inputs.append(InputRecord(name="control_series_provenance", value=control.provenance, source=dataset_label))

    manifest = InterventionManifest(
        intervention_version=INTERVENTION_VERSION,
        replay_version=REPLAY_VERSION,
        evaluation_id=_evaluation_id(pre_registration.registration_sha256, treated_sha, control_sha),
        dataset_label=dataset_label,
        data_provenance=data_provenance,
        registration_sha256=pre_registration.registration_sha256,
        registration_timing=pre_registration.registration_timing,
        treated_series_sha256=treated_sha,
        control_series_sha256=control_sha,
        treated_point_count=len(treated.points),
        washout_period_count=len(washout),
        periods_after_post_window=len(after),
        periods_before_pre_window=len(history),
        inputs=tuple(inputs),
        method=_method(pre_registration.design, confidence_level),
    )

    return InterventionEvaluation(
        manifest=manifest,
        pre_registration=pre_registration,
        design=pre_registration.design,
        pre_window_summary=pre_summary,
        post_window_summary=post_summary,
        association=association,
        difference_in_differences=did_block,
        regression_to_the_mean=reversion,
        confounders=confounders,
        unresolved_confounders=unresolved,
        direction_verdict=direction_verdict,
        direction_matched_pre_registration=direction_matched,
        attribution_verdict=attribution,
        evidence_strength=strength,
    )


def _estimate(
    pre: Sequence[float],
    post: Sequence[float],
    *,
    enough: bool,
    unit: str,
    estimate_of: str,
    confidence_level: float,
    corrected_alpha: float,
    family_size: int,
    design: ComparisonDesign,
) -> AssociationEstimate:
    caveat_base = (
        "The interval assumes the period values are independent draws. Operational "
        "series are autocorrelated, which makes the naive interval too narrow; the "
        "reported p_value is therefore the more conservative of the independence "
        "version and one with the sample sizes discounted for lag-1 autocorrelation. "
        "Neither version accounts for the confounders listed separately, none of "
        "which a wider interval would fix."
    )
    if design == "difference_in_differences":
        caveat_base += (
            " Difference-in-differences standard errors computed this way are known to "
            "be optimistic when the underlying series are serially correlated."
        )

    if not enough:
        return AssociationEstimate(
            estimate=None,
            unit=unit,
            estimate_of=estimate_of,
            relative_change=None,
            confidence_level=confidence_level,
            interval_low=None,
            interval_high=None,
            p_value_iid=None,
            p_value_autocorrelation_adjusted=None,
            p_value=None,
            corrected_alpha=corrected_alpha,
            family_size=family_size,
            distinguishable_from_no_change=None,
            lag1_autocorrelation=None,
            effective_pre_periods=None,
            effective_post_periods=None,
            variance_degenerate=False,
            interval_caveat=(
                f"fewer than {MIN_PERIODS_PER_WINDOW} periods on one side of the cut; no "
                "estimate is reported, because a mean of one or two periods with an "
                "interval attached is a decoration. " + caveat_base
            ),
        )

    naive = _welch(pre, post, n_pre=len(pre), n_post=len(post))
    rho = _lag1_autocorrelation(pre, post)
    adjusted = None
    effective_pre = effective_post = None
    if rho is not None and rho > 0:
        factor = (1.0 - rho) / (1.0 + rho)
        effective_pre = max(2.0, len(pre) * factor)
        effective_post = max(2.0, len(post) * factor)
        adjusted = _welch(pre, post, n_pre=effective_pre, n_post=effective_post)

    p_iid = naive.p_value
    p_adj = None if adjusted is None else adjusted.p_value
    p_used = p_iid if p_adj is None else max(p_iid, p_adj)
    acting = naive if (adjusted is None or p_iid >= p_adj) else adjusted

    low = high = None
    if not acting.degenerate and acting.df > 0:
        critical = _t_critical(acting.df, 1.0 - confidence_level)
        low = acting.difference - critical * acting.standard_error
        high = acting.difference + critical * acting.standard_error

    pre_mean = _mean(pre)
    relative = naive.difference / abs(pre_mean) if pre_mean != 0 else None

    return AssociationEstimate(
        estimate=_round(naive.difference),
        unit=unit,
        estimate_of=estimate_of,
        relative_change=_round(relative),
        confidence_level=confidence_level,
        interval_low=_round(low),
        interval_high=_round(high),
        p_value_iid=_round_p(p_iid),
        p_value_autocorrelation_adjusted=_round_p(p_adj),
        p_value=_round_p(p_used),
        corrected_alpha=corrected_alpha,
        family_size=family_size,
        distinguishable_from_no_change=p_used < corrected_alpha,
        lag1_autocorrelation=_round(rho),
        effective_pre_periods=_round(effective_pre),
        effective_post_periods=_round(effective_post),
        variance_degenerate=naive.degenerate,
        interval_caveat=(
            caveat_base
            + (
                ""
                if rho is None or rho <= AUTOCORRELATION_ATTENTION
                else f" Lag-1 autocorrelation is {rho:.3f}, materially above "
                f"{AUTOCORRELATION_ATTENTION}: the independence assumption is violated "
                "here and the discounted p-value is the one acted on."
            )
            + (
                " Both windows are constant, so there is no sampling variation to report "
                "and no interval is given."
                if naive.degenerate
                else ""
            )
        ),
    )


def _direction_verdict(
    association: AssociationEstimate, expected: Direction
) -> tuple[DirectionVerdict, bool | None]:
    if association.estimate is None or association.distinguishable_from_no_change is None:
        return "insufficient_data", None
    matched = (association.estimate > 0) if expected == "increase" else (association.estimate < 0)
    if association.estimate == 0:
        matched = False
    if not association.distinguishable_from_no_change:
        return "no_detectable_change", matched
    if matched:
        return "moved_in_pre_registered_direction", True
    return "moved_against_pre_registered_direction", False


def _attribution_verdict(
    direction_verdict: DirectionVerdict,
    unresolved: tuple[str, ...],
    design: ComparisonDesign,
) -> AttributionVerdict:
    if direction_verdict in ("insufficient_data", "no_detectable_change"):
        return "insufficient_to_attribute"
    if direction_verdict == "moved_against_pre_registered_direction":
        # The metric moved, against the registered expectation. That is a finding
        # about the series and supports nothing about the intervention.
        return "insufficient_to_attribute"
    if unresolved or design != "difference_in_differences":
        return "association_only_confounded"
    return "association_only_confounders_addressed"


def _evidence_strength(
    direction_verdict: DirectionVerdict, design: ComparisonDesign, has_control: bool
) -> EvidenceStrength:
    if direction_verdict == "insufficient_data":
        return "insufficient"
    if design == "difference_in_differences" and has_control:
        return "stronger_controlled_association"
    return "weak_uncontrolled_association"
