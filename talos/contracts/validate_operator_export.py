"""Read a sample operator export and report what it can and cannot support.

WHAT THIS IS FOR
`talos/contracts/operator_contract.py` states what we need. This turns that
statement into a checkable conversation: point it at two hundred rows and it
answers, capability by capability, with the missing field named --

    This export supports outcome analysis and deadhead measurement. It cannot
    support decision replay, because no source-side knowledge timestamp is
    present.

An agency can run it themselves before anything leaves their building. It writes
nothing, sends nothing, opens no network connection, and retains no value from
the file: findings name COLUMNS, never cell contents.

THE CHECK THAT JUSTIFIES THE FILE
A presence test on `record_created_known_at` is nearly worthless, because the
field that matters most is also the one most likely to be present and
meaningless. An extract tool that writes `created_at = now()` on every row
produces a column that is fully populated, correctly typed, and is the export
time under another name. A validator that reported "decision replay: supported"
for that file would be worse than no validator, because the resulting analysis
would look rigorous.

So the degeneracy checks are the point:

- every row sharing one knowledge time  (`KNOWN_AT_CONSTANT`)
- knowledge times spanning hours while events span weeks (`BACKFILL_SIGNATURE`)
- knowledge time equal to the declared export time (`KNOWN_AT_EQUALS_EXPORT_TIME`)
- knowledge time before the event it describes (`KNOWN_AT_PRECEDES_EVENT`)

Each is arithmetic on the sample, not a judgement about the operator, and each
one downgrades a capability with a stated reason rather than raising an alarm
someone has to interpret.

ORDERING IS LOAD-BEARING
The identity gate runs FIRST, before required-column checks, before timestamp
parsing, before any capability is assessed -- the same ordering ADR-0051
established for the ingest adapter, for the same reason: a file that carries
rider names is refused on that ground even when it is also perfect in every other
respect, and no other finding gets to soften it. When the gate fires, every
capability is reported NOT_ASSESSED rather than NOT_SUPPORTED, because we have
not looked and saying otherwise would be a claim about a file we declined to read.

WHAT IT DOES NOT DO
It does not repair, import, or persist anything -- `themis/connect/
operator_export.py` is the adapter and this is not a second one. It does not
detect a rider's name in a column called `ref2`; nothing does. And it reports on
the SAMPLE: a column populated in two hundred rows may be null in the other two
million, and the report says so.

    py -3 talos/contracts/validate_operator_export.py sample.csv
    py -3 talos/contracts/validate_operator_export.py sample.csv --declarations answers.json
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

# Make the repo root importable when run standalone, exactly as
# talos/contracts/generate.py does.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from talos.contracts.operator_contract import (  # noqa: E402
    CAPABILITIES,
    FIELDS_BY_NAME,
    Requirement,
    Shape,
)

# The shared identity classifier, IMPORTED rather than reimplemented. A second
# PII vocabulary in a second file is how the two drift apart and one of them
# quietly stops catching something (ADR-0057 records exactly that happening).
# `_contains_email` is private; importing a private helper from this module is
# established here -- themis/connect/ingest_report.py imports `_present` the
# same way -- and is the lesser evil against copying the regex.
from themis.connect.operator_export import (  # noqa: E402
    _contains_email,
    classify_pii_column,
    looks_like_street_address,
)


# ---------------------------------------------------------------------------
# Thresholds. Each is a stated rule, not a tuned parameter, and each is written
# so the arithmetic can be checked by hand from the report.
# ---------------------------------------------------------------------------

BACKFILL_EVENT_SPAN = timedelta(days=7)
"""Below this the export is too short for the backfill test to mean anything:
a genuinely live feed covering three days can legitimately have a narrow
knowledge-time span."""

BACKFILL_KNOWN_SPAN = timedelta(days=1)
"""Event times spanning weeks while knowledge times span less than a day is the
signature of a history stamped at load. It is not proof -- an operator could have
migrated systems -- so the finding names the numbers and asks."""

EXPORT_TIME_MATCH_SHARE = 0.5
"""Half the rows carrying a knowledge time equal to the declared export time is
enough to conclude the extract wrote it. One row could be a coincidence of
timing; half of them cannot."""

MINIMUM_VIABLE_WEEKS = 8
"""From the contract's minimum viable ask. Below it, day-of-week and weather
effects are not separable and any model is describing the sample."""

# Vehicle- and driver-identity column names. ADR-0057 records that the shared
# classifier does not catch these and that widening it would change what the
# ingest adapter quarantines for reasons unrelated to this contract. So the
# vocabulary is applied locally, exactly as tlc_trips.py does, and the gap is
# recorded rather than papered over.
_IDENTITY_COLUMN_TOKENS: tuple[tuple[str, str], ...] = (
    ("hacklicense", "driver licence (a person, not a vehicle)"),
    ("hacklicence", "driver licence (a person, not a vehicle)"),
    ("driverlicense", "driver licence (a person, not a vehicle)"),
    ("driverlicence", "driver licence (a person, not a vehicle)"),
    ("medallion", "medallion number (publicly resolvable to a licensee)"),
    ("licenseplate", "vehicle registration plate"),
    ("licenceplate", "vehicle registration plate"),
    ("numberplate", "vehicle registration plate"),
    ("vin", "vehicle identification number"),
)


# How an absent field is described in a verdict. The default -- "no `x` column is
# present" -- is accurate and unreadable for the fields that matter most, and the
# headline sentence this validator exists to produce is only worth anything if a
# non-engineer can read it.
_ABSENCE_PHRASE: dict[str, str] = {
    "record_created_known_at": "no source-side knowledge timestamp is present",
    "record_updated_known_at": "no last-modified timestamp and no change log are present",
    "run_roster": (
        "no run roster was supplied, so we do not know which vehicles existed or "
        "were on shift"
    ),
    "candidate_log": "no log of rejected candidate assignments was supplied",
    "denial_code": "no denial reason code is present",
    "actual_pickup_at": "no actual pickup time is present",
    "actual_dropoff_at": "no actual dropoff time is present",
}


class Verdict(str, Enum):
    SUPPORTED = "supported"
    SUPPORTED_WITH_LIMITS = "supported_with_limits"
    NOT_SUPPORTED = "not_supported"
    NOT_ASSESSED = "not_assessed"


class Severity(str, Enum):
    REFUSAL = "refusal"
    """The export is declined. Nothing else was assessed."""

    CRITICAL = "critical"
    """A capability is withdrawn."""

    WARNING = "warning"
    """A capability is narrowed, or a number needs a caveat attached."""

    INFO = "info"
    """Worth knowing; changes nothing."""


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    message: str
    columns: tuple[str, ...] = ()
    """Column NAMES only. No cell value from the sample ever reaches a finding --
    a report on a file that carries rider names must not itself carry them."""


@dataclass(frozen=True)
class CapabilityVerdict:
    capability_id: str
    capability_name: str
    verdict: Verdict
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ContractAssessment:
    row_count: int
    refused: bool
    findings: tuple[Finding, ...]
    capabilities: tuple[CapabilityVerdict, ...]
    columns_present: tuple[str, ...]
    contract_columns_missing: tuple[str, ...]
    declarations_missing: tuple[str, ...]
    event_span_days: float | None
    source: str = "<in-memory rows>"

    def verdict_for(self, capability_id: str) -> Verdict:
        for item in self.capabilities:
            if item.capability_id == capability_id:
                return item.verdict
        raise KeyError(capability_id)

    def has(self, code: str) -> bool:
        return any(finding.code == code for finding in self.findings)

    def headline(self) -> str:
        """One sentence, in the shape the contract promises."""
        if self.refused:
            return (
                "This export is declined on identity grounds and nothing else was "
                "assessed. See the refusal findings below."
            )
        supported = [
            item.capability_name.lower()
            for item in self.capabilities
            if item.verdict in (Verdict.SUPPORTED, Verdict.SUPPORTED_WITH_LIMITS)
        ]
        blocked = [
            item
            for item in self.capabilities
            if item.verdict is Verdict.NOT_SUPPORTED
        ]
        if supported:
            first = f"This export supports {_join(supported)}."
        else:
            first = "This export supports none of the capabilities in the contract."
        if not blocked:
            return first
        worst = blocked[0]
        reason = worst.reasons[0] if worst.reasons else "a required field is absent"
        sentence = (
            f"{first} It cannot support {worst.capability_name.lower()}, because {reason}."
        )
        # The remaining blockers are NAMED rather than folded into the sentence
        # above: attaching one capability's reason to four capabilities would be
        # a summary that is wrong about three of them.
        rest = [item.capability_name.lower() for item in blocked[1:]]
        if rest:
            sentence += f" Also unsupported, for their own reasons: {_join(rest)}."
        return sentence

    def report(self) -> str:
        lines: list[str] = []
        lines.append("Milexium operator-export contract check")
        lines.append("=" * 38)
        lines.append(f"source        : {self.source}")
        lines.append(f"rows in sample: {self.row_count}")
        if self.event_span_days is not None:
            lines.append(f"period covered: {self.event_span_days:.1f} days of event time")
        lines.append("")
        lines.append(self.headline())
        lines.append("")
        lines.append("Capabilities")
        lines.append("-" * 38)
        for item in self.capabilities:
            lines.append(f"  {item.verdict.value.upper():<22} {item.capability_name}")
            for reason in item.reasons:
                lines.append(f"      - {reason}")
        lines.append("")
        lines.append("Findings")
        lines.append("-" * 38)
        if not self.findings:
            lines.append("  (none)")
        for finding in self.findings:
            lines.append(f"  [{finding.severity.value.upper()}] {finding.code}")
            lines.append(f"      {finding.message}")
            if finding.columns:
                lines.append(f"      columns: {', '.join(finding.columns)}")
        lines.append("")
        lines.append("What this check does NOT establish")
        lines.append("-" * 38)
        lines.append("  - It reports on the SAMPLE. A column populated in this sample may be")
        lines.append("    null in the rest of the extract.")
        lines.append("  - It cannot detect a personal name in a column that does not announce")
        lines.append("    itself (a rider name in a column called 'ref2' passes). The contract")
        lines.append("    is the agreement; this is the seatbelt.")
        lines.append("  - A supported capability means the DATA would support it. Milexium has")
        lines.append("    never run any of these on operator data; nothing here is Validated.")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "row_count": self.row_count,
            "refused": self.refused,
            "headline": self.headline(),
            "event_span_days": self.event_span_days,
            "columns_present": list(self.columns_present),
            "contract_columns_missing": list(self.contract_columns_missing),
            "declarations_missing": list(self.declarations_missing),
            "capabilities": [
                {
                    "id": item.capability_id,
                    "name": item.capability_name,
                    "verdict": item.verdict.value,
                    "reasons": list(item.reasons),
                }
                for item in self.capabilities
            ],
            "findings": [
                {
                    "code": item.code,
                    "severity": item.severity.value,
                    "message": item.message,
                    "columns": list(item.columns),
                }
                for item in self.findings
            ],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _join(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _normalise_column(name: object) -> str:
    text = "" if name is None else str(name)
    return "".join(character for character in text.lower() if character.isalnum())


def _present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _parse_timestamp(value: object) -> datetime | None:
    """Tolerant enough to read a well-formed export, deliberately NOT a repair
    layer. `themis/connect/operator_export.py` owns repair; duplicating its ten
    rules here would give an operator two different answers about the same file.
    An unparseable value is reported as unparseable."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        # Naive timestamps are read as UTC, matching the repo-wide convention,
        # and the assumption is reported as a finding rather than absorbed.
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class _Column:
    """One contract column as it appears in the sample."""

    values: list[object] = field(default_factory=list)

    @property
    def populated(self) -> int:
        return sum(1 for value in self.values if _present(value))


