"""The durable per-request LIFECYCLE RECORD (Program A).

WHAT THIS EXISTS TO MAKE TRUE. `state_machine.py` is a *contract*: it says which
moves are legal. It has never said which moves a given request actually made, or
when, or why. That is the difference between a rulebook and a record, and the
claim this repository has made in writing is about the record:

    "records why each trip received the outcome it did -- booked, offered,
    negotiated, denied or late -- created at the moment of the decision rather
    than reconstructed afterwards."

So this module stores, per request, an append-only chain of
`from_state -> to_state` moves, each carrying the instant the decision WAS MADE,
the instant Milexium WROTE IT DOWN, who or what decided, and the reason codes
where the move was a denial or a negotiation.

TWO CLOCKS, AND ONLY ONE OF THEM MAY BE THE WRITER'S
`decided_at` is VALID time: the operational instant a dispatcher or the scheduler
actually reached the conclusion. `recorded_at` is TRANSACTION time: when this
system wrote the row. Both are REQUIRED fields with NO DEFAULT, and nothing in
this module or in either store reads a clock -- there is no `datetime.now()`
anywhere on the write path and the `decided_at` column carries no SQL DEFAULT, on
either engine. A record that stamped itself on write would be exactly the
"reconstructed afterwards" artefact the sentence above promises this is not, so
the absence of a clock is asserted structurally (by AST over this module's own
source and by `information_schema`) rather than left as a convention. A write
whose `recorded_at` precedes its `decided_at` is refused in Python AND by a CHECK
constraint in the portable DDL.

WHY THE TIMESTAMPS ARE FIXED-WIDTH AND THE REST OF THE REPOSITORY'S ARE NOT
Everything else here stores timestamps as `datetime.isoformat()`, whose fraction
is elided when it is zero -- `...T09:14:03+00:00` next to `...T09:14:03.500000+00:00`.
That is fine while nothing COMPARES two of them in SQL. This table does compare
them (the CHECK above), and on PostgreSQL a TEXT comparison runs under the
database collation, not byte order. On the collation this repository's dev
instance actually uses (`English_United Kingdom.1252`) the two strings above
compare in the WRONG ORDER, because a non-alphanumeric character is weighted
differently from a digit. `iso_fixed_utc` therefore always emits six fractional
digits, so every stored value has identical punctuation in identical positions
and the comparison degenerates to a digit-by-digit one that is correct under any
collation. `conformance/property-tests/test_lifecycle_record.py` pins the
counterexample so this cannot be "simplified" back.

WHAT LIVES HERE RATHER THAN IN THE STORES
The chain rules (`next_transition`) and the explain view (`explain`) are pure
functions in THIS module, and both stores call them. The rules therefore cannot
diverge between SQLite and PostgreSQL by editing one store and forgetting the
other -- there is one implementation and two callers, not two implementations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.canonical.ids import RequestId, RequestTransitionId, TenantId, new_id
from packages.canonical.state_machine import (
    SERVICE_REQUEST_INITIAL_STATE,
    SERVICE_REQUEST_TERMINAL_STATES,
    ServiceRequestState,
    check_transition,
)
from packages.canonical.time import UtcDateTime
from packages.canonical.vocab import ReasonCode

# The actor vocabulary is deliberately the one `decision_events.actor_type`
# already uses ('system' | 'human'), not a new one: "who decided" must mean the
# same thing in the lifecycle record as it does in the decision ledger, or an
# evidence pack that draws on both is quietly comparing two vocabularies.
ActorType = Literal["system", "human"]

_FIXED_WIDTH_UTC = "%Y-%m-%dT%H:%M:%S.%f+00:00"


class BackdatedRecordError(ValueError):
    """A write whose `recorded_at` precedes its `decided_at`.

    Its own type because it is the one failure that would falsify the claim this
    module exists to support: a row that says it was written BEFORE the decision
    it records is either a clock defect or a fabricated history, and either way
    the record can no longer be read as evidence of decision-time capture.
    """


class LifecycleOrderError(ValueError):
    """A transition that does not continue this request's existing chain.

    Distinct from `TransitionError` (which means the CONTRACT forbids the move
    from that state) because the remedy is different: this one means the caller's
    view of where the request currently is disagrees with what is stored -- a
    lost update, a replayed command, or two writers racing.
    """


def iso_fixed_utc(value: datetime) -> str:
    """Render a UTC instant as a FIXED-WIDTH ISO-8601 string.

    Always six fractional digits and always the literal `+00:00` offset, so any
    two rendered values have identical punctuation in identical positions -- see
    the collation note in this module's docstring for why that is load-bearing
    and not cosmetic.
    """
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware (UTC)")
    return value.astimezone(timezone.utc).strftime(_FIXED_WIDTH_UTC)


def parse_fixed_utc(text: str) -> datetime:
    """Inverse of `iso_fixed_utc`. Accepts any ISO-8601 form `fromisoformat`
    accepts, so a value written before this convention existed still reads."""
    return datetime.fromisoformat(text)


class TimeWindow(BaseModel):
    """A closed pickup window: what the rider asked for, or what was offered.

    Kept as one object rather than two loose timestamps so "start after end" is
    impossible to construct, and so a window is present or absent as a WHOLE --
    a half-recorded window would make the negotiated-vs-requested delta silently
    uncomputable in one direction only.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: UtcDateTime
    end: UtcDateTime

    @model_validator(mode="after")
    def _ordered(self) -> "TimeWindow":
        if self.start > self.end:
            raise ValueError(
                f"window start {self.start.isoformat()} is after its end {self.end.isoformat()}"
            )
        return self

    @property
    def minutes(self) -> float:
        """The window's width. A wider offered window is a worse offer, so this
        is part of what a negotiation delta has to expose."""
        return (self.end - self.start).total_seconds() / 60.0


