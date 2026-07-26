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

TWO CLOCKS, AND THE CALLER OWNS EXACTLY ONE OF THEM
`decided_at` is VALID time: the operational instant a dispatcher or the scheduler
actually reached the conclusion. It is the caller's to supply, it has no default
anywhere -- not in the signature, not in the DDL -- and nothing in this module or
either store reads a clock ON ITS BEHALF. A record that stamped its own decision
time would be exactly the "reconstructed afterwards" artefact the sentence above
promises this is not, so that absence is asserted structurally (by AST over this
module's own source and by `information_schema`) rather than left as a convention.

`recorded_at` is TRANSACTION time: when Milexium wrote the row. It used to be a
required argument too, and MX-A-LIFECYCLE-IMMUTABILITY-012 exists because that
was wrong. An external audit inserted a transition asserting a 2020-01-01
decision recorded one second later; it was accepted, because the only rule was
`recorded_at >= decided_at` and BOTH sides of that comparison came from the
caller. The system proved that two caller assertions were ordered and nothing at
all about when the row entered Milexium. There is now no `recorded_at` argument:
`packages/canonical/transaction_clock.py` stamps it inside the writer, and the
database BOUNDS it -- a server-clock DEFAULT plus a BEFORE INSERT trigger on both
engines that refuses any value more than
`RECORDED_AT_TOLERANCE_SECONDS` from the database's own clock. So the claim this
column can support is: *this row was written within a minute of the instant it
says it was*, enforced against raw SQL and not only against this API.

A write whose `recorded_at` precedes its `decided_at` is still refused in Python
AND by a CHECK constraint in the portable DDL. Because the writer stamps
`recorded_at`, the case that now reaches that rule is a caller claiming a
decision in the FUTURE, which is the same falsehood from the other end.

LATE ARRIVAL IS DECLARED, NEVER SILENT
The gap between the two clocks is measured and stored (`ingest_lag_seconds`), and
past `LIFECYCLE_LATE_ARRIVAL_THRESHOLD_SECONDS` a row must name a
`LateRecordingReason`. A decision recorded three days late is entirely
legitimate -- an integration outage, an overnight batch, a dispatcher working off
paper. Recording it as though it were contemporaneous is not, and the difference
between those two is the whole distinction this record is supposed to carry.

TAMPER EVIDENCE
Every transition carries `prev_hash`/`hash`, computed by the SAME normative
`compute_hash` the decision-event ledger uses (ADR-0003). The audit found the
ledger's re-verifiability being read as though it covered this table, which had
no chain at all. `lifecycle_verify.py` re-derives the chain from stored rows and
states precisely what that does and does not prove.

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
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.canonical.events import compute_hash
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

#: Past this many seconds between the decision and its recording, the row must
#: NAME why. 300s is a bound on "contemporaneous" for a dispatch decision: a
#: scheduler writes in milliseconds and a human dispatcher in seconds, so five
#: minutes is already an outlier for a live integration and is comfortably inside
#: a normal batch or replay window. The number is a judgement, and it is written
#: down here once: the same literal appears in the portable DDL's CHECK and a
#: conformance test pins the two together, because a threshold that drifted
#: between application and database would mean rows the application called late
#: that the database accepted with no explanation at all.
LIFECYCLE_LATE_ARRIVAL_THRESHOLD_SECONDS = 300.0

#: How far a stored `recorded_at` may sit from the DATABASE's own clock before
#: the insert is refused. This is the bound that makes `recorded_at` transaction
#: time rather than a caller assertion, so it wants to be tight -- but it has to
#: absorb the skew between whichever host runs the writer and whichever runs the
#: database, and a bound so tight that ordinary skew trips it would be turned off
#: by the first person it woke at 3am. 60s is the compromise, enforced by the
#: BEFORE INSERT triggers in sql/lifecycle_immutability_sqlite.sql and
#: infra/compose/initdb/02-lifecycle-ledger-bootstrap.sql. Both directions matter:
#: backwards is the audit's forgery, forwards is a row claiming to have been
#: written in a future nobody can check yet.
RECORDED_AT_TOLERANCE_SECONDS = 60.0


class LateRecordingReason(str, Enum):
    """WHY a decision reached the record later than it was made.

    A CLOSED VOCABULARY, exactly as `ReasonCode` is and for the same reason: free
    text here would be a prose field on an evidence record, and prose is what gets
    written when nobody wants to say which of these it actually was. Five members,
    each naming a materially different failure of contemporaneity -- an operator
    reading this back needs to know whether the gap was a scheduled batch (normal),
    an outage (an availability problem), or a human typing yesterday's decisions
    in (a data-quality problem).

    NOT a member, deliberately: anything meaning "test fixture" or "unknown". A
    vocabulary member that exists to let a caller past the rule IS the rule not
    existing. The synthetic fixtures in the conformance suite declare
    BATCH_IMPORT, which is what they honestly are: decisions dated 2026-07-01
    written into a database today.
    """

    BATCH_IMPORT = "BATCH_IMPORT"
    """A scheduled export/import cycle: the decision was made in the operator's
    system and reached Milexium on the next run."""

    INTEGRATION_OUTAGE = "INTEGRATION_OUTAGE"
    """The live path was down and the decisions were replayed once it returned."""

    MANUAL_BACKFILL = "MANUAL_BACKFILL"
    """A human entered decisions after the fact -- the weakest provenance of the
    five, and the one an auditor should look at hardest."""

    OFFLINE_DISPATCH = "OFFLINE_DISPATCH"
    """The decision was made without connectivity (a radio call, a paper manifest)
    and recorded when the vehicle or the dispatcher came back online."""

    SYSTEM_MIGRATION = "SYSTEM_MIGRATION"
    """History carried in from a predecessor system at cutover."""


class BackdatedRecordError(ValueError):
    """A write whose `recorded_at` precedes its `decided_at`.

    Its own type because it is the one failure that would falsify the claim this
    module exists to support: a row that says it was written BEFORE the decision
    it records is either a clock defect or a fabricated history, and either way
    the record can no longer be read as evidence of decision-time capture.
    """


class UndeclaredLateRecordError(ValueError):
    """A transition recorded long after it was decided, with no reason given.

    Its own type because the remedy is specific and is NOT "retry": the caller has
    to say which `LateRecordingReason` applies. Raising `ValueError` here would
    push an ingest into catching a type that also means "your reason code is not
    in the vocabulary", and the two need different handling -- one is a bug in the
    payload, the other is a fact about the integration that somebody has to state.
    """


class LifecycleChainError(ValueError):
    """A stored transition whose hash does not match its own contents.

    Raised on READ, never on write. A row that fails this is either a mutation
    that got past the immutability triggers and the privilege boundary, or a
    restore from a tampered dump, or a genuine corruption -- and all three mean
    the same thing to a reader: this is not evidence any more.
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


#: Domain separator inside the hashed payload. A lifecycle transition and a
#: decision event are hashed by the SAME function, so without this a payload
#: crafted for one could in principle be presented as the other; with it the two
#: hash spaces cannot overlap. Versioned, because the day a field is added to the
#: hashed set every existing hash legitimately stops matching and a reader needs
#: to be able to tell that apart from tampering.
LIFECYCLE_HASH_RECORD_TYPE = "request_state_transition/v1"


def _enum_value(value: object) -> object:
    """The `.value` of an enum member, or the value itself if it is not one.

    See `transition_payload` for why this is not defensive clutter: it runs before
    validation, so it must render an invalid input rather than crash on it and
    steal the error from the layer that owns the rule.
    """
    return value.value if isinstance(value, Enum) else value


def _window_payload(window: "TimeWindow | None") -> dict | None:
    return None if window is None else {
        "start": iso_fixed_utc(window.start),
        "end": iso_fixed_utc(window.end),
    }


def transition_payload(
    *,
    transition_id: object,
    tenant_id: object,
    request_id: object,
    from_state: ServiceRequestState,
    to_state: ServiceRequestState,
    decided_at: datetime,
    recorded_at: datetime,
    actor_type: str,
    actor_id: str,
    reason_codes: tuple[ReasonCode, ...],
    requested_window: "TimeWindow | None",
    negotiated_window: "TimeWindow | None",
    late_recording_reason: "LateRecordingReason | None",
) -> dict:
    """EVERY asserted field of a transition, as the dict that gets hashed.

    `transition_id` is in here so a row's identity is bound to its contents --
    without it two rows could have their ids swapped and both chains would still
    verify. `ingest_lag_seconds` is deliberately NOT here: it is a pure function
    of the two timestamps, which ARE here, and `RequestTransition` refuses any row
    whose stored lag disagrees with them. Hashing a derived float would add a
    serialisation-precision failure mode for no additional coverage.

    The timestamps go in as their FIXED-WIDTH rendering, i.e. exactly the bytes
    the database stores, so a hash recomputed from a stored row and a hash
    computed before the write are comparing the same thing.

    IT MUST NOT ASSUME ITS INPUTS ARE VALID. On the write path this runs BEFORE
    `RequestTransition` has validated anything, so a caller passing free text where
    a `ReasonCode` belongs reaches here first. Reading `.value` off it unguarded
    turned the intended `ValidationError` -- "that is not in the vocabulary" --
    into an `AttributeError` from inside the hasher, which is both the wrong error
    and the wrong LAYER: the vocabulary rule is the model's to enforce, and this
    function's job is only to render whatever it is handed deterministically.
    `_enum_value` keeps it renderable so the real check can still be the one that
    fires. (Caught by `test_free_text_cannot_reach_the_record_in_place_of_a_reason_code`,
    which is exactly what it is for.)
    """
    return {
        "record": LIFECYCLE_HASH_RECORD_TYPE,
        "transition_id": str(transition_id),
        "tenant_id": str(tenant_id),
        "request_id": str(request_id),
        "from_state": _enum_value(from_state),
        "to_state": _enum_value(to_state),
        "decided_at": iso_fixed_utc(decided_at),
        "recorded_at": iso_fixed_utc(recorded_at),
        "actor_type": actor_type,
        "actor_id": actor_id,
        "reason_codes": [_enum_value(code) for code in reason_codes],
        "requested_window": _window_payload(requested_window),
        "negotiated_window": _window_payload(negotiated_window),
        "late_recording_reason": (
            None if late_recording_reason is None else _enum_value(late_recording_reason)
        ),
    }


def lifecycle_transition_hash(
    *, prev_hash: str | None, payload: dict, sequence: int, request_id: object
) -> str:
    """The normative lifecycle-chain hash.

    Deliberately `packages.canonical.events.compute_hash` rather than a second
    SHA-256 construction: ADR-0003 made that function normative for the decision
    ledger, and a lifecycle record that chained itself a slightly different way
    would give an evidence pack two link formats to explain. The aggregate this
    chain is per is the REQUEST, so `request_id` is the aggregate id -- one chain
    per request per tenant, which is exactly what `sequence` counts.
    """
    return compute_hash(prev_hash, payload, sequence, str(request_id), None)


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
            "TRANSACTION time: when Milexium wrote this row. Stamped by the "
            "WRITER (packages/canonical/transaction_clock.py), never by the "
            "caller -- `record_transition` has no such argument -- and bounded by "
            "a database trigger against the server's own clock. Never before "
            "`decided_at`."
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
    ingest_lag_seconds: float = Field(
        ge=0.0,
        description=(
            "MEASURED recorded_at - decided_at. Stored rather than left to be "
            "recomputed by every reader, so 'how late was this record' is a "
            "column an analyst can filter on and an evidence pack can carry, not "
            "a subtraction someone might do differently."
        ),
    )
    late_recording_reason: LateRecordingReason | None = Field(
        default=None,
        description=(
            "Why the gap. MANDATORY once the lag exceeds "
            "LIFECYCLE_LATE_ARRIVAL_THRESHOLD_SECONDS, forbidden below it -- a "
            "reason on a contemporaneous row would make the field mean nothing."
        ),
    )
    prev_hash: str | None = Field(
        default=None,
        description=(
            "The hash of this request's previous transition. None at sequence 1 "
            "and never anywhere else -- a NULL further along would be a chain "
            "silently re-rooted."
        ),
    )
    hash: str = Field(
        min_length=64,
        description=(
            "SHA-256 over this row's asserted contents and its predecessor's "
            "hash. Recomputed and CHECKED by this model, so a `RequestTransition` "
            "holding contents that disagree with its own hash cannot exist."
        ),
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

        # THE LAG IS RE-DERIVED, NOT TRUSTED. The stored column is a measurement,
        # and a measurement that can disagree with the two values it was measured
        # from is a place to hide an edit: change `decided_at` on a stored row and
        # the lag column is what would otherwise still say the record was prompt.
        # 1e-6 is one microsecond -- the resolution of the timestamps themselves.
        measured = (self.recorded_at - self.decided_at).total_seconds()
        if abs(self.ingest_lag_seconds - measured) > 1e-6:
            raise ValueError(
                f"ingest_lag_seconds is {self.ingest_lag_seconds!r} but the two "
                f"stored clocks are {measured!r} apart: this row's measured ingest "
                "lag disagrees with its own timestamps"
            )

        if measured > LIFECYCLE_LATE_ARRIVAL_THRESHOLD_SECONDS:
            if self.late_recording_reason is None:
                raise UndeclaredLateRecordError(
                    f"this decision was recorded {measured:.0f}s after it was made, "
                    f"beyond the {LIFECYCLE_LATE_ARRIVAL_THRESHOLD_SECONDS:.0f}s "
                    "contemporaneity bound, with no late_recording_reason. A late "
                    "record is legitimate; a late record presented as a "
                    "contemporaneous one is not"
                )
        elif self.late_recording_reason is not None:
            raise ValueError(
                f"this row was recorded {measured:.3f}s after the decision -- inside "
                "the contemporaneity bound -- so it must NOT name a "
                f"late_recording_reason ({self.late_recording_reason.value!r}). A "
                "reason on a prompt row would make the field unreadable as a signal"
            )

        if (self.sequence == 1) != (self.prev_hash is None):
            raise ValueError(
                f"sequence {self.sequence} with prev_hash {self.prev_hash!r}: the "
                "first transition of a chain has no predecessor and every later one "
                "has exactly one"
            )

        expected = lifecycle_transition_hash(
            prev_hash=self.prev_hash,
            payload=transition_payload(
                transition_id=self.transition_id,
                tenant_id=self.tenant_id,
                request_id=self.request_id,
                from_state=self.from_state,
                to_state=self.to_state,
                decided_at=self.decided_at,
                recorded_at=self.recorded_at,
                actor_type=self.actor_type,
                actor_id=self.actor_id,
                reason_codes=self.reason_codes,
                requested_window=self.requested_window,
                negotiated_window=self.negotiated_window,
                late_recording_reason=self.late_recording_reason,
            ),
            sequence=self.sequence,
            request_id=self.request_id,
        )
        if self.hash != expected:
            raise LifecycleChainError(
                f"transition {self.transition_id!s} carries hash {self.hash!r} but "
                f"its contents hash to {expected!r}: this row has been altered "
                "since it was written, or was never written by this system"
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
    recorded_at: UtcDateTime = Field(
        description=(
            "When Milexium WROTE that most recent decision down. Reported beside "
            "`decided_at` rather than left in the transition list because the two "
            "being far apart is a fact about the evidence, and a reader shown only "
            "the decision time cannot tell a live capture from a backfill."
        )
    )
    ingest_lag_seconds: float = Field(
        description="`recorded_at` - `decided_at` for that decision, in seconds."
    )
    late_recording_reason: "LateRecordingReason | None" = Field(
        default=None,
        description=(
            "The declared reason the outcome reached the record late, or None if "
            "it was recorded within the contemporaneity bound. None here means "
            "'recorded promptly', NOT 'no reason was given' -- the record cannot "
            "hold a late row with no reason."
        ),
    )
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
    late_reason: LateRecordingReason | None = None,
) -> RequestTransition:
    """Validate a proposed transition against the stored chain and build the row.

    PURE: reads no clock, touches no database. `recorded_at` is passed IN by the
    store, which read it from `transaction_clock.py` -- keeping this function
    clock-free is what lets the whole chain rule set be replayed deterministically
    over a stored history. `head` is the request's current last transition (None
    for a request with no history yet), which the caller -- always a store -- has
    just read back under its own tenant scope; its hash becomes this row's
    `prev_hash`, which is why the chain link cannot be supplied by a caller either.

    Both stores call THIS function, so the rules below are one implementation
    with two callers rather than two implementations that can drift.

    Raises, in this order:
      * `BackdatedRecordError` -- `recorded_at` before `decided_at`. Since the
        writer stamps `recorded_at`, what this now catches is a decision claimed
        in the FUTURE.
      * `LifecycleOrderError`  -- the chain does not continue: a first transition
        that does not start at the machine's entry state, a `from_state` that
        disagrees with what is stored, or a decision time earlier than the
        decision it is being appended after.
      * `TransitionError`      -- the CONTRACT forbids `from_state -> to_state`.
        Appending anything after a terminal state lands here, because a terminal
        state's allowed set is empty.
      * `UndeclaredLateRecordError` -- the gap between the two clocks exceeds the
        contemporaneity bound and no reason was declared. Raised HERE, ahead of
        the chain rules, because pydantic would wrap the model's copy of the same
        rule in a `ValidationError` and the caller needs the specific type.
    """
    if recorded_at < decided_at:
        raise BackdatedRecordError(
            f"recorded_at {recorded_at.isoformat()} precedes decided_at "
            f"{decided_at.isoformat()}: a record cannot be written before the "
            "decision it records. The writer stamps recorded_at from the system "
            "clock, so this means the decision is claimed in the future"
        )

    # RAISED HERE AS WELL AS IN THE MODEL, and the duplication is deliberate.
    # Pydantic WRAPS any ValueError a model validator raises in a
    # `ValidationError`, so the model's copy of this rule cannot reach a caller as
    # `UndeclaredLateRecordError` -- and the remedy for this failure ("say which
    # LateRecordingReason applies") is specific enough that it needs to be
    # distinguishable from "your payload is malformed" without string-matching.
    # The model keeps its own copy as the second net for records built outside a
    # store; this one is what a caller of `record_transition` actually catches.
    lag_seconds = (recorded_at - decided_at).total_seconds()
    if lag_seconds > LIFECYCLE_LATE_ARRIVAL_THRESHOLD_SECONDS and late_reason is None:
        raise UndeclaredLateRecordError(
            f"this decision was recorded {lag_seconds:.0f}s after it was made, "
            f"beyond the {LIFECYCLE_LATE_ARRIVAL_THRESHOLD_SECONDS:.0f}s "
            "contemporaneity bound, with no late_reason. A late record is "
            "legitimate; a late record presented as a contemporaneous one is not"
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

    transition_id = new_id(RequestTransitionId)
    prev_hash = None if head is None else head.hash
    payload = transition_payload(
        transition_id=transition_id,
        tenant_id=tenant_id,
        request_id=request_id,
        from_state=from_state,
        to_state=to_state,
        decided_at=decided_at,
        recorded_at=recorded_at,
        actor_type=actor_type,
        actor_id=actor_id,
        reason_codes=tuple(reason_codes),
        requested_window=requested_window,
        negotiated_window=negotiated_window,
        late_recording_reason=late_reason,
    )

    return RequestTransition(
        transition_id=transition_id,
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
        # Measured from the two clocks that are about to be stored, and re-derived
        # by the model from those same two -- so it cannot be passed in wrong.
        ingest_lag_seconds=(recorded_at - decided_at).total_seconds(),
        late_recording_reason=late_reason,
        prev_hash=prev_hash,
        hash=lifecycle_transition_hash(
            prev_hash=prev_hash,
            payload=payload,
            sequence=sequence,
            request_id=request_id,
        ),
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
        recorded_at=final.recorded_at,
        ingest_lag_seconds=final.ingest_lag_seconds,
        late_recording_reason=final.late_recording_reason,
        outcome_reason_codes=final.reason_codes,
        all_reason_codes=tuple(seen),
        requested_window=requested_window,
        negotiated_window=negotiated_window,
        window_start_delta_minutes=start_delta,
        window_end_delta_minutes=end_delta,
        transitions=transitions,
    )