# ---------------------------------------------------------------------------
# The assessment
# ---------------------------------------------------------------------------

def assess(
    rows: Sequence[Mapping[str, object]],
    *,
    declarations: Mapping[str, object] | None = None,
    column_map: Mapping[str, str] | None = None,
    source: str = "<in-memory rows>",
) -> ContractAssessment:
    """Assess a sample against the contract.

    `column_map` maps the operator's own headers onto contract field names, the
    same way `themis.connect.operator_export` takes one -- an operator should
    never have to rename columns to be told what their data supports.
    `declarations` carries the answers to the contract's DECLARATION lines, keyed
    by field name.
    """

    declarations = dict(declarations or {})
    column_map = dict(column_map or {})
    rows = list(rows)

    findings: list[Finding] = []
    headers: list[str] = []
    for row in rows:
        for key in row:
            if key not in headers:
                headers.append(key)

    # --- 1. THE IDENTITY GATE. Runs before everything else. -------------------
    refusals = _identity_findings(rows, headers, column_map)
    if refusals:
        return ContractAssessment(
            row_count=len(rows),
            refused=True,
            findings=tuple(refusals),
            capabilities=tuple(
                CapabilityVerdict(
                    capability_id=cap.id,
                    capability_name=cap.name,
                    verdict=Verdict.NOT_ASSESSED,
                    reasons=(
                        "not assessed: the export was declined on identity grounds "
                        "before any capability was evaluated",
                    ),
                )
                for cap in CAPABILITIES
            ),
            columns_present=tuple(headers),
            contract_columns_missing=(),
            declarations_missing=(),
            event_span_days=None,
            source=source,
        )

    if not rows:
        findings.append(
            Finding(
                "EMPTY_SAMPLE",
                Severity.CRITICAL,
                "the sample contains no rows, so nothing can be assessed from it. "
                "An empty file is a different problem from a bad one and is reported "
                "as such rather than as a clean pass.",
            )
        )

    # --- 2. Which contract columns are present -------------------------------
    resolved = _resolve_columns(rows, headers, column_map)
    present = tuple(name for name, column in resolved.items() if column.populated > 0)
    contract_columns = tuple(
        spec.name for spec in FIELDS_BY_NAME.values() if spec.shape is Shape.COLUMN
    )
    missing = tuple(name for name in contract_columns if name not in present)

    # --- 3. Declarations ------------------------------------------------------
    declaration_fields = tuple(
        spec.name
        for spec in FIELDS_BY_NAME.values()
        if spec.shape is Shape.DECLARATION and spec.requirement is Requirement.REQUIRED
    )
    declarations_missing = tuple(
        name
        for name in declaration_fields
        if not _present(declarations.get(name))
        # denial_code_list only bites when the export actually contains denials
        and not (name == "denial_code_list" and not _has_denials(resolved))
    )
    for name in declarations_missing:
        if name == "fleet_shape":
            # `_fleet_shape_findings` reports this one itself, with the specific
            # consequence attached. Two findings for one unanswered question is
            # noise, and noise is how a report stops being read.
            continue
        spec = FIELDS_BY_NAME[name]
        findings.append(
            Finding(
                f"DECLARATION_MISSING__{name.upper()}",
                Severity.WARNING,
                f"unanswered: {spec.operator_question} Without it: {spec.lost_without_it}",
            )
        )

    # --- 4. The fleet-shape gate ---------------------------------------------
    fleet_shape_resolved, vehicle_ref_usable = _fleet_shape_findings(
        resolved, declarations, findings
    )

    # --- 5. Required columns --------------------------------------------------
    # Derived from the contract, never typed out here. A hand-maintained copy of
    # the required list in the validator is the same drift this whole layer
    # exists to prevent, one level down. The conditional ones (actual_pickup_at,
    # vehicle_ref / run_ref) carry their own rules and are handled below.
    unconditional_required = tuple(
        spec.name
        for spec in FIELDS_BY_NAME.values()
        if spec.shape is Shape.COLUMN
        and spec.requirement is Requirement.REQUIRED
        and spec.conditional_on is None
    )
    for name in unconditional_required:
        if name not in present:
            findings.append(
                Finding(
                    f"REQUIRED_COLUMN_MISSING__{name.upper()}",
                    Severity.CRITICAL,
                    f"`{name}` is required and is absent or entirely blank. "
                    f"{FIELDS_BY_NAME[name].lost_without_it}",
                    columns=(name,),
                )
            )
    # `actual_pickup_at` is required only for SERVED rows, so its absence is
    # counted per row rather than per column -- a column that is blank for every
    # cancelled trip is correct, and a column that is blank for a served one is
    # the measurement missing.
    served_without_actual = sum(
        1
        for outcome, actual in zip(
            resolved["outcome"].values, resolved["actual_pickup_at"].values
        )
        if _normalise_column(outcome) in {"served", "completed", "complete", "performed", "delivered"}
        and not _present(actual)
    )
    if served_without_actual:
        findings.append(
            Finding(
                "SERVED_ROWS_WITHOUT_AN_ACTUAL_PICKUP",
                Severity.WARNING,
                f"{served_without_actual} rows are marked served with no actual pickup "
                "time. Those rows contribute to the denominator of an on-time figure "
                "and cannot contribute to the numerator. We will not substitute the "
                "scheduled time for the actual one -- the gap between them is the "
                "measurement -- so those rows are excluded and the exclusion is "
                "reported alongside any figure.",
                columns=("actual_pickup_at",),
            )
        )

    if "vehicle_ref" not in present and "run_ref" not in present:
        findings.append(
            Finding(
                "REQUIRED_COLUMN_MISSING__VEHICLE_OR_RUN",
                Severity.CRITICAL,
                "neither `vehicle_ref` nor `run_ref` is present. Deadhead is measured "
                "by chaining one vehicle's consecutive trips, so with neither, the "
                "trips cannot be put in order and nothing can be measured between them.",
                columns=("vehicle_ref", "run_ref"),
            )
        )

    # --- 6. Timestamps --------------------------------------------------------
    event_span_days = _timestamp_findings(rows, resolved, findings)

    # --- 7. Outcomes ----------------------------------------------------------
    served_only = _outcome_findings(resolved, findings)

    # --- 8. Knowledge time. The section this whole packet exists for. ---------
    knowledge = _knowledge_time_findings(resolved, declarations, findings)

    # --- 9. Capability verdicts ----------------------------------------------
    capabilities = _verdicts(
        present=present,
        resolved=resolved,
        declarations=declarations,
        knowledge=knowledge,
        served_only=served_only,
        vehicle_ref_usable=vehicle_ref_usable,
        fleet_shape_resolved=fleet_shape_resolved,
    )

    # --- 10. Coverage ---------------------------------------------------------
    if event_span_days is not None and event_span_days < MINIMUM_VIABLE_WEEKS * 7:
        findings.append(
            Finding(
                "BELOW_MINIMUM_VIABLE_WINDOW",
                Severity.WARNING,
                f"the sample covers {event_span_days:.1f} days of event time; the "
                f"minimum viable ask is {MINIMUM_VIABLE_WEEKS}-12 weeks so that "
                "day-of-week and seasonal effects are separable from noise. This is "
                "expected and fine for a sample sent to check the shape of the file.",
            )
        )

    return ContractAssessment(
        row_count=len(rows),
        refused=False,
        findings=tuple(findings),
        capabilities=capabilities,
        columns_present=present,
        contract_columns_missing=missing,
        declarations_missing=declarations_missing,
        event_span_days=event_span_days,
        source=source,
    )


