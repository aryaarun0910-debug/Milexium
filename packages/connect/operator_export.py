"""Adapter: a generic operator trip export (CSV/Parquet-shaped dict rows)
-> ServiceRequest + Outcome (v0.1).

Status: **Exists** (v0.1), **Demonstrated on synthetic exports only**. No real
operator data exists anywhere in this repository and none has ever been
received. Nothing here may be promoted to "Validated" -- that requires
consented operator data against a declared baseline, per
architecture/decisions/0001-adopt-expansion-blueprint-and-control-plane.md.

WHY THIS ADAPTER IS DIFFERENT FROM ITS SIBLINGS
`reference_agency_trips.py`, `tlc_trips.py`, `tides_trips.py`, `gtfs_flex.py`
and `gtfs_realtime.py` each map ONE published schema whose columns are known in
advance. This adapter maps something that has no schema yet: whatever an agency
can actually get out of its scheduling system. So instead of a fixed header it
defines a *minimum field list* (the smallest set that makes a deadhead/late-
trip teardown possible), accepts an explicit `column_map` from the operator's
own header onto that list, and treats everything else as an extension.

The intake contract an agency reads before sending anything is
`docs/OPERATOR_DATA_INTAKE.md`. This module is the enforcement of that
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
an `Outcome` (what happened to it) -- plus the vehicle/run reference, which has
no canonical home at all. The composite is NOT a new canonical entity: it is a
transport container for a batch handoff to `MX-H-DEADHEAD-TEARDOWN-003`, and
the missing canonical home for a vehicle assignment is recorded as semantic
loss on every row rather than quietly invented here.

MODELLING JUDGMENTS WORTH RECORDING (they are judgment, not derivation)
- **Terminal status is materialised directly.** A historical export describes
  finished trips, so `ServiceRequest.status` is set to the terminal state the
  outcome implies (COMPLETED / NO_SHOW / DENIED / CANCELLED) rather than the
  REQUESTED the siblings use. The intermediate lifecycle transitions
  (`packages.canonical.state_machine`) genuinely happened in the operator's
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
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, model_validator

from packages.canonical import (
    BitemporalMeta,
    Outcome,
    RequestId,
    RequestTimes,
    ServiceRequest,
    ServiceRequestState,
    TenantId,
    new_id,
)
from packages.connect.adapter import AdapterResult, QuarantinedRow, SemanticLossRecord

# --------------------------------------------------------------------------
# The minimum field list. docs/OPERATOR_DATA_INTAKE.md publishes exactly this.
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
    `docs/OPERATOR_DATA_INTAKE.md`, not a general PII scanner: a column called
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


def _contains_email(value: object) -> bool:
    return isinstance(value, str) and bool(_EMAIL_RE.search(value))


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


def _present(value: object) -> bool:
    """A CSV cell is absent when the key is missing, the value is None, or the
    string is empty/whitespace (the empty-string null convention CSV uses)."""
    return value is not None and str(value).strip() != ""


def _parse_timestamp(column: str, raw_value: object) -> tuple[datetime, bool]:
    """An exported timestamp -> (UTC datetime, was_naive).

    Accepts a datetime (what a Parquet read yields) or an ISO-8601 string (what
    a CSV export yields). A naive value is treated as UTC and the caller records
    the coercion -- the same simplification every sibling adapter makes, and a
    real hazard for a local-time export, which is why the document asks for an
    explicit offset.
    """

    if isinstance(raw_value, datetime):
        value = raw_value
    elif isinstance(raw_value, str):
        try:
            value = datetime.fromisoformat(raw_value.strip())
        except ValueError as exc:
            raise _UnmappableValue(
                f"unparseable {column} timestamp {raw_value!r}: {exc} "
                "(expected ISO-8601, e.g. 2026-03-04T08:15:00-05:00)",
                column,
            ) from exc
    else:
        raise _UnmappableValue(
            f"unparseable {column} timestamp {raw_value!r}: expected an ISO-8601 string or a datetime",
            column,
        )
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc), True
    return value.astimezone(timezone.utc), False


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

    NOT a canonical entity and not a new contract: `packages.canonical` owns the
    canonical model and this module does not extend it. This is a Connect-layer
    container so one `parse()` can return the request and its outcome together,
    plus the vehicle/run reference that canonical v0.1 has no home for.
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

    # -- quarantine helpers -------------------------------------------------

    def _redacted(self, raw_row: dict, columns: list[str]) -> dict:
        """Preserve the row for re-run, minus the values that must not be kept."""
        redacted = dict(raw_row)
        for column in columns:
            if column in redacted:
                redacted[column] = REDACTION_MARKER
        return redacted

    def _pii_quarantine(
        self, raw_row: dict, findings: list[tuple[str, str]]
    ) -> AdapterResult[OperatorTripRecord]:
        findings = sorted(findings)
        detail = "; ".join(f"{column} ({category})" for column, category in findings)
        return AdapterResult(
            quarantine=QuarantinedRow(
                raw_row=self._redacted(raw_row, [column for column, _ in findings]),
                reason=(
                    "rejected on ingest: the export carries direct rider/staff identifiers, which "
                    f"Milexium does not accept -- {detail}. Remove these column(s) at source and "
                    "re-send; see docs/OPERATOR_DATA_INTAKE.md ('WHAT WE DO NOT WANT'). The offending "
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
        for column, value in raw_row.items():
            category = classify_pii_column(str(column))
            if category is None and _contains_email(value):
                category = "email address (found in the value, not the column name)"
            if category is not None:
                findings.append((str(column), category))
        if findings:
            return self._pii_quarantine(raw_row, findings)

        # 2. Resolve the operator's header onto the canonical column names.
        resolved: dict[str, tuple[str, object]] = {}
        for column, value in raw_row.items():
            name = str(column)
            target = self._column_map.get(name) or (name if name in CANONICAL_COLUMNS else None)
            if target is None:
                continue
            if target in resolved:
                return self._quarantine(
                    raw_row,
                    f"two source columns ({resolved[target][0]!r} and {name!r}) both resolve to the "
                    f"canonical column {target!r}; Milexium will not choose between them",
                    target,
                )
            resolved[target] = (name, value)

        def source_of(canonical: str) -> str:
            return resolved[canonical][0] if canonical in resolved else canonical

        def value_of(canonical: str) -> object:
            return resolved[canonical][1] if canonical in resolved else None

        # 3. Zone columns must carry zones, not addresses.
        address_findings = [
            (source_of(zone_column), "street address (found in the value of a zone column)")
            for zone_column in ("pickup_zone", "dropoff_zone")
            if looks_like_street_address(value_of(zone_column))
        ]
        if address_findings:
            return self._pii_quarantine(raw_row, address_findings)

        # 4. Required fields -- absent means quarantined, never defaulted.
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

        # 5. Times.
        naive_columns: list[str] = []
        try:
            requested_at, naive = _parse_timestamp(source_of("requested_at"), value_of("requested_at"))
            if naive:
                naive_columns.append(source_of("requested_at"))
            scheduled_pickup_at, naive = _parse_timestamp(
                source_of("scheduled_pickup_at"), value_of("scheduled_pickup_at")
            )
            if naive:
                naive_columns.append(source_of("scheduled_pickup_at"))
            actual_pickup_at: datetime | None = None
            if _present(value_of("actual_pickup_at")):
                actual_pickup_at, naive = _parse_timestamp(
                    source_of("actual_pickup_at"), value_of("actual_pickup_at")
                )
                if naive:
                    naive_columns.append(source_of("actual_pickup_at"))
        except _UnmappableValue as exc:
            return self._quarantine(raw_row, str(exc), exc.field)

        # 6. Outcome vocabulary -- an unknown value is quarantined, not bucketed.
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

        # 7. Cross-field consistency.
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

        # 8. Map.
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
        )
        record = OperatorTripRecord(
            request=request, outcome=outcome, vehicle_ref=vehicle_ref, run_ref=run_ref
        )
        return AdapterResult(record=record, semantic_loss=tuple(semantic_loss))

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
    ) -> list[SemanticLossRecord]:
        losses: list[SemanticLossRecord] = [
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
                        "column is optional and docs/OPERATOR_DATA_INTAKE.md asks operators to omit it"
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

        if vehicle_ref is not None or run_ref is not None:
            losses.append(
                SemanticLossRecord(
                    source_field=", ".join(
                        resolved[column][0] for column in VEHICLE_OR_RUN_COLUMNS if column in resolved
                    ),
                    source_value="|".join(part for part in (vehicle_ref, run_ref) if part is not None),
                    reason=(
                        "canonical v0.1 has no home for a vehicle/run assignment on a ServiceRequest or "
                        "an Outcome (Vehicle exists as an entity, but the request-to-vehicle assignment "
                        "does not). The reference is carried on the Connect-layer OperatorTripRecord "
                        "only, so it survives the handoff to the teardown but would NOT survive a write "
                        "to MilexiumDB -- a real canonical gap, recorded rather than invented here"
                    ),
                    disposition="dropped",
                )
            )

        if raw_outcome != canonical_outcome:
            losses.append(
                SemanticLossRecord(
                    source_field=resolved["outcome"][0],
                    source_value=raw_outcome,
                    reason=(
                        f"source outcome {raw_outcome!r} mapped to the canonical value "
                        f"{canonical_outcome!r} via the adapter's published synonym table -- an explicit, "
                        "recorded mapping. Values outside that table are quarantined, never bucketed by "
                        "resemblance"
                    ),
                    disposition="coerced",
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
                        "corrupt any headway or on-time analysis; docs/OPERATOR_DATA_INTAKE.md therefore "
                        "asks for an explicit offset"
                    ),
                    disposition="coerced",
                )
            )

        recognised = {source for source, _ in resolved.values()}
        for column in raw_row:
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
