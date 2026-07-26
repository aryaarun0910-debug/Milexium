"""Typed, permissioned ACTIONS -- the only way operational state may change.

THE CLAIM THIS MODULE MAKES, AND WHAT MAKES IT MORE THAN A CONVENTION.
"Actions are typed operations, never arbitrary database writes" is easy to write
in a design document and worthless unless the arbitrary write is ABSENT rather
than discouraged. Three things make it absent here:

  1. `app/ontology/store.OntologyStore` exposes no method that writes an
     operational effect without an `ActionRecord`. A conformance test enumerates
     the store's public surface and asserts it.
  2. An `ActionRecord` cannot be constructed without an `Authority` holding the
     action's permission (`ACTION_PERMISSIONS`), an input snapshot with its
     content hash, and the alternatives considered. There is no partial
     constructor and no `extra` field to route around one.
  3. The alternatives, the prediction and the verifier verdict are REQUIRED
     shape, not optional metadata. An action recorded without them would be a
     row saying something happened, which is what the repository already has;
     the point of this record is that it says what else could have happened and
     what was expected to follow.

WHAT AN ACTION RECORD IS FOR.
It is the row a learner trains on. The packet's vignette --

    this request arrived at 10:02; this wheelchair-accessible vehicle was
    expected free at 10:41; these three trips were mutually compatible; this
    assignment consumed two likely future pooling opportunities; the dispatcher
    overrode it; the resulting pickup was 14 minutes late

-- is exactly one `ActionRecord` (the assignment), one `Relationship` per
foreclosed pooling opportunity carrying its probability, one further
`ActionRecord` for the override citing the first, and one `ActionOutcome` at
+14 minutes. Every clause has a home, and none of them is a free-text note.

THE ONE INVARIANT MOST LIKELY TO BE ARGUED WITH.
`APPROVE_RECOMMENDATION` and `REJECT_RECOMMENDATION` may not be exercised by an
authority of kind `SYSTEM`. A system approving its own recommendation is not an
approval; it is the recommendation with a second name, and recording it as human
oversight would make an automation-oversight metric structurally meaningless.
An automatic acceptance path is legitimate -- it is just `ASSIGN` under a system
authority, which is what it actually is.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.canonical.time import UtcDateTime
from app.ontology.ids import (
    ActionId,
    ModelVersionId,
    ObjectId,
    OutcomeId,
    PolicyId,
    SnapshotId,
    TenantId,
)
from app.ontology.receipt import ReceiptStamp
from app.ontology.vocab import (
    ACTION_PERMISSIONS,
    ActionKind,
    AuthorityKind,
    ObjectKind,
    Permission,
    ReasonCode,
    VerifierVerdict,
)

__all__ = [
    "Authority",
    "ActionAlternative",
    "ActionPrediction",
    "VerifierResult",
    "ActionRecord",
    "ActionOutcome",
    "PermissionDenied",
    "UnverifiedActionError",
]


class PermissionDenied(PermissionError):
    """An authority attempted an action it does not hold the permission for.

    A `PermissionError`, not a `ValueError`: the request was well-formed and was
    refused. The distinction matters to a caller deciding whether to fix the
    payload or escalate to a human who holds the permission.
    """


class UnverifiedActionError(Exception):
    """An action was taken against a FAILING verifier verdict with no stated
    justification.

    NOT a `ValueError`, for the reason `SnapshotLeakageError` records: pydantic
    would otherwise re-raise it as a `ValidationError` and a test asserting on it
    would pass for any malformed field.

    Overriding a verifier is legitimate -- a dispatcher who can see the vehicle
    knows things the checker does not -- but it is the single most consequential
    thing anyone does in this system, and an unexplained one is indistinguishable
    from the checker being ignored as a matter of routine.
    """


class Authority(BaseModel):
    """Who is acting, and what they are permitted to do.

    Permissions are carried ON the authority rather than looked up from a role
    table at action time, deliberately: an action record must remain explicable
    years later, and a role table is mutable state whose value at the decision
    instant is exactly the kind of thing this package refuses to reconstruct.
    What the actor was permitted to do THEN is part of the episode.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    authority_kind: AuthorityKind
    actor_ref: str = Field(
        min_length=1,
        description="Tokenised actor reference (a service name, a dispatcher token). Never a raw name -- blueprint 10 data minimisation, the same rule ServiceRequest.rider_ref keeps.",
    )
    role: str = Field(
        min_length=1,
        description="The role the permissions were granted under, as the operator names it. Kept for audit; the permissions themselves are what is enforced.",
    )
    permissions: frozenset[Permission] = Field(
        description="What this authority may do, as of the decision instant."
    )
    on_behalf_of: str | None = Field(
        default=None,
        description=(
            "For HUMAN_ON_BEHALF_OF_SYSTEM: the tokenised reference of the system "
            "whose recommendation the human enacted. Required for that kind, "
            "forbidden for the others -- it is what distinguishes 'a person "
            "decided' from 'a person clicked accept'."
        ),
    )

    @model_validator(mode="after")
    def _validate(self) -> "Authority":
        if self.authority_kind is AuthorityKind.HUMAN_ON_BEHALF_OF_SYSTEM:
            if not self.on_behalf_of:
                raise ValueError(
                    "an authority acting on behalf of a system must name it: without "
                    "that, 'was this decision automated?' cannot be answered from the "
                    "record, and it is the question a regulator asks first"
                )
        elif self.on_behalf_of is not None:
            raise ValueError(
                f"on_behalf_of is set but authority_kind is "
                f"{self.authority_kind.value}; only "
                "HUMAN_ON_BEHALF_OF_SYSTEM acts for another party"
            )
        if not self.permissions:
            raise ValueError(
                "an authority with no permissions cannot act; construct it with the "
                "permissions it actually holds rather than an empty set that will "
                "fail at every action"
            )
        return self

    def may(self, action_kind: ActionKind) -> bool:
        return ACTION_PERMISSIONS[action_kind] in self.permissions