def _identity_findings(
    rows: Sequence[Mapping[str, object]],
    headers: Sequence[str],
    column_map: Mapping[str, str],
) -> list[Finding]:
    """The gate. Column names first (a blank identity column in a sample is a
    populated one in the extract), then values."""

    findings: list[Finding] = []
    offending: dict[str, str] = {}

    for header in headers:
        # A column mapped onto a contract field is still checked under its OWN
        # name: laundering `rider_name` through a column_map entry pointing at
        # `trip_ref` must not get it past the gate.
        category = classify_pii_column(str(header))
        if category is None:
            normalised = _normalise_column(header)
            for token, description in _IDENTITY_COLUMN_TOKENS:
                if token in normalised:
                    category = description
                    break
        if category is not None:
            offending[str(header)] = category

    if offending:
        findings.append(
            Finding(
                "IDENTITY_COLUMN_PRESENT",
                Severity.REFUSAL,
                "the export carries direct rider, staff or licensing identifiers. "
                "Milexium does not accept these -- not encrypted, not in a "
                "password-protected archive, not 'in case it is useful'. Remove the "
                "column(s) at source and re-send. The column is refused whether or "
                "not it has a value in this sample, because an all-blank column in a "
                "sample is usually a populated one in the full extract. Offending "
                "columns are named below; no value from them appears anywhere in this "
                "report. -- "
                + "; ".join(
                    f"{name} ({category})" for name, category in sorted(offending.items())
                ),
                columns=tuple(sorted(offending)),
            )
        )

    email_columns: set[str] = set()
    address_zone_columns: set[str] = set()
    zone_targets = {"pickup_zone", "dropoff_zone"}
    for row in rows:
        for key, value in row.items():
            if _contains_email(value):
                email_columns.add(str(key))
            target = column_map.get(str(key), str(key))
            if target in zone_targets and looks_like_street_address(value):
                address_zone_columns.add(str(key))

    if email_columns:
        findings.append(
            Finding(
                "EMAIL_IN_VALUES",
                Severity.REFUSAL,
                "an email address appears in the cell values. Renaming the column does "
                "not change what is in it. The offending value is not reproduced here.",
                columns=tuple(sorted(email_columns)),
            )
        )
    if address_zone_columns:
        findings.append(
            Finding(
                "ZONE_IS_AN_ADDRESS",
                Severity.REFUSAL,
                "a pickup or dropoff zone is shaped like a street address. A pickup "
                "address is a rider's home; zones exist so that column does not have "
                "to travel. Send a zone, district, ZIP or grid cell instead.",
                columns=tuple(sorted(address_zone_columns)),
            )
        )
    return findings


