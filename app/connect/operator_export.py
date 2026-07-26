"""Adapter: a generic operator trip export (CSV/Parquet-shaped dict rows)
-> ServiceRequest + Outcome (v0.1).

Status: **Exists** (v0.1), **Demonstrated on synthetic exports only**. No real
operator data exists anywhere in this repository and none has ever been
received. Nothing here may be promoted to "Validated" -- that requires
consented operator data against a declared baseline, per
knowledge/architecture/decisions/0001-adopt-expansion-blueprint-and-control-plane.md.

WHY THIS ADAPTER IS DIFFERENT FROM ITS SIBLINGS
`reference_agency_trips.py`, `tlc_trips.py`, `tides_trips.py`, `gtfs_flex.py`
and `gtfs_realtime.py` each map ONE published schema whose columns are known in
advance. This adapter maps something that has no schema yet: whatever an agency
can actually get out of its scheduling system. So instead of a fixed header it
defines a *minimum field list* (the smallest set that makes a deadhead/late-
trip teardown possible), accepts an explicit `column_map` from the operator's
own header onto that list, and treats everything else as an extension.

The intake contract an agency reads before sending anything is
`knowledge/docs/OPERATOR_DATA_INTAKE.md`. This module is the enforcement of that
document, not a substitute for it.

FAIL CLOSED ON PII -- the single most important behaviour here
A trip export produced by a scheduling system is exactly where rider names,
phone numbers, home addresses and Medicaid ids leak out, because those columns
sit next to the operational ones in the same table. This adapter therefore
QUARANTINES any row whose export carries such a column -- it does not import
the row and quietly ignore the column. Three separate checks:

1. **Column name** -- a column classified as a direct identifier (personal
   name, email, phone, street address, national/insurance/medical id, date of
   birth, medical or eligibility detail) quarantines the row, *whether or not
   that column has a value in this row*. The presence of the column means the
   export shape carries PII; the agency needs to drop the column at source, and
   an all-blank column in the sample would otherwise hide a populated one in
   the full extract.
2. **Value** -- any cell in any column that contains an email address
   quarantines the row, so renaming `email` to `contact_1` does not defeat (1).
3. **Zone shape** -- a `pickup_zone`/`dropoff_zone` value shaped like a full
   street address ("123 Main St") quarantines the row. Zones are the whole
   point: a street address is a rider's home.

Two deliberate deviations from the sibling adapters, both in the direction of
retaining less:

- **The quarantined raw row is redacted, not verbatim.** `QuarantinedRow`
  normally preserves the raw row exactly so it can be inspected and re-run. For
  a PII quarantine that would copy the rider's name straight into whatever sink
  the caller writes quarantines to -- the opposite of the point. Only the
  offending columns' values are replaced with `REDACTION_MARKER`; every other
  column is preserved verbatim, and the quarantine reason names each offending
  column so the operator knows exactly what to strip.
- **Unmapped columns are recorded by NAME ONLY, never by value.** The siblings
  put the source value in `SemanticLossRecord.source_value` for unmapped
  extensions. Here an unrecognised column is precisely where unanticipated
  personal data would hide, so `source_value` is always `None` for an
  `unmapped_extension`. Nothing is silently dropped (ADR-0007 is satisfied by
  recording the column), but nothing unrecognised is retained either.

GRADUATED NORMALISATION -- repair what is unambiguous, quarantine what is not
Failing closed is right for PII and for genuine ambiguity. Applied to *cosmetic*
defects it is merely brittle: an export whose only sin is a trailing space in
every zone code would quarantine in full, and "your data is malformed" is not a
diagnosis an operator can act on. So this adapter takes a graduated position:

- **Unambiguously repairable** -> repair it, and record a `coerced`
  SemanticLossRecord naming the original value, the repaired value and the rule
  that fired (`REPAIR_RULES`). Every repair is therefore auditable and
  reversible in review; none of them is silent. Reason text begins
  `repair[<rule id>] <original> -> <repaired>.` so a batch can be tallied by
  rule (`repair_rule_of`, used by `app.connect.ingest_report`).
- **Genuinely ambiguous** -> quarantine, exactly as before. `03/04/2026` with no
  declared locale is NOT repairable: DD/MM and MM/DD are both plausible and
  picking one silently is the failure mode this whole module exists to avoid.
  `13/04/2026` *is* repairable, because a 13th month does not exist, so only one
  reading survives -- and the record says which reading was inferred and why.
- **PII** -> unchanged, and still checked FIRST, before any repair runs. A row
  that carries a direct identifier is rejected on that ground even when it is
  also repairable; the repair layer never gets to see it.

Two refusals inside the same feature are worth naming because they look like
omissions: a date with no time-of-day is repaired for `requested_at` (a booking
date is genuinely day-granular, and it is the anchor, not the measurement) and
REFUSED for `scheduled_pickup_at`/`actual_pickup_at`, where anchoring at
midnight would invent precisely the number an on-time analysis is about; and an
epoch integer is refused outright, because seconds-versus-milliseconds is a
guess and the value carries no offset to check it against.

Structural artefacts get their own quarantine reasons rather than being reported
as data defects: a header row repeated mid-file (what concatenating twelve
monthly extracts produces) and a wholly empty row are recognised as *file*
problems, so the ingest report can separate "8% of your rows are bad" from "32%
of your rows are repeated headers".

RIDER IDENTITY
`rider_ref` is OPTIONAL and we ask operators not to send it. If it is sent it
must be the operator's own opaque internal client id; it is tokenised on ingest
as `sha256(value)[:24]` -- the same construction the sibling adapters use -- and
the input is never stored, never echoed into a semantic-loss record, and never
written to a canonical field. Honest limitation: an unsalted hash of a small id
space is brute-forceable, so this is a pseudonym, not anonymisation. That is a
reason to omit the column, and the document says so.

WHAT IT PRODUCES
`OperatorTripRecord`, a Connect-layer composite holding the two canonical
entities one exported trip actually is -- a `ServiceRequest` (the booking) and
an `Outcome` (what happened to it). The composite is NOT a new canonical
entity: it is a transport container for a batch handoff to
`MX-H-DEADHEAD-TEARDOWN-003`.

THE VEHICLE/RUN REFERENCE NOW LANDS ON THE OUTCOME (ADR-0043)
ADR-0038 shipped this adapter and surfaced, in its own consequences, that
`vehicle_ref`/`run_ref` -- the one field the deadhead teardown chains on
(ADR-0039 measures deadhead by chaining ONE vehicle's consecutive trips) -- had
no canonical home. It was carried on the Connect-layer composite only and
recorded as a `dropped` semantic loss on EVERY row, so it survived the
in-memory handoff and would not have survived a write to MilexiumDB. ADR-0043
gave it a home: two additive nullable columns on `outcomes`, because which
vehicle performed a trip is a fact about what HAPPENED, sitting beside
`deadhead_minutes`, the field derived from chaining it.

This adapter therefore populates `Outcome.vehicle_ref`/`Outcome.run_ref`
directly and NO LONGER reports the reference as dropped. That second half is
not bookkeeping: a loss list that keeps reporting a field it actually persists
teaches every reader to discount it, which costs more than the record was ever
worth. The composite still exposes `vehicle_ref`/`run_ref` for existing
callers; they are now the same fact as the outcome's, set from one source.

What legitimately REMAINS lost is narrower, and is still recorded on every row
that carries a reference: the reference is a LABEL, not a resolved entity.
`Outcome.vehicle_ref` is the operator's own unit number and `Outcome.run_ref`
their own run/block id -- plain strings by design, with no foreign key to
`vehicles`, `blocks` or `run_pieces` and no such row minted here, because the
minimum field list carries nothing to build one from. The concrete cost for the
teardown: trips can be grouped by the label and the gaps between consecutive
trips measured, but the run's pull-out and pull-in are unknown, so empty time
before the first trip and after the last one is invisible rather than zero.

ABSENCE STAYS ABSENT. At least one of the two columns is required (a trip
naming neither cannot be torn down at all, so it is quarantined), but the OTHER
one is routinely missing, and a missing reference is written as NULL -- never
back-filled from its sibling, never defaulted to a string. ADR-0039's
`unattributable` bucket exists precisely so unattributed empty time stays
visible; a fabricated run id would attribute it to a run that did not incur it.

MODELLING JUDGMENTS WORTH RECORDING (they are judgment, not derivation)
- **Terminal status is materialised directly.** A historical export describes
  finished trips, so `ServiceRequest.status` is set to the terminal state the
  outcome implies (COMPLETED / NO_SHOW / DENIED / CANCELLED) rather than the
  REQUESTED the siblings use. The intermediate lifecycle transitions
  (`app.canonical.state_machine`) genuinely happened in the operator's
  system and were never observed by Milexium; that absence is recorded as a
  `coerced` semantic loss on every row, so nobody mistakes a materialised
  terminal state for a replayable lifecycle.
- **`Outcome.on_time` is left None.** Whether a pickup was on time depends on
  the agency's on-time window (commonly -0/+30 minutes, but it is a policy
  parameter, not a fact), which no export carries. Computing it would be a
  guess dressed as a measurement.
- **`Outcome.excess_ride_time_minutes` / `deadhead_minutes` are left None.**
  Both are derived by chaining trips on a vehicle, which is the teardown's job,
  not a single row's.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from typing import Mapping

from pydantic import BaseModel, ConfigDict, model_validator

from app.canonical import (
    BitemporalMeta,
    Outcome,
    RequestId,
    RequestTimes,
    ServiceRequest,
    ServiceRequestState,
    TenantId,
    new_id,
)
from app.connect.adapter import AdapterResult, QuarantinedRow, SemanticLossRecord

# --------------------------------------------------------------------------
# The minimum field list. knowledge/docs/OPERATOR_DATA_INTAKE.md publishes exactly this.
# --------------------------------------------------------------------------

CANONICAL_COLUMNS: tuple[str, ...] = (
    "trip_ref",
    "rider_ref",
    "requested_at",
    "scheduled_pickup_at",
    "actual_pickup_at",
    "pickup_zone",
    "dropoff_zone",
    "vehicle_ref",
    "run_ref",
    "outcome",
)
"""Every column this adapter understands. Anything else is an extension."""

REQUIRED_COLUMNS: tuple[str, ...] = (
    "trip_ref",
    "requested_at",
    "scheduled_pickup_at",
    "pickup_zone",
    "dropoff_zone",
    "outcome",
)
"""Absent or blank in any of these and the row is quarantined, never defaulted."""

VEHICLE_OR_RUN_COLUMNS: tuple[str, ...] = ("vehicle_ref", "run_ref")
"""At least one is required: chaining a vehicle's consecutive trips is what
makes deadhead measurable, so a trip that names neither cannot be torn down."""

OPTIONAL_COLUMNS: tuple[str, ...] = ("rider_ref", "actual_pickup_at")
"""`actual_pickup_at` becomes required when `outcome` is `served`."""

OUTCOME_VALUES: tuple[str, ...] = ("served", "no_show", "denied", "cancelled")

REDACTION_MARKER = "<redacted by Milexium on quarantine: direct identifier, not retained>"

_OUTCOME_TO_STATE: dict[str, tuple[ServiceRequestState, bool]] = {
    "served": (ServiceRequestState.COMPLETED, True),
    "no_show": (ServiceRequestState.NO_SHOW, False),
    "denied": (ServiceRequestState.DENIED, False),
    "cancelled": (ServiceRequestState.CANCELLED, False),
}

# Documented synonyms -- an explicit, recorded mapping, not a guess. Keys are
# normalised (lowercase, alphanumerics only). Anything outside this table is
# quarantined rather than bucketed by resemblance.
_OUTCOME_SYNONYMS: dict[str, str] = {
    "served": "served",
    "completed": "served",
    "complete": "served",
    "performed": "served",
    "delivered": "served",
    "noshow": "no_show",
    "missed": "no_show",
    "denied": "denied",
    "denial": "denied",
    "refused": "denied",
    "rejected": "denied",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "cancel": "cancelled",
    "cancellation": "cancelled",
}


# --------------------------------------------------------------------------
# PII classification
# --------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[^@\s,;]+@[^@\s,;]+\.[A-Za-z]{2,}")
_HOUSE_NUMBER_RE = re.compile(r"^\s*\d+[A-Za-z]?\s+\S")

_STREET_SUFFIXES = frozenset(
    {
        "st",
        "street",
        "ave",
        "av",
        "avenue",
        "rd",
        "road",
        "dr",
        "drive",
        "ln",
        "lane",
        "blvd",
        "boulevard",
        "ct",
        "court",
        "pl",
        "place",
        "ter",
        "terrace",
        "pkwy",
        "parkway",
        "hwy",
        "highway",
        "cres",
        "crescent",
        "close",
        "way",
        "apt",
        "apartment",
        "unit",
        "suite",
        "ste",
    }
)

# A "name" column is only flagged when it is a bare name column or when a
# person word sits directly against the word "name". This is deliberately
# tighter than `"name" in column`, which would quarantine ordinary transit
# columns like route_name / zone_name / stop_name and make the check unusable.
_NAME_QUALIFIERS = (
    "rider",
    "client",
    "passenger",
    "customer",
    "patient",
    "member",
    "driver",
    "contact",
    "caregiver",
    "carer",
    "guardian",
    "emergency",
    "applicant",
    "traveler",
    "traveller",
    "pax",
    "attendant",
    "escort",
    "first",
    "last",
    "middle",
    "given",
    "full",
    "legal",
    "preferred",
    "maiden",
    "family",
)
_BARE_NAME_COLUMNS = frozenset(
    {"name", "names", "fullname", "surname", "forename", "firstname", "lastname", "givenname", "legalname"}
)

_EMAIL_COLUMNS = frozenset({"mail", "mails", "emails", "mailto"})
_PHONE_COLUMNS = frozenset(
    {
        "mobile",
        "mobileno",
        "mobilenumber",
        "cell",
        "cellno",
        "cellnumber",
        "tel",
        "telno",
        "telnumber",
        "contactnumber",
        "contactno",
        "homenumber",
    }
)
_ADDRESS_COLUMNS = frozenset({"apt", "aptno", "apartment", "housenumber", "houseno", "postaladdress"})

_ID_SUBSTRINGS = (
    "socialsecurity",
    "nationalid",
    "nationalinsurance",
    "medicaid",
    "medicare",
    "nhsnumber",
    "medicalrecord",
    "patientid",
    "insurance",
    "policynumber",
    "passport",
    "driverlicen",
    "driverslicen",
)
_ID_COLUMNS = frozenset({"ssn", "ssnno", "ssnumber", "nino", "ninumber", "mrn", "sin", "nhsno"})

_MEDICAL_SUBSTRINGS = (
    "diagnosis",
    "medicalcondition",
    "healthcondition",
    "disability",
    "impairment",
    "eligibilit",
)

# --------------------------------------------------------------------------
# The repair vocabulary
# --------------------------------------------------------------------------

REPAIR_REASON_PREFIX = "repair["
"""Every repair's `SemanticLossRecord.reason` starts `repair[<rule id>] `. The
disposition is the existing `coerced` -- this is not a parallel mechanism, it is
the mechanism ADR-0007 already defines, with a machine-readable tag so a batch
can be tallied by rule without parsing prose."""

REDACTED_IN_REPAIR = "<value not retained -- rider identifier>"
"""A repair on the optional `rider_ref` column names the RULE and never the
value, on either side of the arrow. The whole point of that column's handling is
that the operator's client id does not survive ingest; a repair record that
quoted it would defeat it more thoroughly than storing it would."""

REPAIR_RULES: dict[str, str] = {
    "trim_whitespace": (
        "surrounding whitespace (including non-breaking and zero-width spaces, which "
        "survive a spreadsheet round-trip invisibly) removed from a mapped value"
    ),
    "integral_float_identifier": (
        "an identifier or zone that arrived as an integral float ('412.0', '90210.0') -- what a "
        "nullable integer column becomes on a pandas/Parquet round-trip -- read as the integer"
    ),
    "enum_synonym": (
        "an outcome value mapped onto the canonical vocabulary through the adapter's published "
        "synonym table, case- and separator-insensitively"
    ),
    "iso8601_variant": (
        "a timestamp whose date is already unambiguous (four-digit year first) but is spelled in a "
        "form the ISO-8601 parser rejects -- slash separators, unpadded month/day/hour"
    ),
    "iso8601_utc_designator": (
        "a trailing textual UTC designator ('... UTC', '... GMT') read as the +00:00 offset it names"
    ),
    "twelve_hour_clock": "a 12-hour clock time with an am/pm suffix read onto the 24-hour clock",
    "date_order_ddmm": (
        "a slash/dot/dash date read as DAY-first because the first component exceeds 12, so "
        "month-first cannot parse it at all -- the only reading that survives, never a locale guess"
    ),
    "date_order_mmdd": (
        "a slash/dot/dash date read as MONTH-first because the second component exceeds 12, so "
        "day-first cannot parse it at all -- the only reading that survives, never a locale guess"
    ),
    "requested_at_date_only": (
        "a booking DATE with no time-of-day anchored at 00:00 UTC. Applied to requested_at only; "
        "refused for the pickup columns, where midnight would invent the measurement itself"
    ),
    "boolean_like": (
        "a yes/no flag written as Y/YES/TRUE/T/1 or N/NO/FALSE/F/0 read as a boolean. Implemented "
        "and tested as a primitive, DELIBERATELY WIRED TO NO COLUMN -- see coerce_boolean_like()"
    ),
}
"""Every repair this adapter is willing to make, and exactly what each one does.
An operator (or a reviewer) can read this table and know the complete set of
ways their values may have been altered. Anything not in it is quarantined."""

_TRIMMABLE = (
    " \t\r\n\v\f"
    "\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006"
    "\u2007\u2008\u2009\u200a\u202f\u205f\u3000"
    "\u200b\u200c\u200d\ufeff"
)
"""Unicode whitespace plus the zero-width characters a spreadsheet export leaves
behind. `str.strip()` alone misses the zero-width ones, which is how a column
that looks identical to the eye fails an equality check."""

REPEATED_HEADER_MARKER = "the row repeats the export's own header"
EMPTY_ROW_MARKER = "the row is entirely empty"
AMBIGUOUS_DATE_MARKER = "day-first and month-first are both valid readings"
DATE_ONLY_PICKUP_MARKER = "carries a date with no time of day"
NAIVE_TIMESTAMP_MARKER = "no UTC offset"
"""Stable phrases the adapter puts in its own reason text so
`app.connect.ingest_report` can classify a verdict without guessing at
prose. They are exported constants rather than literals in two modules for the
obvious reason: a phrase that drifts silently is how a report starts lying."""

RAGGED_EXTRA_COLUMN_LABEL = "<unnamed extra columns beyond the header row>"
"""`csv.DictReader` collects a ragged row's surplus cells under the key `None`.
They are recorded under this label -- name only, values never retained, same as
any other unrecognised column -- rather than under the string "None"."""

_HEADER_ECHO_MIN_COLUMNS = 3
_HEADER_ECHO_MIN_SHARE = 0.6
"""A row is treated as a repeated header when at least three of its populated
cells equal their own column name and those matches are at least 60% of the
populated cells. Both thresholds exist so a legitimate row that happens to carry
one self-describing value ("outcome" is not a plausible trip_ref, but "zone" as
a zone label is) is not mistaken for a header."""

PII_CATEGORIES: tuple[str, ...] = (
    "personal name",
    "email address",
    "phone number",
    "street address",
    "national, insurance or medical identifier",
    "date of birth",
    "medical or eligibility detail",
)
"""The categories the intake document tells operators to strip before sending."""


def _normalise(text: object) -> str:
    """Lowercase, alphanumerics only: 'Rider Name' / 'rider_name' / 'RIDER-NAME'
    all collapse to 'ridername', so header cosmetics cannot defeat the check."""
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def classify_pii_column(column: str) -> str | None:
    """Return the PII category a column name declares, or None.

    Name-based classification only. It is a backstop for
    `knowledge/docs/OPERATOR_DATA_INTAKE.md`, not a general PII scanner: a column called
    `notes` holding a rider's name in free text will not be caught here (its
    value is never retained either -- see the module docstring).
    """

    norm = _normalise(column)
    if not norm:
        return None
    if "email" in norm or norm in _EMAIL_COLUMNS:
        return "email address"
    if "phone" in norm or "fax" in norm or norm in _PHONE_COLUMNS:
        return "phone number"
    if "addr" in norm or "street" in norm or norm in _ADDRESS_COLUMNS:
        return "street address"
    if norm in _ID_COLUMNS or any(token in norm for token in _ID_SUBSTRINGS):
        return "national, insurance or medical identifier"
    if "birth" in norm or norm in {"dob", "bday"}:
        return "date of birth"
    if any(token in norm for token in _MEDICAL_SUBSTRINGS):
        return "medical or eligibility detail"
    if norm in _BARE_NAME_COLUMNS or any(
        qualifier + "name" in norm or "name" + qualifier in norm for qualifier in _NAME_QUALIFIERS
    ):
        return "personal name"
    return None


def _normalise_outcome(value: str) -> str:
    """Deliberately narrower than `_normalise`: separators are cosmetic in an
    outcome value ('No Show' == 'no_show' == 'no-show') but any other character
    is not, so 'SERVED?' does NOT become 'served'. A question mark is an
    operator flagging uncertainty; resolving it for them would be a guess."""
    text = value.strip().lower()
    for separator in (" ", "-", "_", "."):
        text = text.replace(separator, "")
    return text


def _contains_email(value: object, _depth: int = 0) -> bool:
    """True when an email address hides anywhere in a cell's value.

    Recurses into list/tuple/set/dict cells, which a plain `isinstance(value,
    str)` check would wave through. That is not hypothetical: `csv.DictReader`
    hands a RAGGED row's surplus cells over as a *list* under the key `None`, so
    an email in a column past the end of the header would have bypassed the PII
    gate entirely. Depth-limited because the check must not be the thing that
    crashes ingest.
    """

    if isinstance(value, str):
        return bool(_EMAIL_RE.search(value))
    if _depth >= 4:
        return False
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_email(item, _depth + 1) for item in value)
    if isinstance(value, Mapping):
        return any(
            _contains_email(key, _depth + 1) or _contains_email(item, _depth + 1)
            for key, item in value.items()
        )
    return False


def looks_like_street_address(value: object) -> bool:
    """A narrow heuristic for the one mistake that actually happens: an
    operator pipes their address column into the zone column.

    Requires BOTH a leading house number and a street-type token, so ordinary
    zone labels ('Zone 12', 'NW-3', 'Downtown', 'Main Street Corridor') pass.
    It is not a general address detector and is not claimed to be one.
    """

    if not isinstance(value, str) or not _HOUSE_NUMBER_RE.match(value):
        return False
    tokens = [token.strip(".,").lower() for token in value.split()]
    return any(token in _STREET_SUFFIXES for token in tokens)


# --------------------------------------------------------------------------
# Row-level helpers
# --------------------------------------------------------------------------


class _UnmappableValue(ValueError):
    """Internal signal that a field value cannot become canonical; caught in
    parse() and turned into a QuarantinedRow rather than propagating."""

    def __init__(self, message: str, field: str) -> None:
        super().__init__(message)
        self.field = field


class _AmbiguousValue(_UnmappableValue):
    """A value that has more than one valid reading. Quarantined like any other
    unmappable value -- the separate type exists so the ambiguity is impossible
    to downgrade into a repair by a later edit."""


def _is_null(value: object) -> bool:
    """The null vocabulary a real export arrives with: None, and the
    not-equal-to-itself nulls pandas uses (NaN in a string column, NaT in a
    timestamp column -- note `pandas.NaT` IS a datetime instance, so an
    isinstance check alone lets one through and `str(nan)` is the very
    plausible-looking trip_ref "nan"). `pandas.NA` raises on truthiness rather
    than comparing, which is caught and treated as null. Mirrors
    `app.replay.teardown._is_null`, which learned the same lesson."""

    if value is None:
        return True
    try:
        if value != value:
            return True
    except (TypeError, ValueError):
        return True
    return False


def _trimmed(text: str) -> str:
    """`str.strip()` plus the zero-width characters it leaves behind. A cell
    ending in U+200B looks identical to a clean one and compares unequal to it,
    which is how an operator's zone codes split into two vocabularies."""
    return text.strip(_TRIMMABLE)