class ActionAlternative(BaseModel):
    """One option that was considered and not taken.

    REQUIRED IN THE PLURAL SENSE: an action whose `alternatives` is empty is
    recording that nothing else was considered, which is a real and recordable
    state (a forced assignment with one feasible vehicle) but must be SAID rather
    than defaulted to. `ActionRecord` therefore requires the field explicitly.

    `failed_constraints` reuses `app/canonical/vocab.ReasonCode` -- the
    closed scheduling vocabulary already committed to in the roadmap -- rather
    than a new one, so "why not this vehicle?" means the same thing here as it
    does in `DecisionAlternative` and in an evidence pack.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rank: int = Field(ge=1, description="1 is the option that was taken.")
    candidate_kind: ObjectKind
    candidate_id: ObjectId | None = Field(
        default=None,
        description="The object this option would have used (a vehicle, a run). None where the option was 'do nothing' or 'deny'.",
    )
    feasible: bool
    failed_constraints: tuple[ReasonCode, ...] = ()
    objective_delta: float | None = Field(
        default=None,
        description="How much worse (positive) or better (negative) than the taken option, in the objective's own units. None means NOT EVALUATED -- never 0.0, which would assert equivalence.",
    )

    @model_validator(mode="after")
    def _validate(self) -> "ActionAlternative":
        if not self.feasible and not self.failed_constraints:
            raise ValueError(
                "an infeasible alternative must name at least one failed constraint. "
                "'Infeasible, reason unrecorded' is the answer this record exists to "
                "make impossible"
            )
        if self.feasible and self.failed_constraints:
            raise ValueError(
                "a feasible alternative cannot carry failed constraints"
            )
        return self


class ActionPrediction(BaseModel):
    """What was expected to follow from the action, recorded BEFORE it did.

    Kept separate from `ActionOutcome` for the reason
    `app/canonical/entities.ForecastVintage` keeps predicted and actual
    apart: a prediction stored in the same field as the thing it predicted can be
    overwritten by hindsight, and then no model can ever be scored honestly
    again.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: str = Field(min_length=1, description="What is being predicted, e.g. 'pickup_delay_minutes'.")
    point_estimate: float
    interval_low: float | None = None
    interval_high: float | None = None
    model_version_id: ModelVersionId | None = Field(
        default=None,
        description="The model that produced it, where one did. None means the estimate came from a rule or a human, which is a materially different provenance and is recorded as such rather than as a missing model.",
    )

    @model_validator(mode="after")
    def _validate(self) -> "ActionPrediction":
        lo, hi = self.interval_low, self.interval_high
        if (lo is None) != (hi is None):
            raise ValueError(
                "an interval needs both bounds or neither; a half-interval is not an "
                "uncertainty statement"
            )
        if lo is not None and hi is not None:
            if hi < lo:
                raise ValueError(f"interval [{lo}, {hi}] is inverted")
            if not lo <= self.point_estimate <= hi:
                raise ValueError(
                    f"point estimate {self.point_estimate} lies outside its own "
                    f"interval [{lo}, {hi}]"
                )
        return self