class RequestTransition(BaseModel):
    """ONE durable, append-only row of a request's lifecycle record.

    Every field that makes this evidence rather than a log line is mandatory:
    both states, both clocks, the actor, and -- for a denial or a negotiation --
    the reason codes. `extra='forbid'` means an ingest cannot smuggle a free-text
    "note" onto the record and have it read as a reason (blueprint 06: reason
    codes are a closed vocabulary, never generated prose).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    transition_id: RequestTransitionId
    tenant_id: TenantId
    request_id: RequestId
    sequence: int = Field(
        ge=1,
        description=(
            "Position in this request's chain, 1-based. Assigned by the store "
            "from what is already stored, never by the caller -- two writers "
            "cannot both believe they are writing position 3."
        ),
    )
    from_state: ServiceRequestState
    to_state: ServiceRequestState
    decided_at: UtcDateTime = Field(
        description=(
            "VALID time: when the decision was actually made. REQUIRED, supplied "
            "by the caller at the moment of the decision. There is deliberately "
            "no default -- a defaulted decision time is a reconstruction."
        )
    )
    recorded_at: UtcDateTime = Field(
        description=(
            "TRANSACTION time: when Milexium wrote this row. REQUIRED and never "
            "before `decided_at`."
        )
    )
    actor_type: ActorType
    actor_id: str = Field(
        min_length=1,
        description="Tokenised actor reference (a service name, or a dispatcher token). Never a raw name.",
    )
    reason_codes: tuple[ReasonCode, ...] = Field(
        default=(),
        description=(
            "Closed-vocabulary reasons. MANDATORY for a denial and for a "
            "negotiation; optional elsewhere, where the move itself is the whole "
            "explanation."
        ),
    )
    requested_window: TimeWindow | None = Field(
        default=None, description="The pickup window the rider asked for, as known at decision time."
    )
    negotiated_window: TimeWindow | None = Field(
        default=None, description="The pickup window offered instead, as agreed at decision time."
    )

    @model_validator(mode="after")
    def _validate(self) -> "RequestTransition":
        # THE SECOND NET. Both stores check these before constructing the record,
        # so these branches normally do not fire from a store write; they exist so
        # that a `RequestTransition` built ANYWHERE -- a test fixture, a future
        # importer, an evidence pack reader -- still cannot hold an illegal or
        # self-stamping history. Both layers are exercised in the conformance suite.
        check_transition(self.from_state, self.to_state)
        if self.recorded_at < self.decided_at:
            raise BackdatedRecordError(
                f"recorded_at {self.recorded_at.isoformat()} precedes decided_at "
                f"{self.decided_at.isoformat()}: a record cannot be written before "
                "the decision it records"
            )
        if self.to_state is ServiceRequestState.DENIED and not self.reason_codes:
            raise ValueError(
                "a denial must carry at least one reason code -- 'denied, reason "
                "unrecorded' is the outcome this record exists to make impossible"
            )
        if self.to_state is ServiceRequestState.NEGOTIATED:
            if not self.reason_codes:
                raise ValueError(
                    "a negotiation must carry at least one reason code explaining why "
                    "the requested window could not be honoured"
                )
            if self.requested_window is None or self.negotiated_window is None:
                raise ValueError(
                    "a negotiation must carry BOTH the requested and the negotiated "
                    "window: a negotiation is by definition 'you asked for X, we "
                    "offer Y', and without X the delta a rider actually experienced "
                    "cannot be computed later from this record"
                )
        return self

    @property
    def is_terminal(self) -> bool:
        return self.to_state in SERVICE_REQUEST_TERMINAL_STATES


class OutcomeExplanation(BaseModel):
    """The "explain this outcome" view for one request.

    Answers the three questions an accessibility regulator or an ombudsman asks
    about a single trip, from stored rows only: what happened to it, on what
    stated grounds, and how far the trip it was offered sat from the trip it
    asked for.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: TenantId
    request_id: RequestId
    current_state: ServiceRequestState
    terminal_state: ServiceRequestState | None = Field(
        default=None,
        description=(
            "The outcome, if the request has reached one. None means the request "
            "is still in flight -- stated as absence rather than as a guess at "
            "where it will end up."
        ),
    )
    is_terminal: bool
    decided_at: UtcDateTime = Field(description="When the most recent recorded decision was made.")
    outcome_reason_codes: tuple[ReasonCode, ...] = Field(
        default=(),
        description=(
            "The codes on the MOST RECENT recorded transition. When `is_terminal` "
            "is true these are the grounds for the outcome itself; when it is "
            "false they are the grounds for the latest decision on a request that "
            "does not have an outcome yet, and must not be read as explaining one. "
            "Read this field together with `is_terminal`, never alone."
        ),
    )
    all_reason_codes: tuple[ReasonCode, ...] = Field(
        default=(),
        description=(
            "Every code cited anywhere in the chain, first-seen order, de-duplicated. "
            "A request negotiated for NO_ACCESSIBLE_CAPACITY and later denied for "
            "SHIFT_END was shaped by both, and the outcome codes alone would show "
            "only the second."
        ),
    )
    requested_window: TimeWindow | None = None
    negotiated_window: TimeWindow | None = None
    window_start_delta_minutes: float | None = Field(
        default=None,
        description=(
            "negotiated.start - requested.start, in minutes. Positive means the "
            "rider was pushed later. None means no negotiation was recorded -- "
            "never 0.0, which would assert the offer matched the request."
        ),
    )
    window_end_delta_minutes: float | None = Field(
        default=None, description="negotiated.end - requested.end, in minutes."
    )
    transitions: tuple[RequestTransition, ...] = Field(
        description="The ordered history the three answers above were derived from."
    )