def _present(value: object) -> bool:
    """A CSV cell is absent when the key is missing, the value is null (None, or
    a pandas NaN/NaT/NA), or the string is empty/whitespace once trimmed (the
    empty-string null convention CSV uses)."""
    return not _is_null(value) and _trimmed(str(value)) != ""


def coerce_boolean_like(value: object) -> bool | None:
    """A yes/no flag as an operator writes it -> a bool, or None if it is not
    one of the accepted spellings.

    DELIBERATELY WIRED TO NO COLUMN. The v0.1 minimum field list contains no
    boolean field, and the one enum-like column it does contain (`outcome`) has
    FOUR values: "Y" could only mean `served`, but "N" cannot choose between
    `no_show`, `denied` and `cancelled`, so reading a flag onto `outcome` would
    be the guess this module exists to refuse. Boolean flags genuinely do arrive
    in operator exports -- the test corpus' `OnTimeFlagVendor: "Y"` is exactly
    what they look like -- but they arrive in columns outside the field list,
    whose values are never retained (see the module docstring). So this is the
    repair rule for booleans, defined and tested, applied to nothing today, and
    ready for the day the field list gains a boolean column (a Program A/intake
    document change this module does not own).
    """

    if _is_null(value):
        return None
    if isinstance(value, bool):
        return value
    text = _trimmed(str(value)).lower()
    if text in {"y", "yes", "true", "t", "1"}:
        return True
    if text in {"n", "no", "false", "f", "0"}:
        return False
    return None