class VerifierResult(BaseModel):
    """What the independent checker said, before the action ran.

    `NOT_RUN` is a verdict, not a null -- see `VerifierVerdict`. An action taken
    without verification is a materially different act from a verified one and
    must not look like a missing column in the training set.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: VerifierVerdict
    verifier_name: str = Field(min_length=1)
    verifier_version: str = Field(min_length=1)
    violated_rules: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate(self) -> "VerifierResult":
        if self.verdict is VerifierVerdict.FAIL and not self.violated_rules:
            raise ValueError(
                "a failing verdict must name the rules it failed; an unexplained "
                "failure cannot be acted on or appealed"
            )
        if self.verdict is VerifierVerdict.PASS and self.violated_rules:
            raise ValueError("a passing verdict cannot name violated rules")
        return self


class ActionRecord(BaseModel):
    """One typed, permissioned operation, with everything needed to learn from it.

    Frozen. An action is asserted once; a change of mind is a FURTHER action
    (`REASSIGN`, `REJECT_RECOMMENDATION`) citing this one, never an edit --
    because the fact that the first decision was taken, on the information then
    available, is itself the thing worth learning from.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: ActionId
    tenant_id: TenantId
    action_kind: ActionKind

    # -- what it acted on ---------------------------------------------------- #
    subject_kind: ObjectKind
    subject_id: ObjectId

    # -- the information set (the whole point) ------------------------------- #
    input_snapshot_id: SnapshotId = Field(
        description="The DecisionSnapshot this action was taken from. REQUIRED, no default: an action with no recorded information set is unauditable and untrainable."
    )
    input_snapshot_hash: str = Field(
        min_length=64,
        max_length=64,
        description=(
            "`DecisionSnapshot.content_hash` at the moment of the decision. Pins "
            "the exact information set, not merely a pointer to a row that could "
            "later be re-derived differently -- and catches a snapshot forged "
            "with `model_copy(update=...)`, which skips pydantic validators."
        ),
    )
    input_snapshot_as_of: UtcDateTime = Field(
        description="The snapshot's decision instant, carried here so `decided_at >= as_of` is checkable from the action alone."
    )

    # -- the policy in force -------------------------------------------------- #
    policy_id: PolicyId
    policy_version: int = Field(ge=1)

    # -- what else was on the table ------------------------------------------- #
    alternatives: tuple[ActionAlternative, ...] = Field(
        description="Options considered. May be empty -- meaning 'nothing else was considered' -- but must be supplied explicitly."
    )
    prediction: ActionPrediction | None = None
    verifier: VerifierResult
    override_justification: str | None = Field(
        default=None,
        description="Required when the verifier verdict is FAIL. Free text on purpose: the reason a human overrode a checker is not drawable from a closed vocabulary, and forcing one would produce a uniform meaningless code.",
    )

    # -- who, and when --------------------------------------------------------- #
    authority: Authority
    decided_at: UtcDateTime = Field(
        description="VALID time: when the decision was taken. Caller-supplied, no default -- a defaulted decision time is a reconstruction."
    )
    receipt: ReceiptStamp = Field(
        description="TRANSACTION time: when Milexium recorded it. Writer-assigned."
    )
    reason_codes: tuple[ReasonCode, ...] = ()

    prev_hash: str | None = None
    hash: str

    @model_validator(mode="after")
    def _validate(self) -> "ActionRecord":
        if not self.authority.may(self.action_kind):
            raise PermissionDenied(
                f"authority {self.authority.actor_ref!r} (role {self.authority.role!r}) "
                f"does not hold {ACTION_PERMISSIONS[self.action_kind].value}, which "
                f"{self.action_kind.value} requires"
            )
        if (
            self.action_kind
            in (ActionKind.APPROVE_RECOMMENDATION, ActionKind.REJECT_RECOMMENDATION)
            and self.authority.authority_kind is AuthorityKind.SYSTEM
        ):
            raise PermissionDenied(
                f"{self.action_kind.value} requires a human authority. A system "
                "approving its own recommendation is the recommendation under a "
                "second name, and recording it as oversight makes every "
                "automation-oversight measure meaningless. An automatic path is a "
                "system ASSIGN, which is what it actually is"
            )
        if self.decided_at < self.input_snapshot_as_of:
            raise ValueError(
                f"decision at {self.decided_at.isoformat()} cites an information set "
                f"as of {self.input_snapshot_as_of.isoformat()}, which is LATER. The "
                "decision would have been taken on facts that had not been admitted "
                "when it was made"
            )
        if self.receipt.receipt_time < self.decided_at:
            raise ValueError(
                f"action received at {self.receipt.receipt_time.isoformat()} claims to "
                f"have been decided at {self.decided_at.isoformat()}, in its own "
                "future"
            )
        if self.verifier.verdict is VerifierVerdict.FAIL and not (
            self.override_justification
        ):
            raise UnverifiedActionError(
                f"{self.action_kind.value} was taken against a FAILING verifier "
                f"({', '.join(self.verifier.violated_rules)}) with no justification"
            )
        ranks = [a.rank for a in self.alternatives]
        if len(set(ranks)) != len(ranks):
            raise ValueError("two alternatives share a rank; the ordering is ambiguous")
        if self.receipt.receipt_sequence == 1:
            if self.prev_hash is not None:
                raise ValueError("the first row in a receipt ledger has no predecessor")
        elif self.prev_hash is None:
            raise ValueError(
                "an action beyond receipt sequence 1 has a null prev_hash: a chain "
                "cannot be silently re-rooted"
            )
        return self

    @property
    def was_automated(self) -> bool:
        """Whether the decision content was machine-produced.

        True for `SYSTEM` and for `HUMAN_ON_BEHALF_OF_SYSTEM` -- a human clicking
        accept on a machine recommendation IS an automated decision with human
        sign-off, and treating it as a human decision is how automation rates get
        under-reported.
        """
        return self.authority.authority_kind is not AuthorityKind.HUMAN

    @property
    def decision_lag_seconds(self) -> float:
        """How stale the information set was when the decision was taken."""
        return (self.decided_at - self.input_snapshot_as_of).total_seconds()


