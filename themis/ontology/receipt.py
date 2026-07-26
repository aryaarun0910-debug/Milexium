"""Milexium RECEIPT TIME: the one clock the caller does not own.

THE DEFECT THIS MODULE EXISTS TO NOT REPEAT.
An external audit of this repository (2026-07-26) wrote, of the canonical
lifecycle record:

    "Both its alleged valid-time and transaction-time clocks are caller-supplied.
     I inserted a transition today whose `decided_at` was 2020-01-01 and whose
     `recorded_at` was one second later. It was accepted. The system proves only
     that two assertions are ordered."

Every ontology write therefore carries TWO clocks with different owners:

  * **Event time** (`event_time`, `occurred_at`, `decided_at`) is the CALLER's.
    It is what the operational world says happened, and only the caller can know
    it. It is never defaulted -- a defaulted decision time is a reconstruction.
  * **Receipt time** (`ReceiptStamp.receipt_time`) is the WRITER's. It is when
    the fact entered Milexium. There is no parameter for it anywhere in
    `themis/ontology/store.py`: not an optional one, not a keyword-only one.
    A caller cannot supply it, so a caller cannot assert it.

WHY MONOTONICITY, NOT A WALL-CLOCK WINDOW, IS THE LOAD-BEARING RULE.
The obvious repair is "reject a receipt time more than N seconds from the server
clock". That bounds fabrication but it is not the property a point-in-time
snapshot actually needs, and it makes the system untestable without sleeping.
The property that matters is:

    Once a snapshot has been taken at time T, no write may ever afterwards
    appear with a receipt time earlier than T.

That is what makes an information set FINAL: the set of facts admitted at T can
never be enlarged after the fact, so a snapshot rebuilt tomorrow for the same T
is byte-identical to the one built today. It is enforced three ways --

  1. `ReceiptLedger.stamp` refuses a clock reading earlier than the last stamp
     already issued for the tenant (`ReceiptClockRegressionError`);
  2. a BEFORE INSERT trigger on `ontology_receipt_log`, installed on BOTH
     engines, rejects the same condition in the DATABASE, so a direct SQL insert
     that bypasses this module is refused too;
  3. every stamped row is chained (`prev_hash`/`hash`) into one per-tenant
     ledger, so a receipt time altered after the fact is DETECTABLE on read even
     if it evaded both.

-- and none of the three depends on the wall clock being honest, only on it not
going backwards.

THE CLOCK SEAM, STATED PLAINLY.
`ReceiptLedger` takes its clock as a CONSTRUCTOR argument (defaulting to the
system UTC clock) so tests can drive receipt times deterministically. This is a
trust boundary and it is not free: a process that constructs the ledger with a
lying clock gets lying receipt times. It is nonetheless categorically different
from the audited defect -- a per-write `recorded_at` parameter lets any caller
assert a different lie on every row, whereas a construction-time clock is a
single, process-wide, reviewable substitution that STILL cannot go backwards
(rule 1 above applies to a fake clock exactly as it does to a real one). What
this design does not provide is defence against a hostile operator of the
Milexium process itself; that needs signed checkpoint roots anchored outside the
database, which is named as a limitation in the packet rather than implied here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field

from themis.canonical.time import UtcDateTime, _require_utc

# THE SINGLE TIMESTAMP RENDERING IN THIS REPOSITORY FOR POINT-IN-TIME READS.
# Imported, not re-implemented: `themis/core/feature_store.py` established that
# the strict `<` as-of predicate is only correct if lexicographic order equals
# chronological order, which requires six fixed fractional digits (a bare
# `isoformat()` elides them at zero, and on PostgreSQL a TEXT comparison runs
# under the database collation rather than byte order -- under this repository's
# dev collation '...T09:14:03.500000+00:00' sorts BEFORE '...T09:14:03+00:00').
# A second convention here would be a second chance to get that wrong.
from themis.core.feature_store import _iso_utc as iso_receipt  # noqa: PLC2701

__all__ = [
    "iso_receipt",
    "ReceiptClock",
    "system_utc_clock",
    "ReceiptStamp",
    "ReceiptClockRegressionError",
    "CallerSuppliedReceiptError",
]


class ReceiptClock(Protocol):
    """A source of UTC instants for receipt stamping."""

    def __call__(self) -> datetime: ...  # pragma: no cover - structural


def system_utc_clock() -> datetime:
    """The default receipt clock: this process's UTC wall clock."""
    return datetime.now(timezone.utc)