def _repair(
    rule: str,
    source_field: str,
    original: object,
    repaired: object,
    why: str,
    *,
    redact: bool = False,
) -> SemanticLossRecord:
    """One auditable repair, as the `coerced` semantic-loss record ADR-0007
    already defines. `redact=True` names the rule and suppresses BOTH sides of
    the arrow, used for the optional rider_ref column."""

    if rule not in REPAIR_RULES:  # pragma: no cover -- guards a typo, not a runtime path
        raise KeyError(f"{rule!r} is not a published repair rule; add it to REPAIR_RULES")
    if redact:
        change = f"{REDACTED_IN_REPAIR} -> {REDACTED_IN_REPAIR}"
        retained: str | None = None
    else:
        change = f"{original!r} -> {repaired!r}"
        retained = str(original)
    return SemanticLossRecord(
        source_field=source_field,
        source_value=retained,
        reason=f"{REPAIR_REASON_PREFIX}{rule}] {change}. {why}",
        disposition="coerced",
    )


def repair_rule_of(loss: SemanticLossRecord) -> str | None:
    """The repair rule a semantic-loss record reports, or None if it is not a
    repair. The one supported way to tally repairs over a batch; used by
    `app.connect.ingest_report` so no caller has to sniff prose."""

    if loss.disposition != "coerced" or not loss.reason.startswith(REPAIR_REASON_PREFIX):
        return None
    rule, closed, _ = loss.reason[len(REPAIR_REASON_PREFIX) :].partition("]")
    return rule if closed and rule in REPAIR_RULES else None