def next_transition(
    *,
    tenant_id: TenantId,
    request_id: RequestId,
    head: RequestTransition | None,
    from_state: ServiceRequestState,
    to_state: ServiceRequestState,
    decided_at: datetime,
    recorded_at: datetime,
    actor_type: ActorType,
    actor_id: str,
    reason_codes: tuple[ReasonCode, ...] = (),
    requested_window: TimeWindow | None = None,
    negotiated_window: TimeWindow | None = None,
) -> RequestTransition:
    """Validate a proposed transition against the stored chain and build the row.

    PURE: reads no clock, touches no database. `head` is the request's current
    last transition (None for a request with no history yet), which the caller --
    always a store -- has just read back under its own tenant scope.

    Both stores call THIS function, so the rules below are one implementation
    with two callers rather than two implementations that can drift.

    Raises, in this order:
      * `BackdatedRecordError` -- `recorded_at` before `decided_at`.
      * `LifecycleOrderError`  -- the chain does not continue: a first transition
        that does not start at the machine's entry state, a `from_state` that
        disagrees with what is stored, or a decision time earlier than the
        decision it is being appended after.
      * `TransitionError`      -- the CONTRACT forbids `from_state -> to_state`.
        Appending anything after a terminal state lands here, because a terminal
        state's allowed set is empty.
    """
    if recorded_at < decided_at:
        raise BackdatedRecordError(
            f"recorded_at {recorded_at.isoformat()} precedes decided_at "
            f"{decided_at.isoformat()}: a record cannot be written before the "
            "decision it records"
        )

    if head is None:
        if from_state is not SERVICE_REQUEST_INITIAL_STATE:
            raise LifecycleOrderError(
                f"request {request_id!s} has no recorded history, so its first "
                f"transition must start at {SERVICE_REQUEST_INITIAL_STATE.value!r}, "
                f"not {from_state.value!r}"
            )
        sequence = 1
    else:
        if from_state is not head.to_state:
            raise LifecycleOrderError(
                f"request {request_id!s} is recorded as being in "
                f"{head.to_state.value!r}, but the transition claims to start from "
                f"{from_state.value!r}"
            )
        if decided_at < head.decided_at:
            raise LifecycleOrderError(
                f"decided_at {decided_at.isoformat()} is earlier than the decision "
                f"it follows ({head.decided_at.isoformat()}): a request's decisions "
                "are recorded in the order they were made"
            )
        sequence = head.sequence + 1

    check_transition(from_state, to_state)

    return RequestTransition(
        transition_id=new_id(RequestTransitionId),
        tenant_id=tenant_id,
        request_id=request_id,
        sequence=sequence,
        from_state=from_state,
        to_state=to_state,
        decided_at=decided_at,
        recorded_at=recorded_at,
        actor_type=actor_type,
        actor_id=actor_id,
        reason_codes=tuple(reason_codes),
        requested_window=requested_window,
        negotiated_window=negotiated_window,
    )


