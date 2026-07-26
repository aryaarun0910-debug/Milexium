"""Program H (partial): baseline-vs-Milexium metric comparison.

NON-NEGOTIABLE FRAMING (blueprint/01-north-star-and-boundaries.md, carried
here verbatim because it is load-bearing): **"Replay is a modelled comparison,
not causal proof of savings."** and **"Public aggregate data validates
aggregate demand tasks, not individual dispatch."**

Given the recorded/simulated outcomes of two schedules -- a baseline and
Milexium's -- over the *same* request set, this module computes a per-metric
comparison (served trips, denials, on-time pickup rate, excess ride time,
deadhead, utilization) with baseline value, Milexium value, and delta. It does
NOT compute or claim a monetary saving, and it never asserts that Milexium
*caused* any delta: at least one of the two schedules is always a counterfactual
that was not actually operated over that identical request set, so every delta
is a modelled difference between two schedules, not measured proof of impact.

Observed vs modelled is expressed structurally, not just in prose:
- each ScheduleOutcomeSet carries a `provenance` ("observed" | "simulated");
- each metric carries a `basis` ("recorded_outcomes" | "modelled_fleet_
  accounting") -- utilization is fleet-level accounting supplied by the schedule
  source, the other five are derived from recorded per-request Outcome rows.
"""

from __future__ import annotations

import hashlib
from typing import Callable, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, field_validator

from app.canonical.entities import Outcome
from app.canonical.events import canonical_json
from app.canonical.time import UtcDateTime
from app.replay.replay import ReplayError

REPLAY_VERSION = "0.1.0"

OutcomeProvenance = Literal["observed", "simulated"]
"""Whether a schedule's outcomes were recorded from a real operation
("observed") or produced by simulation/what-if ("simulated"). A counterfactual
baseline is always "simulated"; a shadow-mode schedule that was scored but not
operated is "simulated" too."""

MetricBasis = Literal["recorded_outcomes", "modelled_fleet_accounting"]
"""Where a metric's value comes from: per-request recorded Outcome fields, or
fleet-level accounting the schedule source supplies (utilization)."""

MODELLED_COMPARISON_NOTE = (
    "Modelled comparison, not causal proof of savings. This compares the "
    "recorded or simulated outcomes of two schedules over the same request "
    "set; at least one schedule is a counterfactual that was not actually "
    "operated over that identical set, so every delta is a modelled difference "
    "between schedules, not measured proof that Milexium caused an improvement. "
    "Public aggregate data validates aggregate demand tasks, not individual "
    "dispatch. No monetary savings figure is derived."
)


class ScheduleOutcomeSet(BaseModel):
    """One schedule's outcomes over a request set, plus the provenance and the
    optional fleet accounting a utilization figure needs.

    `outcomes` holds one Outcome per request the schedule faced (a denial is an
    Outcome with served=False, not an absence). `available_vehicle_minutes` and
    `productive_vehicle_minutes` are fleet-level, schedule-reported quantities
    -- absent them, utilization is reported as unavailable rather than guessed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schedule_label: str
    provenance: OutcomeProvenance
    outcomes: tuple[Outcome, ...]
    available_vehicle_minutes: float | None = None
    productive_vehicle_minutes: float | None = None


class MetricDelta(BaseModel):
    """One operational metric compared across the two schedules.

    `delta` is Milexium minus baseline (None if either side is unavailable).
    `favors_milexium` reads the delta against `higher_is_better` -- None when the
    delta is zero or unavailable. It describes *this modelled run only* and is
    never a causal claim.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    unit: str
    higher_is_better: bool
    basis: MetricBasis
    baseline: float | None
    milexium: float | None
    delta: float | None
    favors_milexium: bool | None