def _resolve_columns(
    rows: Sequence[Mapping[str, object]],
    headers: Sequence[str],
    column_map: Mapping[str, str],
) -> dict[str, _Column]:
    resolved: dict[str, _Column] = {
        spec.name: _Column()
        for spec in FIELDS_BY_NAME.values()
        if spec.shape is Shape.COLUMN
    }
    reverse: dict[str, str] = {}
    for header in headers:
        target = column_map.get(str(header), str(header))
        if target in resolved:
            reverse[str(header)] = target
    for row in rows:
        for header, target in reverse.items():
            resolved[target].values.append(row.get(header))
    return resolved


def _has_denials(resolved: Mapping[str, _Column]) -> bool:
    outcomes = resolved.get("outcome")
    if outcomes is None:
        return False
    return any(
        _normalise_column(value) in {"denied", "denial", "refused", "rejected"}
        for value in outcomes.values
    )


_YES_TOKENS = frozenset({"yes", "sole", "owneroperator"})
"""Deliberately asymmetric with `_NO_TOKENS`, and the asymmetry is the safety
property. A missed YES accepts a person identifier; a missed NO merely withholds
an analysis until someone rephrases one line. So the positive markers are matched
generously anywhere in the answer, and the negative ones only as the FIRST word --
which is what stops "not sure" and "no idea" being read as "no"."""