def resolve_intake_columns(
    raw_row: Mapping[str, object], column_map: Mapping[str, str]
) -> tuple[dict[str, tuple[str, object]], list[tuple[str, str, str]]]:
    """Map an operator's own header onto the canonical intake columns.

    Returns `({canonical: (source column, value)}, conflicts)` where a conflict
    is `(canonical, first source column, second source column)`. First-wins in
    the mapping, but the adapter QUARANTINES on any conflict rather than using
    the first -- the return shape keeps that decision at the call site instead of
    burying it here, and lets the ingest report diagnose exactly the columns the
    adapter reads without reimplementing this loop.
    """

    resolved: dict[str, tuple[str, object]] = {}
    conflicts: list[tuple[str, str, str]] = []
    for column, value in raw_row.items():
        if column is None:
            continue
        name = str(column)
        target = column_map.get(name) or (name if name in CANONICAL_COLUMNS else None)
        if target is None:
            continue
        if target in resolved:
            conflicts.append((target, resolved[target][0], name))
            continue
        resolved[target] = (name, value)
    return resolved, conflicts


def looks_like_repeated_header(raw_row: Mapping[str, object]) -> bool:
    """True when a row is the export's own header row appearing again mid-file.

    This is what concatenating twelve monthly extracts produces, and it is a
    FILE defect, not a data defect: reporting it as "twelve rows missing every
    required field" sends an operator hunting for a scheduling-system problem
    that does not exist. Recognised by populated cells that equal their own
    column name (normalised, so `PU Zone` matches `pu_zone`).
    """

    populated = [
        (str(column), value)
        for column, value in raw_row.items()
        if column is not None and _present(value)
    ]
    if len(populated) < _HEADER_ECHO_MIN_COLUMNS:
        return False
    echoes = sum(1 for column, value in populated if _normalise(value) == _normalise(column))
    return echoes >= _HEADER_ECHO_MIN_COLUMNS and echoes >= _HEADER_ECHO_MIN_SHARE * len(populated)


def _is_empty_row(raw_row: Mapping[str, object]) -> bool:
    return not any(_present(value) for value in raw_row.values())


# -- the timestamp repair engine -------------------------------------------
#
# Every rewrite below is reversible from its own record and, critically, is only
# applied when exactly ONE reading of the value survives. Where two readings
# survive the value is quarantined, never resolved by convention, locale, or
# what the neighbouring rows happened to look like.

_DATE_HEAD_RE = re.compile(r"^(\d{1,4})([-/.])(\d{1,2})\2(\d{1,4})(.*)$", re.S)
_COMPACT_DATE_RE = re.compile(r"^\d{8}$")
_TRAILING_UTC_RE = re.compile(r"^(.*?)[\s_]*(UTC|GMT|utc|gmt)$")
_AMPM_RE = re.compile(r"^(.*?)(\d{1,2}):(\d{2})(?::(\d{2}))?(\.\d+)?\s*([AaPp])\.?[Mm]\.?\s*$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?(\.\d+)?\s*(.*)$", re.S)

DATE_ONLY_ALLOWED_COLUMNS: tuple[str, ...] = ("requested_at",)
"""The only canonical column for which a date with no time-of-day is repaired
rather than quarantined. A booking date is genuinely day-granular in plenty of
scheduling systems and it is the ANCHOR of the row, not the thing being
measured; a pickup time anchored at midnight would fabricate the exact quantity
an on-time or headway analysis reports. `app.connect.tides_trips` makes the
same day-anchor judgment for the same reason, and records it the same way."""


def _canonical_date(column: str, text: str) -> tuple[str, str | None]:
    """A date component -> ('YYYY-MM-DD', rule id or None if already canonical).

    Raises `_AmbiguousValue` for the case this whole module is about: a
    slash/dot/dash date whose first two components are both <= 12, where DD/MM
    and MM/DD are both valid readings and nothing in the file says which.
    """

    match = _DATE_HEAD_RE.match(text)
    if match is None:
        raise _UnmappableValue(f"{text!r} is not a recognisable date", column)
    first, separator, middle, last, _ = match.groups()

    if len(first) == 4:
        year, month, day = int(first), int(middle), int(last)
        rule = None if (separator == "-" and len(middle) == 2 and len(last) == 2) else "iso8601_variant"
    elif len(last) == 4:
        year = int(last)
        a, b = int(first), int(middle)
        if a > 12 and b <= 12:
            day, month, rule = a, b, "date_order_ddmm"
        elif b > 12 and a <= 12:
            month, day, rule = a, b, "date_order_mmdd"
        elif a <= 12 and b <= 12:
            raise _AmbiguousValue(
                f"ambiguous date {text!r} in {column}: {AMBIGUOUS_DATE_MARKER} "
                f"(day-first it is day {a} of month {b}; month-first it is month {a} day {b} -- "
                f"{year}-{b:02d}-{a:02d} versus {year}-{a:02d}-{b:02d}, and nothing in the export "
                "says which). "
                "Milexium repairs a date only when one reading survives -- 13/04/2026 has no "
                "thirteenth month, so it is repaired; this one does not. Send ISO-8601 "
                "(2026-03-04) or tell us your export's date order and we will configure it "
                "explicitly rather than infer it",
                column,
            )
        else:
            raise _UnmappableValue(
                f"{text!r} in {column} has no valid reading: both leading components exceed 12",
                column,
            )
    else:
        raise _UnmappableValue(
            f"{text!r} in {column} carries no four-digit year; a two-digit year is a second "
            "ambiguity on top of the date order and is not repaired",
            column,
        )

    try:
        date(year, month, day)
    except ValueError as exc:
        raise _UnmappableValue(f"{text!r} in {column} is not a real calendar date: {exc}", column) from exc
    return f"{year:04d}-{month:02d}-{day:02d}", rule


