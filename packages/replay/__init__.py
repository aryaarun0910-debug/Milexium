"""Program H (partial): historical replay + baseline-vs-Milexium comparison.

Two pieces, both v0.1:

- packages.replay.replay -- the integrity core. Reconstructs "what was known as
  of the replay instant" via the canonical RequestTimes.known_as_of cutoff, and
  raises ReplayError on any input that leaks a fact from the future.
- packages.replay.comparison -- a per-metric baseline-vs-Milexium comparison
  over the same request set, returned as a structured, auditable ReplayComparison
  pinned by a ReplayManifest.

Framing is non-negotiable and single-sourced in MODELLED_COMPARISON_NOTE
(blueprint/01-north-star-and-boundaries.md): a replay is a *modelled comparison,
not causal proof of savings*, and no monetary figure is derived. Not centrally
wired into any other package's __init__.py -- the orchestrator decides where, if
anywhere, this is re-exported.
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
]

CONTRACT_VERSION = "0.1.0"
