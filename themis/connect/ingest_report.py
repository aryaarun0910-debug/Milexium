"""The ingest quality report: what an operator gets back instead of "your
export is malformed".

An operator who sends a first extract needs one thing from us -- a list of
changes they can make. `themis.connect.operator_export` already produces the
raw material for that (a verdict and a reason per row, a `coerced` record per
repair) but it produces it ONE ROW AT A TIME, and a per-row verdict is not a
diagnosis. Three thousand identical quarantine reasons is a single sentence
("your `TripStatus` codes are numeric and we have no mapping for them"), and
nobody is going to read three thousand lines to find it.

So this module turns a batch of `AdapterResult`s back into the sentence:

- **What happened to the file** -- rows total / mapped / repaired / quarantined,
  and separately `rows_structural`: repeated header rows and blank lines, which
  are FILE-assembly artefacts rather than data defects. That split matters more
  than it looks. "40% of your rows were rejected" ends a conversation; "8% were
  rejected and 32% were the header line repeated by whatever concatenated your
  monthly extracts" is a fix.
- **Why rows were rejected** -- quarantine reasons grouped into stable codes with
  counts, most frequent first, each with the adapter's own full text for one
  example so the reason is never paraphrased by this module.
- **What we changed** -- every repair rule that fired, with counts, the columns
  it fired on, and an example. An operator can audit the repairs, and a reviewer
  can reverse them, because each record names the original value.
- **Which required fields are missing** -- ranked, so the largest single fix is
  first.
- **Whether the missingness is CORRELATED** -- see below. This is the item that
  justifies the module.

WHY CORRELATED MISSINGNESS GETS ITS OWN SECTION
ADR-0039 tore down a real, well-maintained PUBLIC feed (NYC TLC FHVHV, one real
week) and found that 32.6% of rows publish no on-scene timestamp -- and that the
missingness is not independent: the operators who omit `originating_base_num`
are the same ones who omit the timestamp. Re-keying that week on the base id put
10,918 segments and 213,936 revenue minutes into `unattributable`, whose empty
time is EXACTLY ZERO. A pipeline that dropped null-id rows would have deleted
real vehicle minutes from every denominator and reported a deadhead percentage
that was wrong in a direction nobody would have noticed.

If that is true of a public feed maintained by a regulator, it is true of an
operator's internal export. So this report measures it rather than hoping: for
every pair of intake columns it computes the 2x2 missing/present table and the
phi coefficient (the Pearson correlation between two binary variables), and
names the pairs that co-miss far more than independence would predict. The
counts are published alongside the coefficient so the operator can check the
arithmetic.

WHAT THIS REPORT IS NOT
- **Not a significance test.** phi is a descriptive coefficient. There is no
  p-value, no multiple-comparison correction, and with a handful of rows a phi
  of 1.0 means almost nothing. `MissingnessDiagnosis.note` says so in the
  artefact, not just here.
- **Not a PII scanner.** It reports column NAMES, counts, and the adapter's own
  reason text. The only values it ever echoes are the ones the adapter already
  chose to retain in a repair record, and it never touches a quarantined row's
  preserved values.
- **Not a verdict on whether to accept the export.** That is a human decision
  about a specific engagement.

Status: **Exists** (v0.1). Demonstrated against a deliberately awful SYNTHETIC
corpus (`aletheia/conformance/property-tests/test_messy_operator_data.py`). No real
operator export has ever been received.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, model_validator

from themis.connect.adapter import AdapterResult, parse_batch
from themis.connect.operator_export import (
    AMBIGUOUS_DATE_MARKER,
    CANONICAL_COLUMNS,
    DATE_ONLY_PICKUP_MARKER,
    EMPTY_ROW_MARKER,
    NAIVE_TIMESTAMP_MARKER,
    OPTIONAL_COLUMNS,
    REPAIR_RULES,
    REPEATED_HEADER_MARKER,
    REQUIRED_COLUMNS,
    VEHICLE_OR_RUN_COLUMNS,
    OperatorExportAdapter,
    OperatorTripRecord,
    repair_rule_of,
    resolve_intake_columns,
)
from themis.connect.operator_export import _present as _adapter_present

# `_present` is imported by its private name on purpose. "Absent" has a precise
# and slightly surprising definition here -- a missing key, None, a pandas
# NaN/NaT/NA, or a string that is empty once zero-width characters are stripped
# -- and a report that used a second, simpler definition would disagree with the
# adapter about which rows were missing a field. One definition, one place.

INGEST_REPORT_VERSION = "0.1.0"

CORRELATION_THRESHOLD = 0.5
"""|phi| at or above which a pair of columns is reported as co-missing. Chosen
to be loose rather than strict: the cost of naming a pair that turns out to be
coincidence is one sentence an operator can dismiss, and the cost of missing a
real one is a biased denominator nobody ever sees. It is a REPORTING threshold,
not a test statistic."""

MIN_ROWS_FOR_MISSINGNESS = 4
"""Below this the diagnosis is suppressed entirely rather than published with a
caveat. A correlation over three rows is noise wearing a number."""

MAX_REPORTED_PAIRS = 10
"""Ten canonical columns make forty-five pairs. Publishing all of them buries
the one that matters, so the report ranks by |phi| and truncates -- and says how
many it truncated, because a silently truncated list is a lie by omission."""

STRUCTURAL_CODES = frozenset({"repeated_header_row", "empty_row"})
"""Quarantine codes that describe the FILE rather than the data in it. Counted
separately everywhere, because folding them into a defect rate overstates how
bad an operator's scheduling data actually is."""