class ReceiptClockRegressionError(RuntimeError):
    """A stamp was requested with a clock reading earlier than one already
    issued for this tenant.

    Its own type because the remedy is operational, not a caller fix: the
    machine's clock stepped backwards (an NTP correction, a VM restore, a
    daylight-saving bug in a wrapper), and continuing would silently make the
    information set at an already-taken snapshot time enlargeable. Refusing the
    write is the safe failure: no evidence is destroyed and the condition is
    visible.
    """


class CallerSuppliedReceiptError(TypeError):
    """A caller attempted to supply a receipt time.

    Raised only by defensive paths that accept **kwargs. The primary defence is
    that no receipt parameter EXISTS on any store method -- a conformance test
    reads the signatures back with `inspect.signature` rather than trusting this
    docstring, so the guarantee survives a future method being added.
    """


class ReceiptStamp(BaseModel):
    """When Milexium received a row, and its position in the tenant's single
    total receipt order.

    TWO FIELDS, NOT ONE, and the second is what makes the ordering total.
    Several rows written in the same millisecond share a `receipt_time`; ties on
    a timestamp are exactly where "latest wins" resolution goes ambiguous and
    two readers disagree. `receipt_sequence` is assigned by the ledger from what
    is already stored (never by a caller, never by an engine-specific
    AUTOINCREMENT -- ADR-0002's portable-DDL rule), so append order is a property
    of the stored rows readable by anything, not just this package. It is the
    same reasoning `PersistentFeatureStore.write` records for `write_sequence`,
    applied across ALL ontology streams at once rather than per feature series:
    a fact, a relationship, an event and an action written in that order have
    strictly increasing sequences, so a snapshot can be cut between any two of
    them unambiguously.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_time: UtcDateTime = Field(
        description=(
            "When Milexium received this row. Assigned by the writer. There is "
            "no store method that accepts it."
        )
    )
    receipt_sequence: int = Field(
        ge=1,
        description=(
            "Position in this tenant's single monotonic receipt order, across "
            "every ontology stream. 1-based, gapless, assigned by the ledger."
        ),
    )

    @property
    def iso(self) -> str:
        """The stored form: fixed-width ISO-8601 UTC. See `iso_receipt`."""
        return iso_receipt(self.receipt_time)

    def precedes(self, as_of: datetime) -> bool:
        """Whether a point-in-time read at `as_of` may see the stamped row.

        STRICTLY earlier -- the same rule, spelled the same way, as
        `themis/core/feature_store.FeatureStore.get_feature`. A row stamped
        exactly at `as_of` is NOT visible: the decision instant is the boundary,
        and a fact that arrived in the same instant the decision was taken
        cannot be shown to have informed it.

        This method is the OBJECT-layer restatement of a rule the DATABASE
        already enforces as a WHERE clause. It exists so an in-memory snapshot
        built without a database obeys the identical boundary, and so the
        boundary can be asserted twice from two independent implementations --
        not so the SQL can be relaxed and this relied on instead.
        """
        _require_utc(as_of)
        return self.receipt_time < as_of


def clock_regression_message(previous: datetime, current: datetime) -> str:
    return (
        f"receipt clock went backwards: last stamp was {iso_receipt(previous)}, "
        f"this reading is {iso_receipt(current)}. Refusing the write -- accepting "
        "it would let a fact be inserted before an already-taken snapshot's "
        "boundary and silently enlarge a historical information set."
    )


def next_stamp(
    *, previous: ReceiptStamp | None, clock: Callable[[], datetime]
) -> ReceiptStamp:
    """Produce the next stamp in a tenant's receipt order. PURE apart from the
    injected clock: it reads no database and holds no state, so the SQLite and
    PostgreSQL stores share one implementation of the monotonicity rule rather
    than two that can drift (the same reasoning
    `themis/canonical/lifecycle.next_transition` records).

    Equal timestamps are ACCEPTED -- two rows can genuinely arrive in the same
    microsecond, and `receipt_sequence` still orders them. Only a strictly
    EARLIER reading is refused.
    """
    now = clock()
    _require_utc(now)
    if previous is None:
        return ReceiptStamp(receipt_time=now, receipt_sequence=1)
    if now < previous.receipt_time:
        raise ReceiptClockRegressionError(
            clock_regression_message(previous.receipt_time, now)
        )
    return ReceiptStamp(
        receipt_time=now, receipt_sequence=previous.receipt_sequence + 1
    )