class ReplayManifest(BaseModel):
    """Pins what a replay comparison used, so it is reproducible and auditable.

    Records the request-set identity (label + a checksum over its request ids),
    the replay instant the decisions were reconstructed as of, both outcome
    sources with their provenance, and the exact metric definitions applied.
    `replay_id` is deterministic in these inputs: the same replay pins the same
    id.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    replay_version: str
    replay_id: str
    request_set_label: str
    request_set_sha256: str
    request_count: int
    replay_instant: UtcDateTime
    baseline_label: str
    baseline_provenance: OutcomeProvenance
    milexium_label: str
    milexium_provenance: OutcomeProvenance
    metric_definitions: tuple[str, ...]
    note: str


class ReplayComparison(BaseModel):
    """The structured result: manifest + per-metric deltas, framed as a modelled
    comparison. `causal_proof` is fixed False and rejected if set True -- the
    boundary is enforced in the type, not only in the docstring."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: ReplayManifest
    metrics: tuple[MetricDelta, ...]
    is_modelled_comparison: bool
    causal_proof: bool = False
    interpretation: str = MODELLED_COMPARISON_NOTE

    @field_validator("causal_proof")
    @classmethod
    def _never_claim_causation(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "a ReplayComparison must never claim causal proof of savings "
                "(blueprint/01 boundary); causal_proof is always False"
            )
        return value


class _MetricSpec(NamedTuple):
    """Single source of truth for a metric: its definition string (copied into
    the manifest) and how it is computed from a ScheduleOutcomeSet."""

    name: str
    unit: str
    higher_is_better: bool
    basis: MetricBasis
    definition: str
    compute: Callable[[ScheduleOutcomeSet], float | None]


def _served_trips(s: ScheduleOutcomeSet) -> float | None:
    return float(sum(1 for o in s.outcomes if o.served))


def _denials(s: ScheduleOutcomeSet) -> float | None:
    return float(sum(1 for o in s.outcomes if not o.served))


def _on_time_pickup_rate(s: ScheduleOutcomeSet) -> float | None:
    # Rate over served trips whose on-time status is known; unknowns are excluded
    # from both numerator and denominator rather than counted as failures.
    known = [o for o in s.outcomes if o.served and o.on_time is not None]
    if not known:
        return None
    return sum(1 for o in known if o.on_time) / len(known)


def _mean_excess_ride_time(s: ScheduleOutcomeSet) -> float | None:
    vals = [
        o.excess_ride_time_minutes
        for o in s.outcomes
        if o.served and o.excess_ride_time_minutes is not None
    ]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _total_deadhead(s: ScheduleOutcomeSet) -> float | None:
    vals = [o.deadhead_minutes for o in s.outcomes if o.deadhead_minutes is not None]
    if not vals:
        return None
    return float(sum(vals))


def _utilization(s: ScheduleOutcomeSet) -> float | None:
    # Fleet-level, modelled: productive over available vehicle minutes, only when
    # the schedule source supplied both -- never inferred from per-trip rows.
    if (
        s.available_vehicle_minutes is not None
        and s.available_vehicle_minutes > 0
        and s.productive_vehicle_minutes is not None
    ):
        return s.productive_vehicle_minutes / s.available_vehicle_minutes
    return None


METRIC_SPECS: tuple[_MetricSpec, ...] = (
    _MetricSpec(
        "served_trips", "trips", True, "recorded_outcomes",
        "Count of outcomes with served=True.", _served_trips,
    ),
    _MetricSpec(
        "denials", "trips", False, "recorded_outcomes",
        "Count of outcomes with served=False.", _denials,
    ),
    _MetricSpec(
        "on_time_pickup_rate", "fraction", True, "recorded_outcomes",
        "Served trips with on_time=True divided by served trips whose on_time "
        "is known (unknowns excluded from both sides); null if none known.",
        _on_time_pickup_rate,
    ),
    _MetricSpec(
        "mean_excess_ride_time_minutes", "minutes", False, "recorded_outcomes",
        "Mean of excess_ride_time_minutes over served trips that recorded one; "
        "null if none recorded.", _mean_excess_ride_time,
    ),
    _MetricSpec(
        "total_deadhead_minutes", "minutes", False, "recorded_outcomes",
        "Sum of deadhead_minutes over outcomes that recorded one; null if none "
        "recorded.", _total_deadhead,
    ),
    _MetricSpec(
        "utilization", "fraction", True, "modelled_fleet_accounting",
        "Modelled: productive_vehicle_minutes / available_vehicle_minutes as "
        "reported by the schedule source; null unless both supplied.",
        _utilization,
    ),
)


