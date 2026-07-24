"""Champion / challenger / canary promotion controller (Program D, v0.1 slice).

`ADR-0010` / `packages/core/model_registry.py` give each task a single champion
pointer that `promote()` overwrites without checking the new version is better.
`blueprint/05-core-model-runtime-and-forecast.md`'s "Champion/challenger"
section describes the fuller lifecycle: several challengers evaluated against
the incumbent, an optional canary serving a fraction of traffic, and promotion
only through an explicit gate with recorded rollback. This module is that
lifecycle, v0.1.

It COMPOSES `ModelRegistry` rather than mutating it: the registry stays the
catalog of what `ModelVersion`s exist (read-only here -- `get()` /
`list_for_task()` only), while this controller owns the richer role state and
the promotion ledger. It never calls `registry.register()` or
`registry.promote()`; the registry's own single-pointer champion is left
untouched so the two mechanisms do not fight over one piece of state.

The gate invariant: a challenger becomes champion ONLY through
`evaluate_and_maybe_promote`, which records a `PromotionDecision` (the metric
comparison plus the verdict). A canary carries a traffic fraction in [0, 1) --
strictly below 1, because a canary that took all traffic would just be the
champion. Demotions and rollbacks are recorded too.

In-memory reference implementation only, matching the `ModelRegistry` /
`HashChainAppender` pattern. Status: Demonstrated on the conformance suite, not
operator-Validated.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from packages.canonical.ids import ModelVersionId
from packages.canonical.time import UtcDateTime, _require_utc
from packages.core.model_registry import ModelRegistry


class PromotionError(ValueError):
    """Base for a rejected promotion-controller operation."""


class RoleAssignmentError(PromotionError):
    """Raised when a version cannot take the requested role (not registered for
    the task, or not an eligible canary)."""


class TrafficFractionError(PromotionError):
    """Raised when a canary traffic fraction is not in [0, 1)."""


class NoRollbackTargetError(PromotionError):
    """Raised when a rollback is requested but no prior champion exists."""


class PromotionDecision(BaseModel):
    """The recorded verdict of one evaluated promotion gate.

    Captures exactly what was compared and why the challenger did or did not
    become champion, so "why was this promoted" is answerable after the fact --
    the promotion analogue of the decision ledger's "why not the alternatives".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task: str
    challenger_id: ModelVersionId
    incumbent_id: ModelVersionId | None = Field(
        description="The champion the challenger was measured against; None for the first champion."
    )
    metric_name: str
    challenger_metric: float
    incumbent_metric: float | None = Field(
        description="The incumbent's metric on the same measurement; None when there was no incumbent."
    )
    higher_is_better: bool
    min_improvement: float
    margin: float | None = Field(
        description="Signed improvement of challenger over incumbent, in the better direction; None with no incumbent."
    )
    promoted: bool
    decided_at: UtcDateTime
    rationale: str


class RollbackRecord(BaseModel):
    """A recorded demotion of the current champion back to a prior one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task: str
    from_champion_id: ModelVersionId
    to_champion_id: ModelVersionId
    decided_at: UtcDateTime
    reason: str


class Rollout(BaseModel):
    """An immutable snapshot of a task's serving roles."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task: str
    champion_id: ModelVersionId | None
    challenger_ids: tuple[ModelVersionId, ...]
    canary_id: ModelVersionId | None
    canary_fraction: float | None