_NO_TOKENS = frozenset({"no", "none", "false", "nope"})


def _tokens(answer: object) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(answer).lower())


def _reads_as_yes(answer: object) -> bool:
    words = _tokens(answer)
    if set(words) & _YES_TOKENS:
        return True
    pairs = set(zip(words, words[1:]))
    return bool(pairs & {("owner", "operator"), ("single", "vehicle"), ("one", "person")})


def _reads_as_no(answer: object) -> bool:
    words = _tokens(answer)
    if not words or _reads_as_yes(answer):
        return False
    return words[0] in _NO_TOKENS


def _fleet_shape_findings(
    resolved: Mapping[str, _Column],
    declarations: Mapping[str, object],
    findings: list[Finding],
) -> tuple[bool, bool]:
    """ADR-0057: in an owner-operator fleet, vehicle and driver are 1:1, so a
    genuine vehicle id IS a pseudonymous person id. The question is fleet shape,
    not column name -- which is exactly why this is answered by the operator and
    never inferred from the header. Unanswered fails closed.

    Returns `(the question was answered readably, vehicle_ref is usable)`. The
    two are separate because an answer of YES is a perfectly good answer -- it
    resolves the question and rules the column out -- whereas an unreadable one
    resolves nothing, and collapsing them would let 'not sure' count as answered.
    """

    has_vehicle_ref = resolved["vehicle_ref"].populated > 0
    answer = declarations.get("fleet_shape")

    if not _present(answer):
        findings.append(
            Finding(
                "FLEET_SHAPE_UNANSWERED",
                Severity.CRITICAL,
                (
                    "`vehicle_ref` is present and the fleet-shape question is "
                    "unanswered, so we cannot tell whether it identifies a vehicle or "
                    "a person. "
                    if has_vehicle_ref
                    else "the fleet-shape question is unanswered, so we cannot tell "
                    "whether a run in this export is one person's whole working day. "
                )
                + "This fails closed: vehicle- and run-level analysis is withheld "
                "until the question is answered. It is one line -- is any vehicle in "
                "this export driven by exactly one person?",
                columns=("vehicle_ref",) if has_vehicle_ref else (),
            )
        )
        return False, False

    if not has_vehicle_ref:
        # Nothing to gate, and the question has been answered.
        return True, False

    if _reads_as_yes(answer):
        findings.append(
            Finding(
                "VEHICLE_REF_IS_A_PERSON_ID",
                Severity.CRITICAL,
                "you have told us at least one vehicle in this export is operated by "
                "exactly one person. In that fleet shape a vehicle number is a "
                "pseudonymous person identifier no matter what the column is called, "
                "so `vehicle_ref` is not accepted as sent. Tokenise it on your side "
                "before export, or send `run_ref` instead -- either preserves the "
                "chaining that deadhead measurement needs.",
                columns=("vehicle_ref",),
            )
        )
        return True, False

    if _reads_as_no(answer):
        return True, True

    findings.append(
        Finding(
            "FLEET_SHAPE_ANSWER_NOT_RECOGNISED",
            Severity.CRITICAL,
            "the fleet-shape answer could not be read as a yes or a no, so this fails "
            "closed and vehicle-level analysis is withheld. We will not interpret an "
            "ambiguous answer to a privacy question -- please reply with 'yes' or 'no' "
            "to: is any vehicle in this export driven by exactly one person? (Your "
            "answer is not reproduced here.)",
            columns=("vehicle_ref",),
        )
    )
    return False, False


def _timestamp_findings(
    rows: Sequence[Mapping[str, object]],
    resolved: Mapping[str, _Column],
    findings: list[Finding],
) -> float | None:
    naive: set[str] = set()
    unparseable: dict[str, int] = {}
    event_times: list[datetime] = []

    timestamp_fields = [
        name
        for name, spec in FIELDS_BY_NAME.items()
        if spec.shape is Shape.COLUMN and spec.value_type.startswith("timestamp")
    ]
    for name in timestamp_fields:
        column = resolved.get(name)
        if column is None:
            continue
        for value in column.values:
            if not _present(value):
                continue
            if isinstance(value, str) and _parse_timestamp(value) is not None:
                text = value.strip()
                if not any(marker in text[10:] for marker in ("+", "Z", "z")) and "-" not in text[10:]:
                    naive.add(name)
            parsed = _parse_timestamp(value)
            if parsed is None:
                unparseable[name] = unparseable.get(name, 0) + 1
            elif name in ("requested_at", "scheduled_pickup_at", "actual_pickup_at"):
                event_times.append(parsed)

    if naive:
        findings.append(
            Finding(
                "TIMESTAMPS_WITHOUT_OFFSET",
                Severity.WARNING,
                "timestamps carry no UTC offset. They are read as UTC, which shifts "
                "every trip by your local offset if they are in fact local time -- and "
                "the result looks perfectly well-formed while every on-time figure and "
                "every hour-of-day bucket is wrong. Answer the timestamp-convention "
                "question, or re-export with offsets.",
                columns=tuple(sorted(naive)),
            )
        )
    if unparseable:
        findings.append(
            Finding(
                "TIMESTAMPS_UNPARSEABLE",
                Severity.WARNING,
                "some timestamps could not be read as ISO-8601. This check does not "
                "guess at date formats (the ingest adapter has explicit, recorded "
                "repair rules and even it refuses an ambiguous DD/MM vs MM/DD date). "
                "Counts by column: "
                + ", ".join(f"{name}={count}" for name, count in sorted(unparseable.items())),
                columns=tuple(sorted(unparseable)),
            )
        )

    if len(event_times) < 2:
        return None
    return (max(event_times) - min(event_times)).total_seconds() / 86400.0