class ActionOutcome(BaseModel):
    """What eventually happened after an action.

    ITS OWN RECORD WITH ITS OWN RECEIPT TIME, not a field on `ActionRecord`, and
    that is the single most important structural decision in this module. An
    outcome written onto the action would be a mutation of a row that snapshots
    have already admitted -- the exact write these tables refuse -- and it would
    make the action's content hash unstable. Separating them also allows the
    several outcomes a single action really has: the pickup was 14 minutes late
    (measured at +14m), the rider complained (at +3 days), the trip was re-billed
    (at +1 month). Each is a separate record at its own horizon.

    The outcome's receipt time is necessarily LATER than the action's, so an
    outcome is invisible to any snapshot at or before the decision it followed.
    That is not a rule this class enforces -- it is a consequence of receipt
    monotonicity, and it is the mechanism by which labels cannot leak into
    features.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome_id: OutcomeId
    tenant_id: TenantId
    action_id: ActionId
    metric: str = Field(min_length=1)
    value: float
    observed_at: UtcDateTime = Field(description="VALID time: when the outcome was observed.")
    receipt: ReceiptStamp = Field(description="TRANSACTION time. Writer-assigned.")
    horizon_seconds: float = Field(
        ge=0.0,
        description="How long after the decision this outcome was measured. Stored rather than derived so an outcome is interpretable without joining back to its action.",
    )
    source_system: str = Field(min_length=1)
    source_record_id: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "ActionOutcome":
        if self.observed_at > self.receipt.receipt_time:
            raise ValueError(
                "an outcome cannot be received before it is observed"
            )
        return self