# Ordered most-specific-first. The marker phrases are imported constants from
# the adapter, not literals repeated here: a phrase that drifts silently is how
# a report starts lying about what the adapter did.
_QUARANTINE_CODES: tuple[tuple[str, str], ...] = (
    ("street address (found in the value of a zone column)", "pii_address_in_zone"),
    ("direct rider/staff identifiers", "pii_direct_identifier"),
    (REPEATED_HEADER_MARKER, "repeated_header_row"),
    (EMPTY_ROW_MARKER, "empty_row"),
    (AMBIGUOUS_DATE_MARKER, "ambiguous_date_order"),
    (DATE_ONLY_PICKUP_MARKER, "date_only_pickup_time"),
    ("missing required field(s)", "missing_required_field"),
    ("neither vehicle_ref nor run_ref", "no_vehicle_or_run_ref"),
    ("unknown outcome value", "unknown_outcome_value"),
    ("outcome says the trip was served but actual_pickup_at is absent", "served_without_actual_pickup"),
    ("before requested_at", "timestamp_before_request"),
    ("both resolve to the", "duplicate_column_mapping"),
    ("is not a UTC offset", "unparseable_timestamp"),
    ("timestamp", "unparseable_timestamp"),
    ("adapter raised", "adapter_exception"),
)

QUARANTINE_CODES: tuple[str, ...] = tuple(dict.fromkeys(code for _, code in _QUARANTINE_CODES)) + (
    "unclassified",
)
"""Every verdict code this report can emit. `unclassified` exists so a reason
the adapter grows tomorrow is counted honestly rather than silently bucketed
into the nearest existing code."""

_DIAGNOSED_COLUMNS: tuple[str, ...] = CANONICAL_COLUMNS


def classify_quarantine_reason(reason: str) -> str:
    """An adapter quarantine reason -> a stable code for counting."""
    for marker, code in _QUARANTINE_CODES:
        if marker in reason:
            return code
    return "unclassified"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _share(part: int, whole: int) -> float:
    """Every rate in this report goes through here. An empty export and an
    export where every row quarantines are both normal inputs -- the report has
    to stay useful for exactly those two, so there is one division and it is
    guarded once."""
    return 0.0 if whole <= 0 else round(part / whole, 6)


class QuarantineReasonCount(BaseModel):
    """One rejection cause, with the adapter's own words for one example."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    count: int
    share_of_rows: float
    structural: bool
    failed_fields: tuple[str, ...]
    example_reason: str


class RepairRuleCount(BaseModel):
    """One repair rule that fired, and what it did.

    `records` can exceed `rows` -- a single row with three whitespace-padded
    columns is one row and three repairs -- and both are published because the
    first answers "how much of my file did you touch" and the second answers
    "how many changes do I have to review"."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule: str
    what_it_does: str
    records: int
    rows: int
    columns: tuple[str, ...]
    example_reason: str