def explain(
    *,
    tenant_id: TenantId,
    request_id: RequestId,
    transitions: tuple[RequestTransition, ...],
) -> OutcomeExplanation | None:
    """Build the "explain this outcome" view from an ordered history.

    PURE, and shared by both stores for the same reason `next_transition` is: the
    view a regulator would be shown must not depend on which engine served it.

    Returns None for a request with no recorded history -- absence, not an
    invented "requested" state for a request this record has never seen.

    The windows reported are the ones from the LAST transition that carried both,
    which is the negotiation that actually stood. A later re-negotiation is a
    later transition, so this reports the offer the rider ended up with rather
    than the first one proposed.
    """
    if not transitions:
        return None

    final = transitions[-1]

    seen: list[ReasonCode] = []
    for transition in transitions:
        for code in transition.reason_codes:
            if code not in seen:
                seen.append(code)

    requested_window: TimeWindow | None = None
    negotiated_window: TimeWindow | None = None
    for transition in transitions:
        if transition.requested_window is not None and transition.negotiated_window is not None:
            requested_window = transition.requested_window
            negotiated_window = transition.negotiated_window

    start_delta: float | None = None
    end_delta: float | None = None
    if requested_window is not None and negotiated_window is not None:
        start_delta = (
            negotiated_window.start - requested_window.start
        ).total_seconds() / 60.0
        end_delta = (negotiated_window.end - requested_window.end).total_seconds() / 60.0

    return OutcomeExplanation(
        tenant_id=tenant_id,
        request_id=request_id,
        current_state=final.to_state,
        terminal_state=final.to_state if final.is_terminal else None,
        is_terminal=final.is_terminal,
        decided_at=final.decided_at,
        outcome_reason_codes=final.reason_codes,
        all_reason_codes=tuple(seen),
        requested_window=requested_window,
        negotiated_window=negotiated_window,
        window_start_delta_minutes=start_delta,
        window_end_delta_minutes=end_delta,
        transitions=transitions,
    )