def _canonical_timestamp_text(column: str, text: str) -> tuple[str, bool, list[str], str | None]:
    """A messy timestamp string -> (canonical ISO text, is_date_only, rewrites
    applied, dominant rule id).

    `rewrites` is prose for the audit record; `dominant rule` is the most
    semantically loaded rule that fired, so one repair record classifies the
    whole rewrite instead of emitting four records for one value.
    """

    rewrites: list[str] = []
    rules: list[str] = []
    work = text

    utc_word = _TRAILING_UTC_RE.match(work)
    if utc_word is not None and utc_word.group(1).strip():
        work = utc_word.group(1).rstrip() + "+00:00"
        rewrites.append(f"read the trailing {utc_word.group(2)!r} as the offset +00:00")
        rules.append("iso8601_utc_designator")

    ampm = _AMPM_RE.match(work)
    if ampm is not None:
        head, hour_text, minute, second, fraction, meridiem = ampm.groups()
        hour = int(hour_text)
        if hour < 1 or hour > 12:
            raise _UnmappableValue(
                f"{text!r} in {column} carries an am/pm suffix on the hour {hour}, which no "
                "12-hour clock has",
                column,
            )
        if meridiem.lower() == "a":
            hour = 0 if hour == 12 else hour
        else:
            hour = 12 if hour == 12 else hour + 12
        work = f"{head}{hour:02d}:{minute}:{second or '00'}{fraction or ''}"
        rewrites.append(f"read {hour_text}:{minute}{meridiem.lower()}m on the 24-hour clock")
        rules.append("twelve_hour_clock")

    if _COMPACT_DATE_RE.match(work):
        iso_date, tail = f"{work[0:4]}-{work[4:6]}-{work[6:8]}", ""
        date_rule: str | None = "iso8601_variant"
        rewrites.append(f"read the compact date {work!r} as {iso_date}")
    else:
        head_match = _DATE_HEAD_RE.match(work)
        if head_match is None:
            raise _UnmappableValue(
                f"unparseable {column} timestamp {text!r}: no recognisable date at the start "
                "(expected ISO-8601, e.g. 2026-03-04T08:15:00-05:00)",
                column,
            )
        date_text = work[: head_match.start(5)]
        tail = head_match.group(5)
        iso_date, date_rule = _canonical_date(column, date_text)
        if date_rule is not None:
            rewrites.append(f"read the date {date_text!r} as {iso_date}")
    if date_rule is not None:
        rules.append(date_rule)

    tail = tail.strip()
    if tail[:1] in {"T", "t"}:
        tail = tail[1:].strip()
    if not tail:
        dominant = _dominant_rule(rules)
        return iso_date, True, rewrites, dominant

    time_match = _TIME_RE.match(tail)
    if time_match is None:
        raise _UnmappableValue(
            f"unparseable {column} timestamp {text!r}: {tail!r} is not a recognisable time of day",
            column,
        )
    hour_text, minute, second, fraction, offset_text = time_match.groups()
    if len(hour_text) == 1:
        rewrites.append(f"zero-padded the hour {hour_text!r}")
        rules.append("iso8601_variant")
    time_part = f"{int(hour_text):02d}:{minute}:{second or '00'}{(fraction or '')[:7]}"
    work = f"{iso_date}T{time_part}{_canonical_offset(column, text, offset_text.strip())}"

    try:
        datetime.fromisoformat(work)
    except ValueError as exc:
        raise _UnmappableValue(
            f"unparseable {column} timestamp {text!r}: {exc} "
            "(expected ISO-8601, e.g. 2026-03-04T08:15:00-05:00)",
            column,
        ) from exc
    if not rewrites:
        rewrites.append(f"respelled {text!r} as ISO-8601")
        rules.append("iso8601_variant")
    return work, False, rewrites, _dominant_rule(rules)


def _canonical_offset(column: str, original: str, offset_text: str) -> str:
    """A UTC offset as an export writes it -> the ISO spelling, or '' when the
    value carries none (the caller then records the naive-is-UTC assumption)."""

    if not offset_text:
        return ""
    if offset_text in {"Z", "z"}:
        return "+00:00"
    match = re.fullmatch(r"([+-])(\d{2}):?(\d{2})?", offset_text)
    if match is None:
        raise _UnmappableValue(
            f"unparseable {column} timestamp {original!r}: {offset_text!r} is not a UTC offset",
            column,
        )
    sign, hours, minutes = match.groups()
    return f"{sign}{hours}:{minutes or '00'}"


_RULE_PRECEDENCE = (
    "date_order_ddmm",
    "date_order_mmdd",
    "twelve_hour_clock",
    "iso8601_utc_designator",
    "iso8601_variant",
)


def _dominant_rule(rules: list[str]) -> str | None:
    for candidate in _RULE_PRECEDENCE:
        if candidate in rules:
            return candidate
    return None


def _parse_timestamp(
    column: str, raw_value: object, *, allow_date_only: bool = False
) -> tuple[datetime, bool, list[SemanticLossRecord]]:
    """An exported timestamp -> (UTC datetime, was_naive, repairs recorded).

    Accepts a datetime (what a Parquet read yields) or a string (what a CSV
    export yields). A clean ISO-8601 string parses with no repair at all; a
    string that is ISO-8601 in *meaning* but not in spelling is repaired through
    `_canonical_timestamp_text` and every rewrite is recorded. A naive value is
    treated as UTC and the caller records the coercion -- the same simplification
    every sibling adapter makes, and a real hazard for a local-time export, which
    is why the intake document asks for an explicit offset.

    An int/float is REFUSED rather than read as a Unix epoch: seconds versus
    milliseconds is a guess, and an epoch integer carries no offset to check the
    guess against.
    """

    repairs: list[SemanticLossRecord] = []
    if isinstance(raw_value, datetime):
        value = raw_value
    elif isinstance(raw_value, str):
        text = _trimmed(raw_value)
        head = _DATE_HEAD_RE.match(text)
        date_only_shaped = _COMPACT_DATE_RE.match(text) is not None or (
            head is not None and not head.group(5).strip()
        )
        if not date_only_shaped:
            try:
                value = datetime.fromisoformat(text)
            except ValueError:
                canonical, _, rewrites, rule = _canonical_timestamp_text(column, text)
                value = datetime.fromisoformat(canonical)
                if rule is not None:
                    repairs.append(
                        _repair(
                            rule,
                            column,
                            text,
                            canonical,
                            "; ".join(rewrites)
                            + ". Every rewrite listed has exactly one valid reading; a value with "
                            "two is quarantined instead",
                        )
                    )
        else:
            canonical, _, rewrites, rule = _canonical_timestamp_text(column, text)
            if not allow_date_only:
                raise _UnmappableValue(
                    f"{column} {text!r} {DATE_ONLY_PICKUP_MARKER}. Milexium will not anchor a "
                    "pickup time at midnight: that would invent the exact quantity an on-time or "
                    "headway analysis reports. A date alone is accepted only for requested_at, "
                    "where day granularity is a real property of a booking rather than a "
                    "fabricated measurement",
                    column,
                )
            if rule is not None:
                repairs.append(_repair(rule, column, text, canonical, "; ".join(rewrites)))
            value = datetime.fromisoformat(canonical + "T00:00:00")
            repairs.append(
                _repair(
                    "requested_at_date_only",
                    column,
                    text,
                    value.isoformat(),
                    "a booking date with no time of day, anchored at 00:00 UTC. The time of day "
                    "is NOT known and has not been recovered -- any advance-notice figure derived "
                    "from this row is accurate to the day and no finer",
                )
            )
    else:
        raise _UnmappableValue(
            f"unparseable {column} timestamp {raw_value!r}: expected an ISO-8601 string or a "
            "datetime. A numeric value is not read as a Unix epoch: seconds versus milliseconds "
            "is a guess and the value carries no offset to check it against",
            column,
        )
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc), True, repairs
    return value.astimezone(timezone.utc), False, repairs