class FieldGap(BaseModel):
    """How often one intake column was absent, over the WHOLE batch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    column: str
    source_columns: tuple[str, ...]
    required: bool
    missing_rows: int
    missing_share: float


class MissingnessPair(BaseModel):
    """The 2x2 table for two columns' missingness, plus its phi coefficient.

    The four counts are published so an operator can redo the arithmetic;
    `expected_both_if_independent` is what `both_missing` would be if the two
    columns went missing for unrelated reasons, which is the comparison that
    makes the number mean something.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    columns: tuple[str, str]
    both_missing: int
    only_first_missing: int
    only_second_missing: int
    neither_missing: int
    expected_both_if_independent: float
    lift: float | None
    phi: float

    @model_validator(mode="after")
    def _pair_is_ordered_and_distinct(self) -> "MissingnessPair":
        first, second = self.columns
        if first >= second:
            raise ValueError("a missingness pair must name two distinct columns in sorted order")
        return self


class MissingnessDiagnosis(BaseModel):
    """Whether the gaps in this export cluster, or fall independently.

    `verdict` is deliberately coarse. The interesting distinction is not "how
    correlated" but "is this the failure mode ADR-0039 hit", and a four-value
    verdict an operations director can read beats a matrix they will not.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rows_considered: int
    structural_rows_excluded: int
    columns_considered: tuple[str, ...]
    verdict: Literal["insufficient_rows", "no_missingness", "looks_independent", "correlated"]
    correlated_pairs: tuple[MissingnessPair, ...]
    mutually_exclusive_pairs: tuple[MissingnessPair, ...]
    pairs_examined: int
    strongest_pair: MissingnessPair | None
    note: str


class IdentifierFormatDrift(BaseModel):
    """An identifier column written in more than one shape within one file.

    NOT repaired, and the refusal is the point: `UNIT-412`, `412` and `unit412`
    might be one vehicle written three ways or three different vehicles, and
    picking one collapses or splits a fleet. Deadhead is measured by chaining a
    single vehicle's consecutive trips, so getting this wrong does not produce a
    slightly worse number -- it produces a confidently wrong one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    column: str
    distinct_shapes: int
    shapes: tuple[tuple[str, int], ...]
    note: str