def _outcome_findings(
    resolved: Mapping[str, _Column],
    findings: list[Finding],
) -> bool:
    """True when the sample contains served trips and nothing else."""
    outcomes = [
        _normalise_column(value)
        for value in resolved["outcome"].values
        if _present(value)
    ]
    if not outcomes:
        return False
    served_like = {"served", "completed", "complete", "performed", "delivered"}
    if set(outcomes) <= served_like:
        findings.append(
            Finding(
                "EXPORT_CONTAINS_ONLY_SERVED_TRIPS",
                Severity.CRITICAL,
                "every row in this sample has a served outcome. If the extract was "
                "filtered to completed trips, unmet demand is structurally invisible: "
                "a forecast trained on it learns the shape of what you were able to "
                "serve, not the shape of what was asked for. Denied, cancelled and "
                "no-show rows are the ones the analysis is most interested in. If the "
                "period genuinely contained no such trips, say so and this finding "
                "goes away.",
                columns=("outcome",),
            )
        )
        return True
    return False


@dataclass(frozen=True)
class _KnowledgeAssessment:
    created_present: bool
    created_complete: bool
    created_rows_missing: int
    usable_for_replay: bool
    updated_usable: bool
    reasons: tuple[str, ...]


def _knowledge_time_findings(
    resolved: Mapping[str, _Column],
    declarations: Mapping[str, object],
    findings: list[Finding],
) -> _KnowledgeAssessment:
    created = resolved["record_created_known_at"]
    updated = resolved["record_updated_known_at"]
    spec = FIELDS_BY_NAME["record_created_known_at"]

    if created.populated == 0:
        findings.append(
            Finding(
                "NO_KNOWLEDGE_TIMESTAMP",
                Severity.CRITICAL,
                "no source-side knowledge timestamp is present. Our receipt time would "
                "then stand in for when your system knew something. If your system knew "
                "at 10:30 and the extract ran at 11:00, a 10:45 reconstruction excludes "
                "it -- correct for us, but your dispatcher knew. Replay would credit "
                "your staff with less information than they had and bias every "
                "comparison in our favour, so decision replay is withdrawn rather than "
                "approximated. This export still supports outcome analysis. "
                + spec.operator_question
                + " Note that this cannot be retrofitted: history exported without it "
                "stays without it.",
                columns=("record_created_known_at",),
            )
        )
        return _KnowledgeAssessment(
            created_present=False,
            created_complete=False,
            created_rows_missing=len(created.values),
            usable_for_replay=False,
            updated_usable=False,
            reasons=("no source-side knowledge timestamp is present",),
        )

    reasons: list[str] = []
    usable = True

    parsed = [_parse_timestamp(value) for value in created.values]
    known = [item for item in parsed if item is not None]
    rows_missing = len(created.values) - len(known)

    # -- degeneracy check 1: one value for every row --------------------------
    if len(set(known)) == 1 and len(known) > 1:
        usable = False
        reasons.append(
            "the knowledge timestamp is identical on every row, so it records when the "
            "extract was written rather than when your system learned anything"
        )
        findings.append(
            Finding(
                "KNOWN_AT_CONSTANT",
                Severity.CRITICAL,
                f"`record_created_known_at` holds one value across all {len(known)} rows. "
                "A single knowledge time for an entire history means every reconstruction "
                "over that history shares one boundary, which is exactly the state the "
                "field exists to avoid. This is indistinguishable from having no "
                "knowledge timestamp at all, and is treated the same way.",
                columns=("record_created_known_at",),
            )
        )

    # -- degeneracy check 2: the backfill signature ---------------------------
    event_values: list[datetime] = []
    for name in ("requested_at", "scheduled_pickup_at"):
        for value in resolved[name].values:
            parsed_event = _parse_timestamp(value)
            if parsed_event is not None:
                event_values.append(parsed_event)
    if len(known) > 1 and len(event_values) > 1:
        known_span = max(known) - min(known)
        event_span = max(event_values) - min(event_values)
        if event_span >= BACKFILL_EVENT_SPAN and known_span <= BACKFILL_KNOWN_SPAN:
            usable = False
            reasons.append(
                f"the knowledge timestamps span {known_span} while the events they "
                f"describe span {event_span} -- the signature of a history stamped at "
                "load rather than recorded as it happened"
            )
            findings.append(
                Finding(
                    "BACKFILL_SIGNATURE",
                    Severity.CRITICAL,
                    f"event times span {event_span.days} days; knowledge times span "
                    f"{known_span}. Eight to twelve weeks arriving as one extract, with "
                    "knowledge times assigned at load, gives every reconstruction over "
                    "that history the same boundary and collapses the point-in-time "
                    "property to nothing. Backfilled data in this shape supports outcome "
                    "analysis but not decision replay. If these timestamps ARE genuine "
                    "system entry times and the pattern has another explanation -- a "
                    "migration, say -- tell us and we will re-read it.",
                    columns=("record_created_known_at",),
                )
            )

    # -- degeneracy check 3: equal to the declared export time ----------------
    export_time = _parse_timestamp(declarations.get("export_generated_at"))
    if export_time is not None and known:
        matches = sum(1 for item in known if item == export_time)
        if matches / len(known) >= EXPORT_TIME_MATCH_SHARE:
            usable = False
            reasons.append(
                "the knowledge timestamp equals the declared export time on "
                f"{matches} of {len(known)} rows, so it is the export time under "
                "another name"
            )
            findings.append(
                Finding(
                    "KNOWN_AT_EQUALS_EXPORT_TIME",
                    Severity.CRITICAL,
                    f"{matches} of {len(known)} rows carry a knowledge timestamp equal to "
                    "the declared export time. That is a value written by the extract, "
                    "not recorded by the operational system. A column like this is worse "
                    "than an absent one, because the analysis built on it looks rigorous. "
                    "Confirm what writes the timestamp -- the booking/dispatch application "
                    "at the moment of entry, or a downstream report layer.",
                    columns=("record_created_known_at",),
                )
            )

    # -- ordering: a row cannot be known before the booking existed -----------
    violations = 0
    requested = [_parse_timestamp(value) for value in resolved["requested_at"].values]
    for known_at, requested_at in zip(parsed, requested):
        if known_at is not None and requested_at is not None and known_at < requested_at:
            violations += 1
    if violations:
        usable = False
        reasons.append(
            f"{violations} rows carry a knowledge timestamp EARLIER than the booking it "
            "describes, so the two columns do not mean what they appear to"
        )
        findings.append(
            Finding(
                "KNOWN_AT_PRECEDES_EVENT",
                Severity.CRITICAL,
                f"{violations} rows record the row as known before the request was made. "
                "A record cannot become visible before the event that created it. The "
                "usual cause is two columns in different time zones, or a 'created' "
                "column that is really the scheduled service date. Either way the field "
                "cannot be used as a knowledge time until it is explained.",
                columns=("record_created_known_at", "requested_at"),
            )
        )

    # -- partial population ---------------------------------------------------
    if rows_missing:
        reasons.append(
            f"{rows_missing} of {len(created.values)} rows carry no knowledge "
            "timestamp, so any reconstructed board omits them"
        )
        findings.append(
            Finding(
                "KNOWN_AT_PARTIAL",
                Severity.WARNING,
                f"{rows_missing} of {len(created.values)} rows have no knowledge "
                "timestamp. Replay is possible over the rest, but the reconstructed "
                "board is missing those rows and is therefore not the board. We would "
                "report the count alongside any figure derived from it.",
                columns=("record_created_known_at",),
            )
        )

    # -- the updated column ---------------------------------------------------
    updated_usable = False
    if updated.populated > 0:
        updated_parsed = [_parse_timestamp(value) for value in updated.values]
        revised = sum(
            1
            for created_at, updated_at in zip(parsed, updated_parsed)
            if created_at is not None and updated_at is not None and updated_at > created_at
        )
        updated_usable = revised > 0
        if revised == 0:
            findings.append(
                Finding(
                    "NO_ROW_SHOWS_A_REVISION",
                    Severity.WARNING,
                    "a last-modified timestamp is present but no row in the sample was "
                    "ever modified after creation. Either the column is not maintained "
                    "by the application, or trips genuinely are never re-timed, "
                    "reassigned or cancelled after entry. The second would be unusual, "
                    "so this is a question rather than a verdict -- which is it?",
                    columns=("record_updated_known_at",),
                )
            )
    else:
        findings.append(
            Finding(
                "NO_REVISION_HISTORY",
                Severity.WARNING,
                "no last-modified timestamp and no change log. Arrivals can be replayed "
                "-- which bookings existed at a given instant -- but revisions cannot: "
                "the cancellations, re-times and reassignments that changed the board "
                "during the day are only visible in their final state. That is most of "
                "what a dispatcher actually reacts to.",
                columns=("record_updated_known_at",),
            )
        )

    source_answer = declarations.get("knowledge_time_source")
    if not _present(source_answer):
        findings.append(
            Finding(
                "KNOWLEDGE_TIME_SOURCE_UNDECLARED",
                Severity.WARNING,
                "a knowledge timestamp is present but nothing says what writes it. A "
                "`created_at` written by a warehouse load is the load time wearing a "
                "disguise and is indistinguishable from the real thing by inspection. "
                "Which system stamps it, and at what moment?",
            )
        )

    return _KnowledgeAssessment(
        created_present=True,
        created_complete=rows_missing == 0,
        created_rows_missing=rows_missing,
        usable_for_replay=usable,
        updated_usable=updated_usable and usable,
        reasons=tuple(reasons),
    )