def request_set_fingerprint(request_ids: tuple[str, ...]) -> str:
    """Order-independent checksum over a request set's ids -- the same set of
    requests fingerprints identically regardless of iteration order."""
    ordered = sorted(str(r) for r in request_ids)
    return hashlib.sha256(
        canonical_json({"request_ids": ordered}).encode("utf-8")
    ).hexdigest()


def _request_ids(s: ScheduleOutcomeSet) -> list[str]:
    ids = [str(o.request_id) for o in s.outcomes]
    if len(set(ids)) != len(ids):
        raise ReplayError(
            f"schedule '{s.schedule_label}' has more than one outcome for the "
            "same request_id; expected exactly one outcome per request"
        )
    return ids


def _replay_id(
    request_set_sha256: str,
    replay_instant: UtcDateTime,
    baseline_label: str,
    milexium_label: str,
) -> str:
    payload = {
        "replay_version": REPLAY_VERSION,
        "request_set_sha256": request_set_sha256,
        "replay_instant": replay_instant.isoformat(),
        "baseline_label": baseline_label,
        "milexium_label": milexium_label,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _favors_milexium(delta: float | None, higher_is_better: bool) -> bool | None:
    if delta is None or delta == 0:
        return None
    return (delta > 0) == higher_is_better


def compare_schedules(
    baseline: ScheduleOutcomeSet,
    milexium: ScheduleOutcomeSet,
    *,
    replay_instant: UtcDateTime,
    request_set_label: str,
) -> ReplayComparison:
    """Compare two schedules' outcomes over the same request set.

    Raises ReplayError unless both sets cover exactly the same request ids (the
    comparison is only meaningful over the identical day of requests). Returns a
    ReplayComparison whose deltas are Milexium minus baseline -- a *modelled*
    comparison, never causal proof of savings, and never a dollar figure.
    """
    baseline_ids = _request_ids(baseline)
    milexium_ids = _request_ids(milexium)
    if set(baseline_ids) != set(milexium_ids):
        raise ReplayError(
            "baseline and Milexium outcome sets must cover the same request "
            f"set: {len(set(baseline_ids) ^ set(milexium_ids))} request ids differ"
        )

    request_set_sha256 = request_set_fingerprint(tuple(baseline_ids))

    metrics: list[MetricDelta] = []
    for spec in METRIC_SPECS:
        b_val = spec.compute(baseline)
        m_val = spec.compute(milexium)
        delta = None if b_val is None or m_val is None else m_val - b_val
        metrics.append(
            MetricDelta(
                name=spec.name,
                unit=spec.unit,
                higher_is_better=spec.higher_is_better,
                basis=spec.basis,
                baseline=b_val,
                milexium=m_val,
                delta=delta,
                favors_milexium=_favors_milexium(delta, spec.higher_is_better),
            )
        )

    manifest = ReplayManifest(
        replay_version=REPLAY_VERSION,
        replay_id=_replay_id(
            request_set_sha256, replay_instant, baseline.schedule_label,
            milexium.schedule_label,
        ),
        request_set_label=request_set_label,
        request_set_sha256=request_set_sha256,
        request_count=len(baseline_ids),
        replay_instant=replay_instant,
        baseline_label=baseline.schedule_label,
        baseline_provenance=baseline.provenance,
        milexium_label=milexium.schedule_label,
        milexium_provenance=milexium.provenance,
        metric_definitions=tuple(spec.definition for spec in METRIC_SPECS),
        note=MODELLED_COMPARISON_NOTE,
    )

    is_modelled = "simulated" in (baseline.provenance, milexium.provenance)
    return ReplayComparison(
        manifest=manifest,
        metrics=tuple(metrics),
        is_modelled_comparison=is_modelled,
    )