class PromotionController:
    """Champion/challenger/canary lifecycle over a read-only `ModelRegistry`."""

    def __init__(self, registry: ModelRegistry) -> None:
        self._registry = registry
        self._champion: dict[str, ModelVersionId] = {}
        # Prior champions, most-recent last: the rollback stack.
        self._champion_history: dict[str, list[ModelVersionId]] = {}
        self._challengers: dict[str, list[ModelVersionId]] = {}
        self._canary: dict[str, tuple[ModelVersionId, float]] = {}
        self._decisions: list[PromotionDecision] = []
        self._rollbacks: list[RollbackRecord] = []

    # -- validation helpers ------------------------------------------------- #
    def _require_registered_for_task(
        self, task: str, model_version_id: ModelVersionId
    ) -> None:
        """The version must exist in the composed registry AND be for `task`
        (Program D resolves models per task first -- a version for another task
        can never serve this one)."""
        model_version = self._registry.get(model_version_id)  # raises if unknown
        if model_version.task != task:
            raise RoleAssignmentError(
                f"model version {model_version_id!r} is for task "
                f"{model_version.task!r}, not {task!r}"
            )

    # -- challengers -------------------------------------------------------- #
    def register_challenger(self, task: str, model_version_id: ModelVersionId) -> None:
        """Enroll a registered version as a challenger for `task`. Idempotent;
        the current champion is not also a challenger."""
        self._require_registered_for_task(task, model_version_id)
        if model_version_id == self._champion.get(task):
            raise RoleAssignmentError(
                f"{model_version_id!r} is already champion for {task!r}"
            )
        challengers = self._challengers.setdefault(task, [])
        if model_version_id not in challengers:
            challengers.append(model_version_id)

    def demote_challenger(self, task: str, model_version_id: ModelVersionId) -> None:
        """Remove a challenger (and drop it as canary if it was serving one)."""
        challengers = self._challengers.get(task, [])
        if model_version_id not in challengers:
            raise RoleAssignmentError(
                f"{model_version_id!r} is not a challenger for {task!r}"
            )
        challengers.remove(model_version_id)
        canary = self._canary.get(task)
        if canary is not None and canary[0] == model_version_id:
            del self._canary[task]

    # -- canary ------------------------------------------------------------- #
    def set_canary(
        self, task: str, model_version_id: ModelVersionId, traffic_fraction: float
    ) -> None:
        """Route `traffic_fraction` of traffic to a challenger as a canary.
        Fraction must be in [0, 1): 0 stages a canary that takes no live
        traffic yet; it can never be 1 (that would be the champion)."""
        fraction = float(traffic_fraction)
        if not (0.0 <= fraction < 1.0):
            raise TrafficFractionError(
                f"canary traffic fraction must be in [0, 1), got {fraction!r}"
            )
        if model_version_id not in self._challengers.get(task, []):
            raise RoleAssignmentError(
                f"canary {model_version_id!r} must first be a challenger for {task!r}"
            )
        self._canary[task] = (model_version_id, fraction)

    def clear_canary(self, task: str) -> None:
        self._canary.pop(task, None)

    def route(self, task: str, roll: float) -> ModelVersionId | None:
        """Which version serves a request whose routing draw is `roll` in
        [0, 1): the canary when `roll < canary_fraction`, otherwise the
        champion. Deterministic given `roll`; the caller owns the RNG."""
        if not (0.0 <= roll < 1.0):
            raise TrafficFractionError(f"routing roll must be in [0, 1), got {roll!r}")
        canary = self._canary.get(task)
        if canary is not None and roll < canary[1]:
            return canary[0]
        return self._champion.get(task)

    # -- the promotion gate ------------------------------------------------- #
    def evaluate_and_maybe_promote(
        self,
        task: str,
        challenger_id: ModelVersionId,
        *,
        metric_name: str,
        challenger_metric: float,
        incumbent_metric: float | None = None,
        higher_is_better: bool = True,
        min_improvement: float = 0.0,
        decided_at: datetime,
    ) -> PromotionDecision:
        """The ONLY path from challenger to champion. Records and returns a
        `PromotionDecision`.

        With no incumbent the challenger is installed as the first champion
        (promoted, no comparison). With an incumbent the challenger is promoted
        iff it beats the incumbent, in the `higher_is_better` direction, by at
        least `min_improvement`. On promotion the outgoing champion is pushed on
        the rollback stack and the challenger leaves the challenger pool.
        """
        _require_utc(decided_at)
        if min_improvement < 0.0:
            raise PromotionError("min_improvement must be non-negative")
        if challenger_id not in self._challengers.get(task, []):
            raise RoleAssignmentError(
                f"{challenger_id!r} is not a challenger for {task!r}; register it first"
            )
        incumbent_id = self._champion.get(task)

        if incumbent_id is None:
            decision = PromotionDecision(
                task=task,
                challenger_id=challenger_id,
                incumbent_id=None,
                metric_name=metric_name,
                challenger_metric=float(challenger_metric),
                incumbent_metric=None,
                higher_is_better=higher_is_better,
                min_improvement=float(min_improvement),
                margin=None,
                promoted=True,
                decided_at=decided_at,
                rationale="no incumbent champion -- challenger installed as first champion",
            )
            self._apply_promotion(task, challenger_id)
            self._decisions.append(decision)
            return decision

        if incumbent_metric is None:
            raise PromotionError(
                "incumbent_metric is required to gate a challenger against the current champion"
            )
        margin = (
            challenger_metric - incumbent_metric
            if higher_is_better
            else incumbent_metric - challenger_metric
        )
        promoted = margin >= min_improvement and margin > 0.0
        if promoted:
            rationale = (
                f"challenger beats champion on {metric_name} by {margin:.6g} "
                f">= min_improvement {min_improvement:.6g}"
            )
        else:
            rationale = (
                f"challenger does not clear the gate on {metric_name}: margin "
                f"{margin:.6g} < min_improvement {min_improvement:.6g} (or no gain)"
            )
        decision = PromotionDecision(
            task=task,
            challenger_id=challenger_id,
            incumbent_id=incumbent_id,
            metric_name=metric_name,
            challenger_metric=float(challenger_metric),
            incumbent_metric=float(incumbent_metric),
            higher_is_better=higher_is_better,
            min_improvement=float(min_improvement),
            margin=float(margin),
            promoted=promoted,
            decided_at=decided_at,
            rationale=rationale,
        )
        if promoted:
            self._apply_promotion(task, challenger_id)
        self._decisions.append(decision)
        return decision

    def _apply_promotion(self, task: str, challenger_id: ModelVersionId) -> None:
        outgoing = self._champion.get(task)
        if outgoing is not None:
            self._champion_history.setdefault(task, []).append(outgoing)
        self._champion[task] = challenger_id
        challengers = self._challengers.get(task, [])
        if challenger_id in challengers:
            challengers.remove(challenger_id)
        canary = self._canary.get(task)
        if canary is not None and canary[0] == challenger_id:
            del self._canary[task]

    # -- rollback ----------------------------------------------------------- #
    def rollback(self, task: str, *, decided_at: datetime, reason: str) -> RollbackRecord:
        """Demote the current champion back to the previous one, recorded. The
        demoted champion rejoins the challenger pool so it can be re-evaluated;
        raises if there is no prior champion to fall back to."""
        _require_utc(decided_at)
        history = self._champion_history.get(task, [])
        current = self._champion.get(task)
        if current is None or not history:
            raise NoRollbackTargetError(
                f"no prior champion to roll back to for {task!r}"
            )
        previous = history.pop()
        self._champion[task] = previous
        challengers = self._challengers.setdefault(task, [])
        if current not in challengers:
            challengers.append(current)
        record = RollbackRecord(
            task=task,
            from_champion_id=current,
            to_champion_id=previous,
            decided_at=decided_at,
            reason=reason,
        )
        self._rollbacks.append(record)
        return record

    # -- read-only views ---------------------------------------------------- #
    def champion(self, task: str) -> ModelVersionId | None:
        return self._champion.get(task)

    def challengers(self, task: str) -> tuple[ModelVersionId, ...]:
        return tuple(self._challengers.get(task, []))

    def canary(self, task: str) -> tuple[ModelVersionId, float] | None:
        return self._canary.get(task)

    def rollout(self, task: str) -> Rollout:
        canary = self._canary.get(task)
        return Rollout(
            task=task,
            champion_id=self._champion.get(task),
            challenger_ids=tuple(self._challengers.get(task, [])),
            canary_id=canary[0] if canary is not None else None,
            canary_fraction=canary[1] if canary is not None else None,
        )

    def decisions(self) -> tuple[PromotionDecision, ...]:
        return tuple(self._decisions)

    def rollbacks(self) -> tuple[RollbackRecord, ...]:
        return tuple(self._rollbacks)