def _verdicts(
    *,
    present: Sequence[str],
    resolved: Mapping[str, _Column],
    declarations: Mapping[str, object],
    knowledge: _KnowledgeAssessment,
    served_only: bool,
    vehicle_ref_usable: bool,
    fleet_shape_resolved: bool,
) -> tuple[CapabilityVerdict, ...]:
    present_set = set(present)
    if not vehicle_ref_usable:
        present_set.discard("vehicle_ref")

    out: list[CapabilityVerdict] = []
    for cap in CAPABILITIES:
        reasons: list[str] = []
        verdict = Verdict.SUPPORTED

        missing_required = [
            name
            for name in cap.requires
            if name not in present_set and not _declared(name, declarations)
            # An unreadable answer is not an answer. Without this, "not sure"
            # satisfies the fleet-shape requirement by being non-empty, and the
            # gate that fails closed elsewhere would be bypassed here.
            or (name == "fleet_shape" and not fleet_shape_resolved)
        ]
        if missing_required:
            verdict = Verdict.NOT_SUPPORTED
            for name in missing_required:
                spec = FIELDS_BY_NAME.get(name)
                if name in _ABSENCE_PHRASE:
                    reasons.append(_ABSENCE_PHRASE[name])
                elif spec is None:
                    reasons.append(f"`{name}` is absent")
                elif spec.shape is Shape.DECLARATION:
                    reasons.append(
                        f"the `{name}` question is unanswered -- {spec.operator_question}"
                    )
                else:
                    reasons.append(f"no `{name}` column is present")

        if cap.requires_any and not (set(cap.requires_any) & present_set):
            verdict = Verdict.NOT_SUPPORTED
            reasons.append(
                "none of " + " / ".join(f"`{name}`" for name in cap.requires_any) + " is usable"
            )

        # Capability-specific rules that a field-presence check cannot express.
        if cap.id in ("information_set_replay", "intraday_state_replay", "counterfactual_comparison"):
            if knowledge.created_present and not knowledge.usable_for_replay:
                verdict = Verdict.NOT_SUPPORTED
                reasons.extend(knowledge.reasons)
            elif verdict is not Verdict.NOT_SUPPORTED and knowledge.created_rows_missing:
                verdict = Verdict.SUPPORTED_WITH_LIMITS
                reasons.extend(knowledge.reasons)

        if cap.id == "intraday_state_replay" and verdict is not Verdict.NOT_SUPPORTED:
            if not knowledge.updated_usable:
                verdict = Verdict.NOT_SUPPORTED
                reasons.append(
                    "no revision is visible in the sample, so the board can be rebuilt "
                    "from arrivals but not from the changes made during the day"
                )

        if cap.id == "counterfactual_comparison" and verdict is not Verdict.NOT_SUPPORTED:
            # Fails closed: supported only on a clear YES. The unsafe direction
            # here is reading "no, our scheduler does not log candidates" as an
            # affirmative and then recording alternatives=() -- an assertion that
            # nothing else was considered, which is a fabricated and flattering
            # finding, and the exact hazard ADR-0072 flagged.
            answer = declarations.get("alternatives_logged")
            if not _reads_as_yes(answer):
                verdict = Verdict.NOT_SUPPORTED
                if _reads_as_no(answer):
                    reasons.append(
                        "your scheduler does not log the candidates it rejected, so the "
                        "alternatives for a historical decision are UNKNOWN rather than "
                        "empty. Recording them as empty would assert that nothing else "
                        "was considered, which is a fabricated -- and flattering -- "
                        "finding"
                    )
                else:
                    reasons.append(
                        "we could not read the alternatives-logged answer as a yes, and "
                        "the difference between 'nothing else was considered' and 'we do "
                        "not know what else was considered' is not something to assume"
                    )

        if cap.id == "unmet_demand_forecasting" and served_only:
            verdict = Verdict.NOT_SUPPORTED
            reasons.append(
                "every row in the sample is a served trip, so demand that was refused "
                "or cancelled is not in the file at all"
            )

        if cap.id == "deadhead_measurement" and verdict is Verdict.SUPPORTED:
            # The two sharpeners are not interchangeable and a single "any of
            # them is present" check would let mileage stand in for the dropoff
            # time. Only the dropoff time turns a bound into a measurement.
            if resolved["actual_dropoff_at"].populated == 0:
                verdict = Verdict.SUPPORTED_WITH_LIMITS
                reasons.append(
                    "no actual dropoff time, so the empty leg is measured pickup-to-"
                    "pickup and includes the in-service time: the figure is an upper "
                    "bound and would be reported as one"
                )
            if resolved["trip_distance"].populated == 0:
                reasons.append(
                    "no per-trip mileage, so deadhead is reported in minutes only and "
                    "cannot be cross-checked against the miles you already file"
                )

        # There was a `row_count == 0 -> NOT_SUPPORTED` special case here. A
        # mutation deleting it came back GREEN, and the mutation was right: every
        # capability requires at least one COLUMN (asserted by conformance test),
        # so an empty sample already reports every capability unsupported through
        # the ordinary missing-column path -- and does it better, because the
        # reasons name the columns instead of restating that the file was empty.
        # Removed rather than kept as unreachable defence with a test written to
        # cover it, which is how a redundant branch survives review forever.
        out.append(
            CapabilityVerdict(
                capability_id=cap.id,
                capability_name=cap.name,
                verdict=verdict,
                reasons=tuple(reasons),
            )
        )
    return tuple(out)


