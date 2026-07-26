"""Ontology events: what the operational world did, receipt-stamped.

An event here is NOT a `themis/canonical/entities.DecisionEvent`. That log
records what the SCHEDULER decided and is chained per aggregate; this one records
what HAPPENED -- a rider cancelled, a vehicle broke down, a dispatcher overrode a
recommendation -- and is chained into the tenant's single receipt order alongside
facts, relationships and actions. Two logs, two id kinds
(`OntologyEventId` vs `DecisionEventId`), so a row of one cannot be cited as
evidence from the other.

THE TWO CLOCKS AGAIN, and here the gap between them is the interesting signal.
`occurred_at` is when the thing happened in the world. `receipt` is when
Milexium found out. In a real operator's data the gap is routinely minutes and
occasionally days -- a no-show keyed in at end of shift, a maintenance event
entered the next morning -- and that gap is not noise to be smoothed away:

  * A decision taken between the two could not have known about the event, and a
    replay that let it know would be scoring a dispatcher against information
    they did not have.
  * The gap's DISTRIBUTION is itself a feature of the operator. An operator
    whose no-shows arrive six hours late cannot support a same-day no-show
    model, and finding that out from the data is cheaper than finding it out
    from a failed pilot.

`ingest_lag_seconds` is therefore computed and stored rather than left to be
derived, and an event beyond `LATE_ARRIVAL_THRESHOLD_SECONDS` must name a reason
from a closed vocabulary. That is the same discipline the canonical lifecycle
record adopted after the 2026-07-26 audit: late arrival is DECLARED, not hidden.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from themis.canonical.events import canonical_json, compute_hash
from themis.canonical.time import UtcDateTime
from themis.ontology.ids import ObjectId, OntologyEventId, TenantId
from themis.ontology.receipt import ReceiptStamp
from themis.ontology.vocab import (
    AuthorityKind,
    EventKind,
    ObjectKind,
    ReasonCode,
)

__all__ = [
    "LATE_ARRIVAL_THRESHOLD_SECONDS",
    "LateArrivalReason",
    "OntologyEvent",
    "event_row_hash",
]

LATE_ARRIVAL_THRESHOLD_SECONDS = 300
"""Beyond five minutes of ingest lag, an event must say why it was late.

A GUESS about operator systems, and cheap to change -- it is one integer with
one consumer (the validator below) and one mirror (a CHECK in the portable DDL).
Five minutes is chosen because it is comfortably longer than any plausible
message-queue or polling delay and comfortably shorter than a human data-entry
gap, so the threshold separates 'the pipe was slow' from 'a person typed it in
later', which are the two populations worth telling apart. The right value is an
operator-specific empirical question; see the packet."""


class LateArrivalReason(str, Enum):
    """Why an event reached Milexium materially after it happened.

    Closed, because this is a field a consumer branches on when deciding whether
    a gap is a data-quality problem (fix the pipe) or an operational fact (the
    dispatcher records no-shows at end of shift, and always will).
    """

    BATCH_EXPORT = "batch_export"
    """The operator exports on a schedule; the lag is the export cadence."""
    MANUAL_ENTRY = "manual_entry"
    """A human typed it in later. The lag is human, not technical."""
    BACKFILL = "backfill"
    """Historical load of records that predate the integration."""
    SOURCE_OUTAGE = "source_outage"
    CORRECTION = "correction"
    """A restatement of an event already received; the original is retained."""
    UNKNOWN = "unknown"
    """An honest landing place, NOT a default -- it must be chosen. An operator
    who cannot say why their data is late has told us something real about their
    systems, and recording that is better than inventing 'batch_export'."""


class OntologyEvent(BaseModel):
    """One receipt-stamped happening.

    Frozen and `extra='forbid'`. `payload` is a plain dict because an event's
    detail genuinely varies by kind and a closed schema per kind would be 16
    models most operators only half-populate; what is NOT free-form is anything a
    consumer branches on -- `event_kind`, `subject_kind`, `reason_codes` and the
    late-arrival vocabulary are all closed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: OntologyEventId
    tenant_id: TenantId
    event_kind: EventKind
    subject_kind: ObjectKind
    subject_id: ObjectId

    occurred_at: UtcDateTime = Field(
        description=(
            "VALID time: when it happened in the world. Supplied by the caller "
            "at the moment they know it, with no default -- a defaulted "
            "occurrence time is a reconstruction."
        )
    )
    receipt: ReceiptStamp = Field(
        description="TRANSACTION time: when Milexium received it. Writer-assigned."
    )

    actor_kind: AuthorityKind
    actor_ref: str = Field(
        min_length=1,
        description="Tokenised actor reference -- a service name or a dispatcher token. Never a raw name (blueprint 10 data minimisation).",
    )
    reason_codes: tuple[ReasonCode, ...] = ()
    late_arrival_reason: LateArrivalReason | None = None
    payload: dict = Field(default_factory=dict)

    prev_hash: str | None = Field(
        default=None,
        description="Hash of the preceding row in this tenant's receipt ledger. None only at sequence 1.",
    )
    hash: str = Field(
        description="Tamper-evidence over this row, by the normative themis.canonical.events.compute_hash."
    )

    @model_validator(mode="after")
    def _validate(self) -> "OntologyEvent":
        if self.receipt.receipt_time < self.occurred_at:
            raise ValueError(
                f"event received at {self.receipt.receipt_time.isoformat()} claims to "
                f"have occurred at {self.occurred_at.isoformat()}, in its own future. "
                "An event cannot be received before it happens"
            )
        if self.ingest_lag_seconds > LATE_ARRIVAL_THRESHOLD_SECONDS and (
            self.late_arrival_reason is None
        ):
            raise ValueError(
                f"event arrived {self.ingest_lag_seconds:.0f}s after it occurred "
                f"(threshold {LATE_ARRIVAL_THRESHOLD_SECONDS}s) with no "
                "late_arrival_reason. A decision recorded hours late is legitimate; "
                "recording it as though it were contemporaneous is not"
            )
        if self.receipt.receipt_sequence == 1:
            if self.prev_hash is not None:
                raise ValueError("the first row in a receipt ledger has no predecessor")
        elif self.prev_hash is None:
            raise ValueError(
                f"event at receipt sequence {self.receipt.receipt_sequence} has a null "
                "prev_hash: a chain cannot be silently re-rooted"
            )
        return self

    @property
    def ingest_lag_seconds(self) -> float:
        """`receipt_time - occurred_at`. Non-negative by the validator above."""
        return (self.receipt.receipt_time - self.occurred_at).total_seconds()

    @property
    def is_late(self) -> bool:
        return self.ingest_lag_seconds > LATE_ARRIVAL_THRESHOLD_SECONDS


def event_row_hash(
    *,
    prev_hash: str | None,
    tenant_id: TenantId,
    event_id: OntologyEventId,
    receipt_sequence: int,
    payload: dict,
) -> str:
    """Chain hash for one event row.

    Delegates to `themis.canonical.events.compute_hash` -- THE normative hash
    function for this repository (ADR-0003) -- rather than defining a second one,
    so a hash computed here is comparable with one computed by the canonical
    ledger and a verifier needs one implementation, not two. `canonical_json` is
    imported for the same reason: deterministic serialisation must mean one
    thing.
    """
    return compute_hash(
        prev_hash,
        {"row": canonical_json(payload), "tenant": str(tenant_id)},
        receipt_sequence,
        str(event_id),
        None,
    )