def _integral_float_text(value: object) -> str | None:
    """'412.0' / 412.0 -> '412'; anything else -> None.

    Deliberately narrow: only an exactly-integral float, and only in the
    identifier and zone columns. A value of 12.5 is left alone, because a
    fractional identifier means something this adapter does not understand and
    rounding it would invent an entity.
    """

    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else None
    if isinstance(value, str) and re.fullmatch(r"-?\d+\.0+", value):
        return str(int(float(value)))
    return None


def _tokenize_rider(rider_ref: str) -> str:
    """sha256 the operator's opaque client id. The input never reaches a
    canonical field, a semantic-loss record, or a log line."""
    digest = hashlib.sha256(rider_ref.encode("utf-8")).hexdigest()[:24]
    return f"riderref-{digest}"


def _synthetic_rider_ref(trip_ref: str) -> str:
    """When no rider column is sent (the state we ask for), rider_ref is a
    deterministic per-trip placeholder -- never a stable or joinable identity."""
    digest = hashlib.sha256(f"operator-export|{trip_ref}".encode("utf-8")).hexdigest()[:24]
    return f"operator-no-rider-{digest}"


class OperatorTripRecord(BaseModel):
    """One exported operator trip as the canonical entities it actually is.

    NOT a canonical entity and not a new contract: `app.canonical` owns the
    canonical model and this module does not extend it. This is a Connect-layer
    container so one `parse()` can return the request and its outcome together.

    `vehicle_ref`/`run_ref` are kept here for the callers written against
    ADR-0038, when this composite was the reference's ONLY home. Since ADR-0043
    they are no longer that home -- `Outcome.vehicle_ref`/`Outcome.run_ref` is,
    and it is the one that persists. `parse()` sets both from a single source so
    they cannot disagree; anything that has to survive a write to MilexiumDB
    should read the outcome's.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request: ServiceRequest
    outcome: Outcome
    vehicle_ref: str | None = None
    run_ref: str | None = None

    @model_validator(mode="after")
    def _outcome_belongs_to_request(self) -> "OperatorTripRecord":
        if self.outcome.request_id != self.request.request_id:
            raise ValueError("outcome.request_id must reference the request it accompanies")
        if self.outcome.tenant_id != self.request.tenant_id:
            raise ValueError("outcome.tenant_id must match the request's tenant")
        return self


class OperatorExportAdapter:
    """Maps one row of an operator trip export onto an `OperatorTripRecord`.

    `column_map` maps the operator's own header onto `CANONICAL_COLUMNS`, so an
    agency never has to rewrite its extract -- `{"BookingNo": "trip_ref", ...}`.
    A source column that is already a canonical name needs no entry.

    `recorded_at` is the import's transaction time (BitemporalMeta), distinct
    from the trip's valid-time fields -- the export has no notion of when
    Milexium ingested it.
    """

    adapter_name = "operator-trip-export"
    adapter_version = "0.1.0"

    def __init__(
        self,
        tenant_id: TenantId,
        *,
        recorded_at: datetime,
        column_map: dict[str, str] | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._recorded_at = recorded_at
        self._column_map = dict(column_map or {})

        unknown = sorted(set(self._column_map.values()) - set(CANONICAL_COLUMNS))
        if unknown:
            raise ValueError(
                f"column_map targets are not canonical intake columns: {', '.join(unknown)}; "
                f"valid targets are {', '.join(CANONICAL_COLUMNS)}"
            )
        targets = list(self._column_map.values())
        duplicated = sorted({target for target in targets if targets.count(target) > 1})
        if duplicated:
            raise ValueError(
                f"column_map sends more than one source column to the same canonical column: "
                f"{', '.join(duplicated)}"
            )

    @property
    def column_map(self) -> dict[str, str]:
        """A copy of the operator-header-to-canonical mapping this adapter runs
        with. Read by `app.connect.ingest_report` so a report diagnoses
        exactly the columns the adapter read, not a second guess at them."""
        return dict(self._column_map)

    # -- quarantine helpers -------------------------------------------------

    def _redacted(self, raw_row: dict, columns: list[object]) -> dict:
        """Preserve the row for re-run, minus the values that must not be kept."""
        redacted = dict(raw_row)
        for column in columns:
            if column in redacted:
                redacted[column] = REDACTION_MARKER
        return redacted

    def _pii_quarantine(
        self,
        raw_row: dict,
        findings: list[tuple[str, str]],
        redact_keys: list[object] | None = None,
    ) -> AdapterResult[OperatorTripRecord]:
        # `redact_keys` exists because a column's DISPLAY name is not always its
        # dict key: csv.DictReader's ragged-row cells live under the key None and
        # are reported under RAGGED_EXTRA_COLUMN_LABEL. Redacting by display name
        # would have missed exactly that cell -- the one holding an email nobody
        # named a column for.
        findings = sorted(findings)
        detail = "; ".join(f"{column} ({category})" for column, category in findings)
        keys = redact_keys if redact_keys is not None else [column for column, _ in findings]
        return AdapterResult(
            quarantine=QuarantinedRow(
                raw_row=self._redacted(raw_row, keys),
                reason=(
                    "rejected on ingest: the export carries direct rider/staff identifiers, which "
                    f"Milexium does not accept -- {detail}. Remove these column(s) at source and "
                    "re-send; see knowledge/docs/OPERATOR_DATA_INTAKE.md ('WHAT WE DO NOT WANT'). The offending "
                    "values were redacted from this quarantine record and were not retained"
                ),
                failed_field=findings[0][0],
            )
        )

    @staticmethod
    def _quarantine(raw_row: dict, reason: str, field: str | None = None) -> AdapterResult[OperatorTripRecord]:
        return AdapterResult(
            quarantine=QuarantinedRow(raw_row=dict(raw_row), reason=reason, failed_field=field)
        )

    # -- the contract -------------------------------------------------------

    def parse(self, raw_row: dict) -> AdapterResult[OperatorTripRecord]:
        # 1. PII, before anything else: a row carrying a direct identifier is
        #    rejected on that ground regardless of whatever else is wrong with it.
        findings: list[tuple[str, str]] = []
        redact_keys: list[object] = []
        for column, value in raw_row.items():
            display = RAGGED_EXTRA_COLUMN_LABEL if column is None else str(column)
            category = None if column is None else classify_pii_column(display)
            if category is None and _contains_email(value):
                category = "email address (found in the value, not the column name)"
            if category is not None:
                findings.append((display, category))
                redact_keys.append(column)
        if findings:
            return self._pii_quarantine(raw_row, findings, redact_keys)

        # 2. Structural artefacts of the FILE, not defects in the data. Named
        #    separately so a report can say "32% of your rows are repeated
        #    headers" instead of "32% of your rows are missing every field".
        if _is_empty_row(raw_row):
            return self._quarantine(
                raw_row,
                f"{EMPTY_ROW_MARKER}: every cell is blank. Nothing was imported and nothing is "
                "wrong with your scheduling system -- this is a trailing or interleaved blank "
                "line in the file, usually from a spreadsheet round-trip",
            )
        if looks_like_repeated_header(raw_row):
            return self._quarantine(
                raw_row,
                f"{REPEATED_HEADER_MARKER}: every populated cell holds its own column name. This "
                "is what concatenating several extracts produces -- the second and later files "
                "bring their header rows with them. It is a file-assembly artefact, not a data "
                "problem; strip the repeated header lines and re-send",
            )

        # 3. Resolve the operator's header onto the canonical column names.
        resolved, conflicts = resolve_intake_columns(raw_row, self._column_map)
        if conflicts:
            target, first, second = conflicts[0]
            return self._quarantine(
                raw_row,
                f"two source columns ({first!r} and {second!r}) both resolve to the "
                f"canonical column {target!r}; Milexium will not choose between them",
                target,
            )

        def source_of(canonical: str) -> str:
            return resolved[canonical][0] if canonical in resolved else canonical

        def value_of(canonical: str) -> object:
            return resolved[canonical][1] if canonical in resolved else None

        # 4. Zone columns must carry zones, not addresses. Still a PII check, and
        #    still ahead of every repair: the raw value AND its trimmed form are
        #    both tested, so no normalisation can be the thing that lets an
        #    address through.
        address_findings = [
            (source_of(zone_column), "street address (found in the value of a zone column)")
            for zone_column in ("pickup_zone", "dropoff_zone")
            if looks_like_street_address(value_of(zone_column))
            or looks_like_street_address(_trimmed(str(value_of(zone_column))))
        ]
        if address_findings:
            return self._pii_quarantine(raw_row, address_findings)

        # 5. Graduated normalisation. Only reached once every PII gate above has
        #    passed. Repairs rewrite the RESOLVED view; `raw_row` is untouched,
        #    so a quarantine still preserves exactly what the operator sent.
        repairs: list[SemanticLossRecord] = []
        for canonical, (source, value) in list(resolved.items()):
            repaired, records = self._normalise_value(canonical, source, value)
            if records:
                resolved[canonical] = (source, repaired)
                repairs.extend(records)

        # 6. Required fields -- absent means quarantined, never defaulted.
        missing = [column for column in REQUIRED_COLUMNS if not _present(value_of(column))]
        if missing:
            return self._quarantine(
                raw_row,
                "missing required field(s): "
                + ", ".join(f"{column} (source column {source_of(column)!r})" for column in missing),
                source_of(missing[0]),
            )

        if not any(_present(value_of(column)) for column in VEHICLE_OR_RUN_COLUMNS):
            return self._quarantine(
                raw_row,
                "neither vehicle_ref nor run_ref is present; chaining a vehicle's consecutive trips "
                "is what makes deadhead measurable, so a trip naming no vehicle or run cannot be "
                "analysed and is not imported",
                "vehicle_ref",
            )

        # 7. Times.
        naive_columns: list[str] = []
        times: dict[str, datetime] = {}
        try:
            for canonical in ("requested_at", "scheduled_pickup_at", "actual_pickup_at"):
                if canonical == "actual_pickup_at" and not _present(value_of(canonical)):
                    continue
                parsed, naive, time_repairs = _parse_timestamp(
                    source_of(canonical),
                    value_of(canonical),
                    allow_date_only=canonical in DATE_ONLY_ALLOWED_COLUMNS,
                )
                repairs.extend(time_repairs)
                if naive:
                    naive_columns.append(source_of(canonical))
                times[canonical] = parsed
        except _UnmappableValue as exc:
            return self._quarantine(raw_row, str(exc), exc.field)
        requested_at = times["requested_at"]
        scheduled_pickup_at = times["scheduled_pickup_at"]
        actual_pickup_at: datetime | None = times.get("actual_pickup_at")

        # 8. Outcome vocabulary -- an unknown value is quarantined, not bucketed.
        raw_outcome = str(value_of("outcome")).strip()
        canonical_outcome = _OUTCOME_SYNONYMS.get(_normalise_outcome(raw_outcome))
        if canonical_outcome is None:
            return self._quarantine(
                raw_row,
                f"unknown outcome value {raw_outcome!r} in source column {source_of('outcome')!r}; "
                f"Milexium accepts {', '.join(OUTCOME_VALUES)} (plus the documented synonyms) and "
                "will not guess which of them an unrecognised value means",
                source_of("outcome"),
            )
        status, served = _OUTCOME_TO_STATE[canonical_outcome]

        # 9. Cross-field consistency.
        if served and actual_pickup_at is None:
            return self._quarantine(
                raw_row,
                "outcome says the trip was served but actual_pickup_at is absent; a served trip with "
                "no observed pickup time cannot be measured against its schedule, and Milexium will "
                "not substitute the scheduled time for the actual one",
                source_of("actual_pickup_at"),
            )
        if scheduled_pickup_at < requested_at:
            return self._quarantine(
                raw_row,
                f"scheduled_pickup_at ({scheduled_pickup_at.isoformat()}) is before requested_at "
                f"({requested_at.isoformat()}); a trip cannot be scheduled before it was requested, "
                "so these timestamps are wrong or in different time zones",
                source_of("scheduled_pickup_at"),
            )
        if actual_pickup_at is not None and actual_pickup_at < requested_at:
            return self._quarantine(
                raw_row,
                f"actual_pickup_at ({actual_pickup_at.isoformat()}) is before requested_at "
                f"({requested_at.isoformat()}); a trip cannot be performed before it was requested, "
                "so these timestamps are wrong or in different time zones",
                source_of("actual_pickup_at"),
            )

        # 10. Map.
        trip_ref = str(value_of("trip_ref")).strip()
        vehicle_ref = str(value_of("vehicle_ref")).strip() if _present(value_of("vehicle_ref")) else None
        run_ref = str(value_of("run_ref")).strip() if _present(value_of("run_ref")) else None
        rider_sent = _present(value_of("rider_ref"))
        rider_ref = (
            _tokenize_rider(str(value_of("rider_ref")).strip()) if rider_sent else _synthetic_rider_ref(trip_ref)
        )

        semantic_loss = self._semantic_loss(
            raw_row=raw_row,
            resolved=resolved,
            trip_ref=trip_ref,
            rider_sent=rider_sent,
            vehicle_ref=vehicle_ref,
            run_ref=run_ref,
            canonical_outcome=canonical_outcome,
            raw_outcome=raw_outcome,
            status=status,
            served=served,
            actual_pickup_at=actual_pickup_at,
            naive_columns=naive_columns,
            repairs=repairs,
        )

        request_id = new_id(RequestId)
        request = ServiceRequest(
            request_id=request_id,
            tenant_id=self._tenant_id,
            rider_ref=rider_ref,
            pickup_zone=str(value_of("pickup_zone")).strip(),
            dropoff_zone=str(value_of("dropoff_zone")).strip(),
            mobility_device=None,
            times=RequestTimes(
                requested_at=requested_at,
                scheduled_pickup_at=scheduled_pickup_at,
                actual_pickup_at=actual_pickup_at if served else None,
            ),
            status=status,
            meta=BitemporalMeta(version=1, recorded_at=self._recorded_at),
        )
        outcome = Outcome(
            tenant_id=self._tenant_id,
            request_id=request_id,
            served=served,
            actual_pickup_at=actual_pickup_at if served else None,
            on_time=None,
            excess_ride_time_minutes=None,
            deadhead_minutes=None,
            # ADR-0043's columns, written here rather than left to the caller.
            # Both are `None` when the export did not carry them -- absent stays
            # absent, and the missing one is NEVER back-filled from its sibling.
            vehicle_ref=vehicle_ref,
            run_ref=run_ref,
        )
        record = OperatorTripRecord(
            request=request, outcome=outcome, vehicle_ref=vehicle_ref, run_ref=run_ref
        )
        return AdapterResult(record=record, semantic_loss=tuple(semantic_loss))

    # -- graduated normalisation -------------------------------------------

    _FLOAT_ID_COLUMNS: tuple[str, ...] = (
        "trip_ref",
        "rider_ref",
        "vehicle_ref",
        "run_ref",
        "pickup_zone",
        "dropoff_zone",
    )

    def _normalise_value(
        self, canonical: str, source: str, value: object
    ) -> tuple[object, list[SemanticLossRecord]]:
        """Repair one mapped cell's cosmetic defects, recording each one.

        Only the two rules that are safe on ANY value live here (whitespace and
        the integral-float identifier); the timestamp and outcome rules need the
        column's meaning and run in their own steps. `rider_ref` repairs are
        recorded with the value suppressed on both sides -- naming the rule is
        the audit, and quoting the operator's client id would defeat the
        tokenisation the column exists to get.
        """

        redact = canonical == "rider_ref"
        records: list[SemanticLossRecord] = []
        if _is_null(value):
            return value, records

        if isinstance(value, str):
            trimmed = _trimmed(value)
            if trimmed != value:
                if trimmed:
                    records.append(
                        _repair(
                            "trim_whitespace",
                            source,
                            value,
                            trimmed,
                            "surrounding whitespace only; the value itself is unchanged. Left in "
                            "place it would split one zone or vehicle vocabulary into two that "
                            "look identical and compare unequal",
                            redact=redact,
                        )
                    )
                value = trimmed

        if canonical in self._FLOAT_ID_COLUMNS:
            integral = _integral_float_text(value)
            if integral is not None:
                records.append(
                    _repair(
                        "integral_float_identifier",
                        source,
                        value,
                        integral,
                        "an identifier or zone code read as a whole number. A nullable integer "
                        "column becomes float64 on a pandas/Parquet round-trip, which turns the "
                        "id 412 into '412.0'; the fractional part is exactly zero, so the integer "
                        "reading is the only one, and leaving it would make the same id in a CSV "
                        "export and a Parquet export two different entities",
                        redact=redact,
                    )
                )
                value = integral

        return value, records

    # -- semantic loss ------------------------------------------------------

    def _semantic_loss(
        self,
        *,
        raw_row: dict,
        resolved: dict[str, tuple[str, object]],
        trip_ref: str,
        rider_sent: bool,
        vehicle_ref: str | None,
        run_ref: str | None,
        canonical_outcome: str,
        raw_outcome: str,
        status: ServiceRequestState,
        served: bool,
        actual_pickup_at: datetime | None,
        naive_columns: list[str],
        repairs: list[SemanticLossRecord],
    ) -> list[SemanticLossRecord]:
        # Repairs lead: they are the only entries that describe a change made to
        # the operator's OWN values, which is what a reviewer needs to see first.
        losses: list[SemanticLossRecord] = [
            *repairs,
            SemanticLossRecord(
                source_field="<lifecycle transitions between request and outcome>",
                source_value=None,
                reason=(
                    f"a historical export describes a finished trip, so status is materialised "
                    f"directly at the terminal state {status.value!r} implied by the outcome. The "
                    "intermediate transitions (requested -> negotiated -> scheduled -> in_progress) "
                    "happened inside the operator's scheduling system and were never observed by "
                    "Milexium: no intermediate ServiceRequest versions and no DecisionEvents exist "
                    "for this aggregate, so its history is not replayable, only its endpoint"
                ),
                disposition="coerced",
            ),
            SemanticLossRecord(
                source_field="<on-time determination>",
                source_value=None,
                reason=(
                    "Outcome.on_time is left None. Whether a pickup counted as on time depends on the "
                    "agency's on-time window (commonly -0/+30 minutes, but it is a policy parameter, "
                    "not a fact) and no trip export carries it; deriving on_time from the "
                    "scheduled/actual gap would be a policy guess presented as a measurement"
                ),
                disposition="dropped",
            ),
            SemanticLossRecord(
                source_field="<excess ride time and deadhead>",
                source_value=None,
                reason=(
                    "Outcome.excess_ride_time_minutes and Outcome.deadhead_minutes are left None. Both "
                    "are derived by chaining a vehicle's consecutive trips (and, for excess ride time, "
                    "from a dropoff time the minimum field list does not ask for), which is the "
                    "teardown's job, not a single row's"
                ),
                disposition="dropped",
            ),
        ]

        if rider_sent:
            losses.append(
                SemanticLossRecord(
                    source_field=resolved["rider_ref"][0],
                    source_value=None,
                    reason=(
                        "the operator's own client identifier was replaced by sha256(value)[:24] on "
                        "ingest and the input was NOT retained -- not in the canonical record, not in "
                        "this loss record (hence the null source_value), not in a log. The mapping is "
                        "one-way, so the original id cannot be recovered from Milexium. Honest limit: "
                        "an unsalted hash over a small id space is brute-forceable, which is why this "
                        "column is optional and knowledge/docs/OPERATOR_DATA_INTAKE.md asks operators to omit it"
                    ),
                    disposition="coerced",
                )
            )
        else:
            losses.append(
                SemanticLossRecord(
                    source_field="<no rider identifier column>",
                    source_value=None,
                    reason=(
                        "no rider identifier was sent (the state Milexium asks for). rider_ref is a "
                        "deterministic per-trip placeholder (operator-no-rider-<sha256 of trip_ref>), "
                        "never a stable or joinable identity: repeat trips by the same rider cannot be "
                        "linked, so any per-rider analysis is impossible by construction"
                    ),
                    disposition="dropped",
                )
            )

        # The vehicle/run reference itself is NOT a loss any more. ADR-0038
        # recorded it as `dropped` on every row because canonical v0.1 had
        # nowhere to put it; ADR-0043 put it on `outcomes`, and this adapter now
        # writes `Outcome.vehicle_ref`/`Outcome.run_ref`, so the value survives a
        # write to MilexiumDB and reporting it as dropped would be false.
        #
        # One aspect of that old record is still true and is kept, narrowed to
        # exactly that aspect: what persists is the operator's LABEL for a
        # vehicle/run, not the entity it names.
        if vehicle_ref is not None or run_ref is not None:
            losses.append(
                SemanticLossRecord(
                    source_field="<the block, run or vehicle the reference names>",
                    source_value=None,
                    reason=(
                        "the reference itself is retained: vehicle_ref/run_ref are written to "
                        "Outcome.vehicle_ref/Outcome.run_ref (ADR-0043) and survive a write to "
                        "MilexiumDB. What is NOT retained is the entity behind the label. These stay "
                        "plain source-system strings with no foreign key to vehicles, blocks or "
                        "run_pieces, and no Vehicle/Block/RunPiece row is minted here, because the "
                        "minimum field list carries nothing to build one from -- no capacity, no "
                        "accessibility equipment, no pull-out/pull-in, no piece boundaries. Two "
                        "consequences worth stating plainly: the same unit number sent by two "
                        "operators is not one vehicle, and a teardown can measure the gaps BETWEEN "
                        "this run's consecutive trips but not the empty time before its first trip "
                        "or after its last, which is therefore invisible rather than zero"
                    ),
                    disposition="dropped",
                )
            )

        if raw_outcome != canonical_outcome:
            losses.append(
                _repair(
                    "enum_synonym",
                    resolved["outcome"][0],
                    raw_outcome,
                    canonical_outcome,
                    "mapped via the adapter's published synonym table -- an explicit, recorded "
                    "mapping that is insensitive to case and to the separators an outcome value "
                    "uses ('No Show' == 'no_show' == 'no-show'). Values outside that table are "
                    "quarantined, never bucketed by resemblance: 'SERVED?' keeps its question "
                    "mark, because that is an operator flagging uncertainty",
                )
            )

        if not served and actual_pickup_at is not None:
            losses.append(
                SemanticLossRecord(
                    source_field=resolved["actual_pickup_at"][0],
                    source_value=actual_pickup_at.isoformat(),
                    reason=(
                        f"an actual pickup time was supplied on a trip whose outcome is "
                        f"{canonical_outcome!r}. A trip that was not served has no pickup, so the value "
                        "is not mapped onto ServiceRequest.times.actual_pickup_at or Outcome."
                        "actual_pickup_at; it most likely records when the vehicle arrived, which is a "
                        "different fact with no canonical home"
                    ),
                    disposition="dropped",
                )
            )

        if naive_columns:
            losses.append(
                SemanticLossRecord(
                    source_field=", ".join(naive_columns),
                    source_value=None,
                    reason=(
                        "timestamp(s) carried no UTC offset and were treated as UTC directly -- the same "
                        "simplification every adapter in this repo makes. If the export is in agency "
                        "local time this silently shifts every trip by the local offset, which would "
                        "corrupt any headway or on-time analysis; knowledge/docs/OPERATOR_DATA_INTAKE.md therefore "
                        "asks for an explicit offset"
                    ),
                    disposition="coerced",
                )
            )

        recognised = {source for source, _ in resolved.values()}
        for column in raw_row:
            if column is None:
                # csv.DictReader's restkey: a RAGGED row's surplus cells, which
                # belong to no column at all. Recorded by label, never by value,
                # for the same reason as any other unrecognised column -- and
                # note the PII value scan above already looked inside the list.
                losses.append(
                    SemanticLossRecord(
                        source_field=RAGGED_EXTRA_COLUMN_LABEL,
                        source_value=None,
                        reason=(
                            "the row carried more cells than the header declares, so these values "
                            "belong to no named column. They are recorded as present and their "
                            "values are NOT retained. A ragged row usually means an unquoted "
                            "comma inside a value earlier in the row, which also means the named "
                            "columns after it are shifted -- worth checking before re-sending"
                        ),
                        disposition="unmapped_extension",
                    )
                )
                continue
            name = str(column)
            if name in recognised:
                continue
            losses.append(
                SemanticLossRecord(
                    source_field=name,
                    source_value=None,
                    reason=(
                        "not part of the Milexium minimum intake field list and not named in the "
                        "column_map, so it is recorded by name and its value is deliberately NOT "
                        "retained -- an unrecognised column in an operator export is exactly where "
                        "unanticipated personal data would hide"
                    ),
                    disposition="unmapped_extension",
                )
            )

        return losses