class IngestQualityReport(BaseModel):
    """The whole diagnosis, as one returnable structure.

    Every count is over the rows actually submitted, including the quarantined
    ones -- a missingness figure computed only over rows that IMPORTED is
    conditioned on success and is exactly the statistic that hides a systematic
    gap.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_version: str = INGEST_REPORT_VERSION
    adapter_name: str
    adapter_version: str

    rows_total: int
    rows_mapped: int
    rows_repaired: int
    rows_quarantined: int
    rows_structural: int

    mapped_share: float
    repaired_share: float
    quarantined_share: float

    quarantine_reasons: tuple[QuarantineReasonCount, ...]
    repair_rules: tuple[RepairRuleCount, ...]
    required_field_gaps: tuple[FieldGap, ...]
    optional_field_gaps: tuple[FieldGap, ...]
    missingness: MissingnessDiagnosis
    identifier_drift: tuple[IdentifierFormatDrift, ...]
    warnings: tuple[str, ...]

    @model_validator(mode="after")
    def _counts_reconcile(self) -> "IngestQualityReport":
        if self.rows_mapped + self.rows_quarantined != self.rows_total:
            raise ValueError("mapped + quarantined must equal the rows submitted")
        if self.rows_structural > self.rows_quarantined:
            raise ValueError("structural rows are a subset of the quarantined rows")
        if self.rows_repaired > self.rows_mapped:
            raise ValueError("only a mapped row can carry a repair")
        return self

    @property
    def headline(self) -> str:
        if self.rows_total == 0:
            return "No rows were submitted, so there is nothing to diagnose."
        parts = [
            f"{self.rows_total} rows: {self.rows_mapped} imported "
            f"({self.mapped_share:.1%}), {self.rows_quarantined} set aside "
            f"({self.quarantined_share:.1%})"
        ]
        if self.rows_structural:
            parts.append(
                f"{self.rows_structural} of those are file-assembly artefacts (repeated header "
                "rows or blank lines), not data defects"
            )
        if self.rows_repaired:
            parts.append(
                f"{_plural(self.rows_repaired, 'imported row')} needed a recorded repair"
            )
        return "; ".join(parts) + "."

    def to_text(self) -> str:
        """The report as an operator would read it. Deliberately plain: this is
        the thing that gets pasted into an email."""

        lines = [
            "MILEXIUM INGEST QUALITY REPORT",
            f"adapter {self.adapter_name} v{self.adapter_version} / report v{self.report_version}",
            "",
            self.headline,
            "",
        ]
        if self.quarantine_reasons:
            lines.append("WHY ROWS WERE SET ASIDE (most frequent first)")
            for entry in self.quarantine_reasons:
                tag = " [file artefact]" if entry.structural else ""
                fields = f" -- fields: {', '.join(entry.failed_fields)}" if entry.failed_fields else ""
                lines.append(
                    f"  {entry.count:>6}  {entry.share_of_rows:>7.1%}  {entry.code}{tag}{fields}"
                )
                lines.append(f"          e.g. {entry.example_reason}")
            lines.append("")
        if self.repair_rules:
            lines.append("WHAT WE REPAIRED (every change is recorded and reversible in review)")
            for rule in self.repair_rules:
                lines.append(
                    f"  {rule.records:>6} {'change' if rule.records == 1 else 'changes'} in "
                    f"{_plural(rule.rows, 'row')}  {rule.rule} -- {', '.join(rule.columns)}"
                )
                lines.append(f"          {rule.what_it_does}")
                lines.append(f"          e.g. {rule.example_reason}")
            lines.append("")
        gaps = [gap for gap in self.required_field_gaps if gap.missing_rows]
        if gaps:
            lines.append("REQUIRED FIELDS MOST OFTEN MISSING")
            for gap in gaps:
                lines.append(
                    f"  {gap.missing_rows:>6}  {gap.missing_share:>7.1%}  {gap.column} "
                    f"(your column(s): {', '.join(gap.source_columns) or 'not present in the file'})"
                )
            lines.append("")
        lines.append("MISSINGNESS -- do gaps cluster, or fall independently?")
        lines.append(f"  verdict: {self.missingness.verdict}")
        lines.append(f"  {self.missingness.note}")
        for pair in self.missingness.correlated_pairs:
            first, second = pair.columns
            lines.append(
                f"  co-missing: {first} + {second} -- blank together in {pair.both_missing} rows, "
                f"{pair.expected_both_if_independent:.1f} expected if unrelated (phi {pair.phi:+.2f})"
            )
        for pair in self.missingness.mutually_exclusive_pairs:
            first, second = pair.columns
            lines.append(
                f"  alternating: {first} + {second} -- one or the other, rarely both "
                f"(phi {pair.phi:+.2f})"
            )
        lines.append("")
        if self.identifier_drift:
            lines.append("IDENTIFIER FORMATS THAT CHANGE WITHIN THE FILE")
            lines.append(
                "  NOT repaired. 'UNIT-412' and '412' may be one vehicle written two ways or two "
                "different vehicles, and deadhead is measured by chaining a single vehicle's"
            )
            lines.append(
                "  consecutive trips -- guessing here would not degrade the answer, it would "
                "produce a confidently wrong one. Normalise at source, or send us the rule."
            )
            for drift in self.identifier_drift:
                shapes = ", ".join(f"{shape} x{count}" for shape, count in drift.shapes)
                lines.append(f"    {drift.column}: {drift.distinct_shapes} shapes -- {shapes}")
            lines.append("  (shape key: 9 = a run of digits, A = a run of letters)")
            lines.append("")
        if self.warnings:
            lines.append("WORTH KNOWING")
            for warning in self.warnings:
                lines.append(f"  - {warning}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------
# Building the report
# --------------------------------------------------------------------------


def value_shape(value: object) -> str:
    """A value's SHAPE, with the content thrown away: 'UNIT-412' -> 'A-9',
    '412' -> '9', 'unit412' -> 'A9'.

    Runs of the same character class collapse to one symbol, so 'UNIT-412' and
    'BUS-7' share a shape while 'UNIT-412' and '412' do not. Content is
    discarded deliberately -- the shape is safe to publish in a report, an
    identifier is not necessarily."""

    out: list[str] = []
    for character in str(value):
        if character.isdigit():
            symbol = "9"
        elif character.isalpha():
            symbol = "A"
        elif character.isspace():
            symbol = " "
        else:
            symbol = character
        if out and out[-1] == symbol:
            continue
        out.append(symbol)
    return "".join(out) or "<empty>"


def _phi(n11: int, n10: int, n01: int, n00: int) -> float | None:
    """The phi coefficient for a 2x2 table, or None when it is undefined.

    Undefined means a margin is zero -- a column that is never missing, or
    always missing, has no variance to correlate with anything. Returning None
    rather than 0.0 keeps "no relationship" and "no information" distinct."""

    row_missing, row_present = n11 + n10, n01 + n00
    column_missing, column_present = n11 + n01, n10 + n00
    denominator = row_missing * row_present * column_missing * column_present
    if denominator == 0:
        return None
    return (n11 * n00 - n10 * n01) / math.sqrt(denominator)


def _missing_matrix(
    raw_rows: Sequence[Mapping[str, object]], column_map: Mapping[str, str]
) -> tuple[dict[str, list[bool]], dict[str, set[str]]]:
    """Per canonical column, one bool per row: was it absent? Plus the operator's
    own column name(s) that fed it, for reporting back in their vocabulary.

    Resolution goes through the adapter's own `resolve_intake_columns`, so the
    report diagnoses exactly the columns the adapter read -- not a second,
    slightly-different guess at them."""

    missing: dict[str, list[bool]] = {column: [] for column in _DIAGNOSED_COLUMNS}
    sources: dict[str, set[str]] = defaultdict(set)
    for row in raw_rows:
        resolved, _ = resolve_intake_columns(row, column_map)
        for column in _DIAGNOSED_COLUMNS:
            if column in resolved:
                source, value = resolved[column]
                sources[column].add(source)
                missing[column].append(not _adapter_present(value))
            else:
                missing[column].append(True)
    return missing, sources


def _diagnose_missingness(
    missing: dict[str, list[bool]], rows: int, structural_excluded: int
) -> MissingnessDiagnosis:
    """Is the missingness in this export clustered, or scattered?

    Structural rows (repeated headers, blank lines) are excluded by the caller
    before this runs. Leaving them in would be actively misleading: a blank line
    is missing EVERY column at once, so a handful of them drive every pair to
    phi = 1.0 and bury the one real signal under forty spurious ones.
    """

    def empty(verdict, note):
        return MissingnessDiagnosis(
            rows_considered=rows,
            structural_rows_excluded=structural_excluded,
            columns_considered=(),
            verdict=verdict,
            correlated_pairs=(),
            mutually_exclusive_pairs=(),
            pairs_examined=0,
            strongest_pair=None,
            note=note,
        )

    if rows < MIN_ROWS_FOR_MISSINGNESS:
        return empty(
            "insufficient_rows",
            f"{rows} row(s) of real data is below the {MIN_ROWS_FOR_MISSINGNESS}-row floor for this "
            "check, so no missingness diagnosis is offered. A correlation over three rows is noise "
            "wearing a number, and publishing one would be worse than publishing nothing.",
        )
    if not any(any(missing[column]) for column in _DIAGNOSED_COLUMNS):
        return empty(
            "no_missingness",
            "No intake column is absent in any row, so there is no missingness to correlate.",
        )

    varying = tuple(column for column in _DIAGNOSED_COLUMNS if 0 < sum(missing[column]) < rows)

    pairs: list[MissingnessPair] = []
    for index, first in enumerate(varying):
        for second in varying[index + 1 :]:
            n11 = n10 = n01 = n00 = 0
            for a, b in zip(missing[first], missing[second]):
                if a and b:
                    n11 += 1
                elif a:
                    n10 += 1
                elif b:
                    n01 += 1
                else:
                    n00 += 1
            phi = _phi(n11, n10, n01, n00)
            if phi is None:
                continue
            expected = (n11 + n10) * (n11 + n01) / rows
            ordered = tuple(sorted((first, second)))
            swapped = ordered[0] != first
            pairs.append(
                MissingnessPair(
                    columns=ordered,
                    both_missing=n11,
                    only_first_missing=n01 if swapped else n10,
                    only_second_missing=n10 if swapped else n01,
                    neither_missing=n00,
                    expected_both_if_independent=round(expected, 4),
                    lift=None if expected == 0 else round(n11 / expected, 4),
                    phi=round(phi, 6),
                )
            )

    pairs.sort(key=lambda pair: (-abs(pair.phi), pair.columns))
    # Only POSITIVE phi is the ADR-0039 hazard: it means two columns go blank in
    # the same rows, so dropping those rows removes a non-random slice. Negative
    # phi means the opposite -- the columns are populated alternately, which for
    # vehicle_ref/run_ref is the intended either-or shape of the field list, not
    # a defect. Reporting the two under one heading would call a correct export
    # broken.
    correlated = tuple(pair for pair in pairs if pair.phi >= CORRELATION_THRESHOLD)
    exclusive = tuple(pair for pair in pairs if pair.phi <= -CORRELATION_THRESHOLD)
    truncated = max(0, len(correlated) - MAX_REPORTED_PAIRS)

    if not pairs:
        verdict = "looks_independent"
        note = (
            "Every column that goes missing at all is missing in EVERY row, so there is no variation "
            "left to correlate. That is itself worth knowing: a column absent from the whole file is "
            "a mapping or export problem, not a data-quality one."
        )
    elif correlated:
        verdict = "correlated"
        note = (
            f"{len(correlated)} of {len(pairs)} column pair(s) go missing TOGETHER far more often "
            f"than independence would predict (phi >= {CORRELATION_THRESHOLD})"
            + (f"; the {MAX_REPORTED_PAIRS} strongest are listed" if truncated else "")
            + ". This is the failure mode ADR-0039 found in a real, well-maintained PUBLIC feed: the "
            "operators omitting one field were the same ones omitting another, so dropping the "
            "incomplete rows removed a non-random slice of service from every denominator and biased "
            "the result in a direction nobody could see. It is why rows that cannot be imported are "
            "REPORTED here rather than filtered away. Honest limit: this is a descriptive "
            "coefficient over the rows submitted -- no significance test, no correction for the "
            "number of pairs examined, and a small sample can produce a phi of 1.0 by coincidence."
        )
    else:
        verdict = "looks_independent"
        note = (
            f"No column pair co-misses strongly enough to look systematic (phi < "
            f"{CORRELATION_THRESHOLD} for all {len(pairs)} pairs examined). Gaps in this sample look "
            "independent, so dropping incomplete rows would bias aggregates less than it otherwise "
            "might. Honest limit: this is a descriptive check over the rows submitted, not a "
            "statistical test, and a larger extract can still reveal a pattern this one does not."
        )
    if exclusive:
        note += (
            f" Separately, {len(exclusive)} pair(s) are populated ALTERNATELY rather than together "
            "(negative phi). For vehicle_ref/run_ref that is the intended either-or shape of the "
            "field list and not a defect; for any other pair it usually means two columns carrying "
            "one fact between them."
        )

    return MissingnessDiagnosis(
        rows_considered=rows,
        structural_rows_excluded=structural_excluded,
        columns_considered=varying,
        verdict=verdict,
        correlated_pairs=correlated[:MAX_REPORTED_PAIRS],
        mutually_exclusive_pairs=exclusive[:MAX_REPORTED_PAIRS],
        pairs_examined=len(pairs),
        strongest_pair=pairs[0] if pairs else None,
        note=note,
    )


def _identifier_drift(
    raw_rows: Sequence[Mapping[str, object]], column_map: Mapping[str, str]
) -> tuple[IdentifierFormatDrift, ...]:
    shapes: dict[str, Counter] = {column: Counter() for column in ("trip_ref", *VEHICLE_OR_RUN_COLUMNS)}
    for row in raw_rows:
        resolved, _ = resolve_intake_columns(row, column_map)
        for column in shapes:
            if column in resolved and _adapter_present(resolved[column][1]):
                shapes[column][value_shape(resolved[column][1])] += 1

    drift: list[IdentifierFormatDrift] = []
    for column, counter in shapes.items():
        if len(counter) < 2:
            continue
        drift.append(
            IdentifierFormatDrift(
                column=column,
                distinct_shapes=len(counter),
                shapes=tuple((shape, count) for shape, count in counter.most_common(5)),
                note=(
                    f"{column} is written in {len(counter)} different shapes within one file. "
                    "Milexium does NOT normalise these: 'UNIT-412' and '412' may be one vehicle "
                    "written two ways or two different vehicles, and deadhead is measured by "
                    "chaining a single vehicle's consecutive trips -- guessing here would not "
                    "degrade the answer, it would produce a confidently wrong one. If they are the "
                    "same entity, normalise at source or tell us the rule and we will apply it "
                    "explicitly."
                ),
            )
        )
    return tuple(drift)


def _timestamp_clock_warning(
    results: Sequence[AdapterResult[OperatorTripRecord]],
) -> list[str]:
    """One export, two clocks: some rows carrying a UTC offset and some not, in
    the same column, means the file was assembled from two sources. Every naive
    row is then silently shifted by the local offset, which is the difference
    between an on-time figure and a wrong one."""

    naive_rows: Counter = Counter()
    mapped = 0
    for result in results:
        if result.record is None:
            continue
        mapped += 1
        for loss in result.semantic_loss:
            if NAIVE_TIMESTAMP_MARKER in loss.reason and repair_rule_of(loss) is None:
                for column in loss.source_field.split(", "):
                    naive_rows[column] += 1

    warnings: list[str] = []
    for column, count in sorted(naive_rows.items()):
        if 0 < count < mapped:
            warnings.append(
                f"{column}: {count} of {mapped} imported rows carried NO UTC offset and were read "
                "as UTC; the rest carried one (or omitted the column). One column, two clocks -- so "
                "if the offset-less rows are agency local time, every one of them is shifted by "
                "your local offset while its neighbours are not. This usually means the file was "
                "assembled from two sources."
            )
        elif count == mapped and mapped:
            warnings.append(
                f"{column} carries no UTC offset in any imported row and was read as UTC "
                "throughout. If the export is in agency local time, every trip is shifted by that "
                "offset and any on-time or headway figure derived from it is wrong by the same "
                "amount. Sending an explicit offset removes the assumption entirely."
            )
    return warnings


def build_ingest_report(
    adapter: OperatorExportAdapter,
    raw_rows: Sequence[Mapping[str, object]],
    results: Sequence[AdapterResult[OperatorTripRecord]] | None = None,
) -> IngestQualityReport:
    """Diagnose a batch. `results` may be supplied when the caller has already
    parsed (so a report never re-runs an import); omitted, the batch is parsed
    here through the same `parse_batch` any caller would use.

    The raw rows are needed as well as the results because a quarantined row's
    values are only reachable through the quarantine record, and a missingness
    figure computed over the IMPORTED rows alone is conditioned on success --
    precisely the statistic that hides a systematic gap.
    """

    raw_rows = list(raw_rows)
    if results is None:
        results = parse_batch(adapter, [dict(row) for row in raw_rows])
    results = list(results)
    if len(results) != len(raw_rows):
        raise ValueError(
            f"{len(raw_rows)} rows and {len(results)} results: a report must describe the batch it "
            "was given, one verdict per row"
        )

    rows_total = len(raw_rows)
    column_map = adapter.column_map

    # -- verdicts ----------------------------------------------------------
    reason_counts: Counter = Counter()
    reason_fields: dict[str, set[str]] = defaultdict(set)
    reason_examples: dict[str, str] = {}
    rows_quarantined = rows_structural = 0
    is_structural: list[bool] = []
    for result in results:
        if result.quarantine is None:
            is_structural.append(False)
            continue
        rows_quarantined += 1
        code = classify_quarantine_reason(result.quarantine.reason)
        is_structural.append(code in STRUCTURAL_CODES)
        reason_counts[code] += 1
        reason_examples.setdefault(code, result.quarantine.reason)
        if result.quarantine.failed_field:
            reason_fields[code].add(result.quarantine.failed_field)
        if code in STRUCTURAL_CODES:
            rows_structural += 1

    quarantine_reasons = tuple(
        QuarantineReasonCount(
            code=code,
            count=count,
            share_of_rows=_share(count, rows_total),
            structural=code in STRUCTURAL_CODES,
            failed_fields=tuple(sorted(reason_fields[code])),
            example_reason=reason_examples[code],
        )
        for code, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
    )

    # -- repairs -----------------------------------------------------------
    rule_records: Counter = Counter()
    rule_rows: Counter = Counter()
    rule_columns: dict[str, set[str]] = defaultdict(set)
    rule_examples: dict[str, str] = {}
    rows_repaired = rows_mapped = 0
    for result in results:
        if result.record is None:
            continue
        rows_mapped += 1
        fired: set[str] = set()
        for loss in result.semantic_loss:
            rule = repair_rule_of(loss)
            if rule is None:
                continue
            rule_records[rule] += 1
            rule_columns[rule].add(loss.source_field)
            rule_examples.setdefault(rule, loss.reason)
            fired.add(rule)
        for rule in fired:
            rule_rows[rule] += 1
        if fired:
            rows_repaired += 1

    repair_rules = tuple(
        RepairRuleCount(
            rule=rule,
            what_it_does=REPAIR_RULES[rule],
            records=count,
            rows=rule_rows[rule],
            columns=tuple(sorted(rule_columns[rule])),
            example_reason=rule_examples[rule],
        )
        for rule, count in sorted(rule_records.items(), key=lambda item: (-item[1], item[0]))
    )

    # -- missingness -------------------------------------------------------
    # Field gaps are counted over EVERY submitted row -- an operator asking
    # "which required field do I most often omit" wants the whole file. The
    # correlation and identifier-drift checks run over the data rows only: a
    # blank line is missing every column at once, so a few of them drive every
    # pair to phi = 1.0 and bury the one real signal under forty spurious ones.
    missing, sources = _missing_matrix(raw_rows, column_map)
    data_rows = [row for row, structural in zip(raw_rows, is_structural) if not structural]
    data_missing, _ = _missing_matrix(data_rows, column_map)

    def gaps(columns: Sequence[str]) -> tuple[FieldGap, ...]:
        entries = [
            FieldGap(
                column=column,
                source_columns=tuple(sorted(sources[column])),
                required=column in REQUIRED_COLUMNS,
                missing_rows=sum(missing[column]),
                missing_share=_share(sum(missing[column]), rows_total),
            )
            for column in columns
        ]
        entries.sort(key=lambda gap: (-gap.missing_rows, gap.column))
        return tuple(entries)

    optional = tuple(
        column
        for column in _DIAGNOSED_COLUMNS
        if column in OPTIONAL_COLUMNS or column in VEHICLE_OR_RUN_COLUMNS
    )

    # -- warnings ----------------------------------------------------------
    warnings = _timestamp_clock_warning(results)
    if rows_total == 0:
        warnings.append(
            "The export contained no rows at all. That is not a data-quality verdict: an empty "
            "file usually means the extract's date filter matched nothing, or the header was "
            "written without its body."
        )
    elif rows_mapped == 0:
        warnings.append(
            "Not one row imported. Before treating this as a data-quality problem, check the "
            "column mapping: if the extract's headers are not the ones Milexium was configured "
            "with, every row fails for a reason that has nothing to do with your data."
        )
    fully_absent = [
        column
        for column in REQUIRED_COLUMNS
        if rows_total and sum(missing[column]) == rows_total
    ]
    if fully_absent:
        warnings.append(
            "Required column(s) "
            + ", ".join(fully_absent)
            + " are absent from EVERY row. A column missing everywhere is a mapping or export "
            "problem rather than a data-quality one -- most likely the extract does not include "
            "it, or Milexium was given the wrong header name for it."
        )
    if "date_order_ddmm" in rule_records and "date_order_mmdd" in rule_records:
        warnings.append(
            "This file contains BOTH day-first and month-first dates: some rows could only be read "
            "one way and some only the other. Each was repaired on its own evidence and recorded, "
            "but a single column with two date orders means the file was assembled from two "
            "sources -- and every date in it whose components are both 12 or less is ambiguous and "
            "was set aside. Declare one order and re-export."
        )
    if rows_structural:
        warnings.append(
            f"{rows_structural} of the {rows_quarantined} set-aside rows are file-assembly "
            "artefacts (a repeated header line or a blank row), not defects in your scheduling "
            "data. Removing them changes the rejection rate without changing your data at all."
        )

    return IngestQualityReport(
        adapter_name=adapter.adapter_name,
        adapter_version=adapter.adapter_version,
        rows_total=rows_total,
        rows_mapped=rows_mapped,
        rows_repaired=rows_repaired,
        rows_quarantined=rows_quarantined,
        rows_structural=rows_structural,
        mapped_share=_share(rows_mapped, rows_total),
        repaired_share=_share(rows_repaired, rows_total),
        quarantined_share=_share(rows_quarantined, rows_total),
        quarantine_reasons=quarantine_reasons,
        repair_rules=repair_rules,
        required_field_gaps=gaps(REQUIRED_COLUMNS),
        optional_field_gaps=gaps(optional),
        missingness=_diagnose_missingness(data_missing, len(data_rows), rows_structural),
        identifier_drift=_identifier_drift(data_rows, column_map),
        warnings=tuple(warnings),
    )
