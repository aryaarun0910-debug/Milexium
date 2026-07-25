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

`PromotionController` is the in-memory reference implementation, matching the
`ModelRegistry` / `HashChainAppender` pattern.
`PersistentPromotionController` (below) is the same contract over a real
database: ADR-0034 shipped the reference backend only, so a design partner's
promotion decisions, serving roles and rollback history vanished on a process
restart -- and a promotion ledger that does not survive a restart is not an
audit trail. Both engines run `packages/core/sql/core_v0_1.sql`; see
`packages/core/feature_store.py` for the `CoreDatabase` adapter and why the
persistence plumbing lives there.

Status: Demonstrated on the conformance suite, not operator-Validated.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from packages.canonical.ids import ModelVersionId
from packages.canonical.time import UtcDateTime, _require_utc
from packages.core.feature_store import CoreDatabase, _iso_utc
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


def _require_registered_for_task(
    registry: ModelRegistry, task: str, model_version_id: ModelVersionId
) -> None:
    """The version must exist in the composed registry AND be for `task`
    (Program D resolves models per task first -- a version for another task can
    never serve this one).

    Module-level so the in-memory and persistent controllers cannot disagree
    about what "eligible for this task" means.
    """
    model_version = registry.get(model_version_id)  # raises if unknown
    if model_version.task != task:
        raise RoleAssignmentError(
            f"model version {model_version_id!r} is for task "
            f"{model_version.task!r}, not {task!r}"
        )


