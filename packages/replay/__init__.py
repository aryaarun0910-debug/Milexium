"""Program H (partial): historical replay, baseline comparison, deadhead teardown.

Three pieces, all v0.1:

- packages.replay.replay -- the integrity core. Reconstructs "what was known as
  of the replay instant" via the canonical RequestTimes.known_as_of cutoff, and
  raises ReplayError on any input that leaks a fact from the future.
- packages.replay.comparison -- a per-metric baseline-vs-Milexium comparison
  over the same request set, returned as a structured, auditable ReplayComparison
  pinned by a ReplayManifest.
- packages.replay.teardown -- localises non-revenue (empty) vehicle time from an
  operator's trip-level records to specific hours, days and runs, and values it
  at their own cost per vehicle-hour. Reuses the comparison module's framing
  rather than restating it.

Framing is non-negotiable and single-sourced in MODELLED_COMPARISON_NOTE
(blueprint/01-north-star-and-boundaries.md): a replay is a *modelled comparison,
not causal proof of savings*. The comparison derives no monetary figure at all;
the teardown's money figures are the accounting value of empty time at the
operator's own rate, hedged by FIXED_COST_HEDGE and never a guaranteed saving.
Not centrally wired into any other package's __init__.py -- the orchestrator
decides where, if anywhere, this is re-exported.
"""

from packages.replay.replay import (
    ReplayError,
    assert_requests_known_as_of,
    known_as_of_request,
    replay_requests_as_of,
    verify_no_future_leak,
)
from packages.replay.comparison import (
    METRIC_SPECS,
    MODELLED_COMPARISON_NOTE,
    REPLAY_VERSION,
    MetricBasis,
    MetricDelta,
    OutcomeProvenance,
    ReplayComparison,
    ReplayManifest,
    ScheduleOutcomeSet,
    compare_schedules,
    request_set_fingerprint,
)
from packages.replay.teardown import (
    DEADHEAD_TEARDOWN_NOTE,
    DEFAULT_REDUCTION_FRACTION,
    FIXED_COST_HEDGE,
    MAX_SEGMENT_HOURS,
    TEARDOWN_VERSION,
    CostBasis,
    CostEnvelope,
    DataProvenance,
    DeadheadTeardown,
    InputRecord,
    MethodStep,
    RunContribution,
    SegmentKind,
    TeardownError,
    TeardownManifest,
    TimeBucket,
    VehicleSegment,
    segment_set_fingerprint,
    teardown_deadhead,
)

__all__ = [
    "ReplayError",
    "assert_requests_known_as_of",
    "known_as_of_request",
    "replay_requests_as_of",
    "verify_no_future_leak",
    "METRIC_SPECS",
    "MODELLED_COMPARISON_NOTE",
    "REPLAY_VERSION",
    "MetricBasis",
    "MetricDelta",
    "OutcomeProvenance",
    "ReplayComparison",
    "ReplayManifest",
    "ScheduleOutcomeSet",
    "compare_schedules",
    "request_set_fingerprint",
    "DEADHEAD_TEARDOWN_NOTE",
    "DEFAULT_REDUCTION_FRACTION",
    "FIXED_COST_HEDGE",
    "MAX_SEGMENT_HOURS",
    "TEARDOWN_VERSION",
    "CostBasis",
    "CostEnvelope",
    "DataProvenance",
    "DeadheadTeardown",
    "InputRecord",
    "MethodStep",
    "RunContribution",
    "SegmentKind",
    "TeardownError",
    "TeardownManifest",
    "TimeBucket",
    "VehicleSegment",
    "segment_set_fingerprint",
    "teardown_deadhead",
]

CONTRACT_VERSION = "0.1.0"