def _declared(name: str, declarations: Mapping[str, object]) -> bool:
    """A declaration is satisfied by an answer; a companion TABLE is satisfied by
    the operator saying they have sent one. Neither is a column, so neither can
    be found by reading the trip export -- and treating a missing answer as a
    missing column would report "no run roster" as a data defect rather than as
    an unanswered question."""
    spec = FIELDS_BY_NAME.get(name)
    if spec is None or spec.shape is Shape.COLUMN:
        return False
    return _present(declarations.get(name))


# ---------------------------------------------------------------------------
# File entry points
# ---------------------------------------------------------------------------

def assess_csv(
    path: str | Path,
    *,
    declarations: Mapping[str, object] | None = None,
    column_map: Mapping[str, str] | None = None,
) -> ContractAssessment:
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return assess(
        rows,
        declarations=declarations,
        column_map=column_map,
        source=str(path),
    )


def _main(argv: Sequence[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    sample = argv[0]
    declarations: dict[str, object] = {}
    column_map: dict[str, str] = {}
    as_json = False
    index = 1
    while index < len(argv):
        flag = argv[index]
        if flag == "--declarations":
            declarations = json.loads(Path(argv[index + 1]).read_text(encoding="utf-8"))
            index += 2
        elif flag == "--column-map":
            column_map = json.loads(Path(argv[index + 1]).read_text(encoding="utf-8"))
            index += 2
        elif flag == "--json":
            as_json = True
            index += 1
        else:
            print(f"unknown argument: {flag}")
            return 2
    assessment = assess_csv(sample, declarations=declarations, column_map=column_map)
    if as_json:
        print(json.dumps(assessment.as_dict(), indent=2, sort_keys=True))
    else:
        print(assessment.report())
    # A refused export is an exit code, so this can sit in a pipeline. A missing
    # capability is NOT: an export that supports outcome analysis and not replay
    # is a normal, useful answer, not a failure.
    return 1 if assessment.refused else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