def _evaluate_gate(
    *,
    task: str,
    challenger_id: ModelVersionId,
    incumbent_id: ModelVersionId | None,
    metric_name: str,
    challenger_metric: float,
    incumbent_metric: float | None,
    higher_is_better: bool,
    min_improvement: float,
    decided_at: datetime,
) -> PromotionDecision:
    """The verdict itself: compare, and record what was compared and why.

    PURE -- it reads no state and writes none, it just turns a comparison into a
    `PromotionDecision`. Both the in-memory and the persistent controller call
    this one function, so persistence cannot quietly change what the gate
    decides; only where the verdict is stored.

    With no incumbent the challenger is the first champion (promoted, no
    comparison). With an incumbent it is promoted iff it beats the incumbent, in
    the `higher_is_better` direction, by at least `min_improvement`.
    """
    if incumbent_id is None:
        return PromotionDecision(
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
    return PromotionDecision(
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
        _require_registered_for_task(self._registry, task, model_version_id)

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
        decision = _evaluate_gate(
            task=task,
            challenger_id=challenger_id,
            incumbent_id=self._champion.get(task),
            metric_name=metric_name,
            challenger_metric=challenger_metric,
            incumbent_metric=incumbent_metric,
            higher_is_better=higher_is_better,
            min_improvement=min_improvement,
            decided_at=decided_at,
        )
        if decision.promoted:
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


# --------------------------------------------------------------------------- #
# Persistent backend
# --------------------------------------------------------------------------- #
class PersistentPromotionController:
    """Durable champion/challenger/canary lifecycle: `PromotionController`'s
    contract, backed by the promotion tables in
    `packages/core/sql/core_v0_1.sql`.

    Method-for-method identical to the in-memory reference (proved structurally
    by `test_core_persistence.py`), and it decides identically: the verdict
    comes from the same pure `_evaluate_gate`, and eligibility from the same
    `_require_registered_for_task`. Only WHERE the state lives changes.

    It COMPOSES `ModelRegistry` read-only, exactly as the in-memory controller
    does -- the registry's own ADR-0010 single-pointer champion is still never
    touched, so the two mechanisms do not fight over one piece of state. Note
    the asymmetry this creates and which this class does NOT resolve: the
    controller's roles now survive a restart, the registry's catalog does not.
    A caller must re-register its `ModelVersion`s on startup before a restored
    controller can validate them.

    Two ledgers and three role tables. `promotion_decisions` and
    `promotion_rollbacks` are append-only and globally ordered by their sequence
    columns -- an audit trail, so a REJECTED challenger is recorded exactly as
    durably as a promoted one. `promotion_champions`,
    `promotion_champion_history` and `promotion_challengers` /
    `promotion_canaries` are the mutable present: who serves right now.

    Every state change and the ledger row that explains it are written in ONE
    transaction and committed together, so a crash can never leave a champion
    who was promoted by no recorded decision, nor a decision that claims a
    promotion which did not happen.
    """

    def __init__(self, registry: ModelRegistry, database: CoreDatabase) -> None:
        self._registry = registry
        self._db = database

    # -- state reads (the persistent analogue of the in-memory dicts) -------- #
    def _champion_id(self, task: str) -> ModelVersionId | None:
        rows = self._db.query(
            "SELECT champion_id FROM promotion_champions WHERE task = ?", (task,)
        )
        return ModelVersionId(rows[0][0]) if rows else None

    def _challenger_ids(self, task: str) -> list[ModelVersionId]:
        return [
            ModelVersionId(row[0])
            for row in self._db.query(
                "SELECT model_version_id FROM promotion_challengers "
                "WHERE task = ? ORDER BY enrol_sequence",
                (task,),
            )
        ]

    def _canary_row(self, task: str) -> tuple[ModelVersionId, float] | None:
        rows = self._db.query(
            "SELECT model_version_id, traffic_fraction FROM promotion_canaries "
            "WHERE task = ?",
            (task,),
        )
        return (ModelVersionId(rows[0][0]), float(rows[0][1])) if rows else None

    def _next(self, statement: str, params: tuple = ()) -> int:
        """Next value of an application-assigned sequence column. Portable
        (COALESCE(MAX(...), 0) + 1) rather than SERIAL/AUTOINCREMENT, whose
        spellings differ per engine -- see core_v0_1.sql."""
        return int(self._db.query(statement, params)[0][0])

    # -- challengers -------------------------------------------------------- #
    def register_challenger(self, task: str, model_version_id: ModelVersionId) -> None:
        """Enroll a registered version as a challenger for `task`. Idempotent;
        the current champion is not also a challenger."""
        _require_registered_for_task(self._registry, task, model_version_id)
        if model_version_id == self._champion_id(task):
            raise RoleAssignmentError(
                f"{model_version_id!r} is already champion for {task!r}"
            )
        if model_version_id in self._challenger_ids(task):
            return
        self._db.execute(
            "INSERT INTO promotion_challengers (task, model_version_id, enrol_sequence) "
            "VALUES (?, ?, ?)",
            (
                task,
                str(model_version_id),
                self._next(
                    "SELECT COALESCE(MAX(enrol_sequence), 0) + 1 "
                    "FROM promotion_challengers WHERE task = ?",
                    (task,),
                ),
            ),
        )
        self._db.commit()

    def demote_challenger(self, task: str, model_version_id: ModelVersionId) -> None:
        """Remove a challenger (and drop it as canary if it was serving one)."""
        if model_version_id not in self._challenger_ids(task):
            raise RoleAssignmentError(
                f"{model_version_id!r} is not a challenger for {task!r}"
            )
        self._db.execute(
            "DELETE FROM promotion_challengers WHERE task = ? AND model_version_id = ?",
            (task, str(model_version_id)),
        )
        self._db.execute(
            "DELETE FROM promotion_canaries WHERE task = ? AND model_version_id = ?",
            (task, str(model_version_id)),
        )
        self._db.commit()

    # -- canary ------------------------------------------------------------- #
    def set_canary(
        self, task: str, model_version_id: ModelVersionId, traffic_fraction: float
    ) -> None:
        """Route `traffic_fraction` of traffic to a challenger as a canary.
        Fraction must be in [0, 1): 0 stages a canary that takes no live
        traffic yet; it can never be 1 (that would be the champion).

        The [0, 1) rule is checked here AND restated as a CHECK constraint on
        `promotion_canaries`, so a fraction of 1 cannot be stored even by a
        writer that bypassed this method."""
        fraction = float(traffic_fraction)
        if not (0.0 <= fraction < 1.0):
            raise TrafficFractionError(
                f"canary traffic fraction must be in [0, 1), got {fraction!r}"
            )
        if model_version_id not in self._challenger_ids(task):
            raise RoleAssignmentError(
                f"canary {model_version_id!r} must first be a challenger for {task!r}"
            )
        # DELETE + INSERT rather than an upsert: ON CONFLICT is spelled
        # compatibly on both engines but is a later addition to each, and the
        # two statements are unambiguous in the portable subset (ADR-0002).
        self._db.execute("DELETE FROM promotion_canaries WHERE task = ?", (task,))
        self._db.execute(
            "INSERT INTO promotion_canaries (task, model_version_id, traffic_fraction) "
            "VALUES (?, ?, ?)",
            (task, str(model_version_id), fraction),
        )
        self._db.commit()

    def clear_canary(self, task: str) -> None:
        self._db.execute("DELETE FROM promotion_canaries WHERE task = ?", (task,))
        self._db.commit()

    def route(self, task: str, roll: float) -> ModelVersionId | None:
        """Which version serves a request whose routing draw is `roll` in
        [0, 1): the canary when `roll < canary_fraction`, otherwise the
        champion. Deterministic given `roll`; the caller owns the RNG."""
        if not (0.0 <= roll < 1.0):
            raise TrafficFractionError(f"routing roll must be in [0, 1), got {roll!r}")
        canary = self._canary_row(task)
        if canary is not None and roll < canary[1]:
            return canary[0]
        return self._champion_id(task)

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

        The verdict is `_evaluate_gate`'s -- the same function the in-memory
        controller calls. The role change (if any) and the ledger row are
        committed in a single transaction.
        """
        _require_utc(decided_at)
        if min_improvement < 0.0:
            raise PromotionError("min_improvement must be non-negative")
        if challenger_id not in self._challenger_ids(task):
            raise RoleAssignmentError(
                f"{challenger_id!r} is not a challenger for {task!r}; register it first"
            )
        decision = _evaluate_gate(
            task=task,
            challenger_id=challenger_id,
            incumbent_id=self._champion_id(task),
            metric_name=metric_name,
            challenger_metric=challenger_metric,
            incumbent_metric=incumbent_metric,
            higher_is_better=higher_is_better,
            min_improvement=min_improvement,
            decided_at=decided_at,
        )
        if decision.promoted:
            self._apply_promotion(task, challenger_id)
        self._record_decision(decision)
        self._db.commit()
        return decision

    def _apply_promotion(self, task: str, challenger_id: ModelVersionId) -> None:
        """Install `challenger_id` as champion. Uncommitted -- the caller commits
        it together with the decision that authorised it."""
        outgoing = self._champion_id(task)
        if outgoing is not None:
            self._db.execute(
                "INSERT INTO promotion_champion_history (task, stack_position, champion_id) "
                "VALUES (?, ?, ?)",
                (
                    task,
                    self._next(
                        "SELECT COALESCE(MAX(stack_position), 0) + 1 "
                        "FROM promotion_champion_history WHERE task = ?",
                        (task,),
                    ),
                    str(outgoing),
                ),
            )
        self._db.execute("DELETE FROM promotion_champions WHERE task = ?", (task,))
        self._db.execute(
            "INSERT INTO promotion_champions (task, champion_id) VALUES (?, ?)",
            (task, str(challenger_id)),
        )
        self._db.execute(
            "DELETE FROM promotion_challengers WHERE task = ? AND model_version_id = ?",
            (task, str(challenger_id)),
        )
        self._db.execute(
            "DELETE FROM promotion_canaries WHERE task = ? AND model_version_id = ?",
            (task, str(challenger_id)),
        )

    def _record_decision(self, decision: PromotionDecision) -> None:
        """Append one row to the promotion ledger. Uncommitted; append-only --
        there is no UPDATE or DELETE against `promotion_decisions` anywhere in
        this module, on purpose."""
        self._db.execute(
            "INSERT INTO promotion_decisions (decision_sequence, task, challenger_id, "
            "incumbent_id, metric_name, challenger_metric, incumbent_metric, "
            "higher_is_better, min_improvement, margin, promoted, decided_at, rationale) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self._next(
                    "SELECT COALESCE(MAX(decision_sequence), 0) + 1 FROM promotion_decisions"
                ),
                decision.task,
                str(decision.challenger_id),
                str(decision.incumbent_id) if decision.incumbent_id is not None else None,
                decision.metric_name,
                decision.challenger_metric,
                decision.incumbent_metric,
                1 if decision.higher_is_better else 0,
                decision.min_improvement,
                decision.margin,
                1 if decision.promoted else 0,
                _iso_utc(decision.decided_at),
                decision.rationale,
            ),
        )

    # -- rollback ----------------------------------------------------------- #
    def rollback(
        self, task: str, *, decided_at: datetime, reason: str
    ) -> RollbackRecord:
        """Demote the current champion back to the previous one, recorded. The
        demoted champion rejoins the challenger pool so it can be re-evaluated;
        raises if there is no prior champion to fall back to.

        The pop of the history stack, the champion swap, the demoted champion's
        re-enrolment and the rollback record are one transaction."""
        _require_utc(decided_at)
        current = self._champion_id(task)
        top = self._db.query(
            "SELECT stack_position, champion_id FROM promotion_champion_history "
            "WHERE task = ? ORDER BY stack_position DESC LIMIT 1",
            (task,),
        )
        if current is None or not top:
            raise NoRollbackTargetError(
                f"no prior champion to roll back to for {task!r}"
            )
        stack_position, previous_raw = top[0]
        previous = ModelVersionId(previous_raw)

        self._db.execute(
            "DELETE FROM promotion_champion_history WHERE task = ? AND stack_position = ?",
            (task, int(stack_position)),
        )
        self._db.execute("DELETE FROM promotion_champions WHERE task = ?", (task,))
        self._db.execute(
            "INSERT INTO promotion_champions (task, champion_id) VALUES (?, ?)",
            (task, str(previous)),
        )
        if current not in self._challenger_ids(task):
            self._db.execute(
                "INSERT INTO promotion_challengers (task, model_version_id, enrol_sequence) "
                "VALUES (?, ?, ?)",
                (
                    task,
                    str(current),
                    self._next(
                        "SELECT COALESCE(MAX(enrol_sequence), 0) + 1 "
                        "FROM promotion_challengers WHERE task = ?",
                        (task,),
                    ),
                ),
            )
        record = RollbackRecord(
            task=task,
            from_champion_id=current,
            to_champion_id=previous,
            decided_at=decided_at,
            reason=reason,
        )
        self._db.execute(
            "INSERT INTO promotion_rollbacks (rollback_sequence, task, from_champion_id, "
            "to_champion_id, decided_at, reason) VALUES (?, ?, ?, ?, ?, ?)",
            (
                self._next(
                    "SELECT COALESCE(MAX(rollback_sequence), 0) + 1 FROM promotion_rollbacks"
                ),
                record.task,
                str(record.from_champion_id),
                str(record.to_champion_id),
                _iso_utc(record.decided_at),
                record.reason,
            ),
        )
        self._db.commit()
        return record

    # -- read-only views ---------------------------------------------------- #
    def champion(self, task: str) -> ModelVersionId | None:
        return self._champion_id(task)

    def challengers(self, task: str) -> tuple[ModelVersionId, ...]:
        return tuple(self._challenger_ids(task))

    def canary(self, task: str) -> tuple[ModelVersionId, float] | None:
        return self._canary_row(task)

    def rollout(self, task: str) -> Rollout:
        canary = self._canary_row(task)
        return Rollout(
            task=task,
            champion_id=self._champion_id(task),
            challenger_ids=tuple(self._challenger_ids(task)),
            canary_id=canary[0] if canary is not None else None,
            canary_fraction=canary[1] if canary is not None else None,
        )

    def decisions(self) -> tuple[PromotionDecision, ...]:
        """The whole ledger, in decision order across every task -- the same
        global ordering the in-memory controller's append-ordered list gives.
        Ordering and completeness are the audit-trail claim: ORDER BY the
        application-assigned `decision_sequence`, never by an engine's row
        order."""
        return tuple(
            PromotionDecision(
                task=row[0],
                challenger_id=ModelVersionId(row[1]),
                incumbent_id=ModelVersionId(row[2]) if row[2] is not None else None,
                metric_name=row[3],
                challenger_metric=float(row[4]),
                incumbent_metric=float(row[5]) if row[5] is not None else None,
                higher_is_better=bool(row[6]),
                min_improvement=float(row[7]),
                margin=float(row[8]) if row[8] is not None else None,
                promoted=bool(row[9]),
                decided_at=datetime.fromisoformat(row[10]),
                rationale=row[11],
            )
            for row in self._db.query(
                "SELECT task, challenger_id, incumbent_id, metric_name, challenger_metric, "
                "incumbent_metric, higher_is_better, min_improvement, margin, promoted, "
                "decided_at, rationale FROM promotion_decisions ORDER BY decision_sequence"
            )
        )

    def rollbacks(self) -> tuple[RollbackRecord, ...]:
        return tuple(
            RollbackRecord(
                task=row[0],
                from_champion_id=ModelVersionId(row[1]),
                to_champion_id=ModelVersionId(row[2]),
                decided_at=datetime.fromisoformat(row[3]),
                reason=row[4],
            )
            for row in self._db.query(
                "SELECT task, from_champion_id, to_champion_id, decided_at, reason "
                "FROM promotion_rollbacks ORDER BY rollback_sequence"
            )
        )
