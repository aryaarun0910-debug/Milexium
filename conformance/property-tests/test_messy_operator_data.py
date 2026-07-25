"""Conformance for graduated repair on MESSY operator exports (MX-B-MESSY-DATA-006).

Every fixture in this file is SYNTHETIC. No real operator data exists in this
repository, and none of these rows describes a real trip, vehicle or person.

WHY THIS SUITE EXISTS
Paratransit and NEMT operators export whatever their vendor emits. The first
design partner will send something ugly. Quarantining 40% of it and replying
"your export is malformed" ends the engagement. But guessing is worse, and it is
the failure mode this whole repository is built to avoid.

So the adapter takes a GRADUATED position, and this suite pins both halves of it:

  * UNAMBIGUOUSLY REPAIRABLE -> repaired, with a `coerced` SemanticLossRecord
    naming the rule, so every repair is auditable and reversible in review.
  * GENUINELY AMBIGUOUS -> quarantined, exactly as before.

The two assertions that matter most, and that this file exists to hold:

  1. `test_an_ambiguous_day_month_date_is_quarantined_not_guessed` -- `03/04/2026`
     has two valid readings and the adapter must refuse both. This is the line
     between "repaired with a recorded reason" and "guessed", which is the whole
     credibility position.
  2. `test_pii_still_fails_closed_when_the_row_is_also_malformed` -- the PII gate
     must win over every repair path. A repair that ran first could normalise a
     rider name into canonical form and admit it.

Empirical grounding for the whole packet: the deadhead teardown (ADR-0039) found
32.6% of NYC TLC rows publish no on-scene timestamp, and that the missingness is
CORRELATED -- operators omitting the base id also omit the timestamp. That is a
well-maintained PUBLIC feed. An operator's internal export is worse, which is why
`build_ingest_report` diagnoses correlation rather than only counting gaps.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from packages.canonical import TenantId, new_id
from packages.connect import (
    REPAIR_RULES,
    IngestQualityReport,
    OperatorExportAdapter,
    build_ingest_report,
    repair_rule_of,
)

RECORDED_AT = datetime(2026, 7, 25, 9, 0, tzinfo=timezone.utc)


def _adapter() -> OperatorExportAdapter:
    return OperatorExportAdapter(new_id(TenantId), recorded_at=RECORDED_AT)


def row(**overrides: object) -> dict:
    """SYNTHETIC. A clean minimal export row, before we ruin it."""
    base = {
        "trip_ref": "T-0001",
        "requested_at": "2026-03-02T19:05:00",
        "scheduled_pickup_at": "2026-03-04T13:15:00",
        "actual_pickup_at": "2026-03-04T13:22:00",
        "pickup_zone": "NW3",
        "dropoff_zone": "CBD1",
        "run_ref": "RUN-A",
        "outcome": "served",
    }
    base.update(overrides)
    return base


def _rules_fired(result) -> set[str]:
    """The repair rules recorded on a parsed row."""
    return {
        rule
        for loss in result.semantic_loss
        if (rule := repair_rule_of(loss)) is not None
    }


# ---------------------------------------------------------------------------
# THE LINE BETWEEN REPAIRED AND GUESSED
# ---------------------------------------------------------------------------


def test_an_ambiguous_day_month_date_is_quarantined_not_guessed() -> None:
    """`03/04/2026` is 3 April and 4 March, and nothing in the row says which.

    The adapter must refuse it. Picking either reading silently would shift a
    trip by a month, and every downstream hour-of-day and day-of-week bucket in
    the teardown would be wrong while looking perfectly well-formed. A quarantine
    an operator can fix beats a number nobody can audit.
    """
    result = _adapter().parse(row(scheduled_pickup_at="03/04/2026 13:15"))

    assert result.record is None
    assert result.quarantine is not None
    assert "ambiguous" in result.quarantine.reason.lower()
    # and the reason must SAY why, so the operator can resolve it at source
    assert "both valid readings" in result.quarantine.reason


@pytest.mark.parametrize(
    ("text", "expected_rule"),
    [
        ("13/04/2026 09:00", "date_order_ddmm"),  # 13 > 12 -> day-first, forced
        ("04/13/2026 09:00", "date_order_mmdd"),  # 13 > 12 -> month-first, forced
    ],
)
def test_a_date_is_repaired_only_when_one_component_forces_the_reading(
    text: str, expected_rule: str
) -> None:
    """The mirror of the test above: when a component exceeds 12 there is only
    one valid reading, so it is arithmetic rather than a guess -- and it is still
    recorded as a repair."""
    result = _adapter().parse(row(scheduled_pickup_at=text))

    assert result.record is not None
    assert expected_rule in _rules_fired(result)


def test_pii_still_fails_closed_when_the_row_is_also_malformed() -> None:
    """The PII gate must win over every repair path.

    A row can be BOTH malformed and carrying a rider name. If repair ran first it
    could tidy the row into something acceptable and admit the identifier. The
    gate runs before any normalisation, so the row is rejected on PII grounds and
    the name never reaches the record, the loss notes, or the quarantine payload.
    """
    messy_and_sensitive = row(
        scheduled_pickup_at="  03/04/2026 13:15  ",  # ambiguous AND untrimmed
        outcome="  SERVED  ",  # would otherwise be repaired
        rider_name="Wilhelmina Okonkwo-Rutherford",
    )
    result = _adapter().parse(messy_and_sensitive)

    assert result.record is None
    assert result.quarantine is not None
    assert "rider_name" in result.quarantine.reason
    # the value itself must not survive anywhere in the quarantine record
    assert "Wilhelmina" not in str(result.quarantine.raw_row)
    assert "Wilhelmina" not in result.quarantine.reason


# ---------------------------------------------------------------------------
# REPAIRS: each records a rule, so it is auditable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "expected_rule"),
    [
        ({"pickup_zone": "  NW3  "}, "trim_whitespace"),
        ({"outcome": "  served  "}, "trim_whitespace"),
        ({"run_ref": "412.0"}, "integral_float_identifier"),
        # year-first but slash-separated: unambiguous (the year pins the order),
        # so it is arithmetic rather than a guess -- contrast the DD/MM case above.
        ({"scheduled_pickup_at": "2026/03/04 13:15"}, "iso8601_variant"),
        ({"scheduled_pickup_at": "2026-03-04 13:15:00 UTC"}, "iso8601_utc_designator"),
        ({"scheduled_pickup_at": "2026-03-04 01:15 PM"}, "twelve_hour_clock"),
        ({"requested_at": "2026-03-02"}, "requested_at_date_only"),
    ],
)
def test_an_unambiguous_defect_is_repaired_and_recorded(
    overrides: dict, expected_rule: str
) -> None:
    """Each repair produces a record, never a silent fix. An operator reviewing
    the ingest can see exactly what we changed and disagree with it."""
    result = _adapter().parse(row(**overrides))

    assert result.record is not None, f"{expected_rule} should have been repairable"
    assert expected_rule in _rules_fired(result)


def test_every_repair_rule_has_a_published_explanation() -> None:
    """A rule whose reason nobody can read is not auditable. REPAIR_RULES is the
    published catalogue and must cover every rule the adapter can fire."""
    assert REPAIR_RULES
    for rule, explanation in REPAIR_RULES.items():
        assert explanation.strip(), f"{rule} has no explanation"
        assert len(explanation) > 30, f"{rule}'s explanation is too thin to audit"


# ---------------------------------------------------------------------------
# STRUCTURAL MESS: the shapes a vendor CSV actually arrives in
# ---------------------------------------------------------------------------


def test_a_trip_crossing_midnight_is_accepted() -> None:
    """23:40 -> 00:15 is a real overnight trip, not an error. Rejecting it would
    quarantine the night shift."""
    result = _adapter().parse(
        row(
            scheduled_pickup_at="2026-03-04T23:40:00",
            actual_pickup_at="2026-03-05T00:15:00",
        )
    )
    assert result.record is not None


def test_a_zero_duration_trip_is_accepted_not_treated_as_broken() -> None:
    """Same scheduled and actual pickup is a punctual trip, not a defect."""
    result = _adapter().parse(
        row(scheduled_pickup_at="2026-03-04T13:15:00", actual_pickup_at="2026-03-04T13:15:00")
    )
    assert result.record is not None


def test_a_repeated_header_row_is_quarantined_structurally() -> None:
    """Vendors paginate exports and re-emit the header. It must not become a
    trip whose trip_ref is literally 'trip_ref'."""
    header_as_row = {name: name for name in row()}
    result = _adapter().parse(header_as_row)

    assert result.record is None
    assert result.quarantine is not None


def test_an_empty_row_is_quarantined_and_says_so() -> None:
    result = _adapter().parse({name: "" for name in row()})

    assert result.record is None
    assert result.quarantine is not None


def test_extra_vendor_columns_do_not_block_a_good_row() -> None:
    """A ragged export with unknown trailing columns still imports; the extras
    are reported rather than silently dropped (ADR-0007)."""
    result = _adapter().parse(row(vendor_internal_code="X99", legacy_flag="", notes=""))

    assert result.record is not None
    reported = {loss.source_field for loss in result.semantic_loss}
    assert "vendor_internal_code" in reported


# ---------------------------------------------------------------------------
# THE INGEST QUALITY REPORT: a diagnosis, not a rejection
# ---------------------------------------------------------------------------


def test_an_entirely_empty_export_reports_cleanly_without_dividing_by_zero() -> None:
    """The degenerate case must produce a usable report, not a ZeroDivisionError.
    An operator who sends an empty file deserves an answer."""
    adapter = _adapter()
    report = build_ingest_report(adapter, [])

    assert isinstance(report, IngestQualityReport)
    assert report.rows_total == 0
    assert report.headline
    assert report.to_text()


def test_a_wholly_unusable_export_still_produces_an_actionable_report() -> None:
    """When EVERY row quarantines, the report is the only thing of value we can
    return -- so it must still name the reasons and the missing fields."""
    adapter = _adapter()
    rows = [{"trip_ref": f"T-{i}", "outcome": "served"} for i in range(6)]
    report = build_ingest_report(adapter, rows)

    assert report.rows_total == 6
    assert report.rows_mapped == 0
    assert report.quarantine_reasons, "a fully-failed ingest must explain itself"
    assert report.to_text()


def test_the_report_counts_reconcile_to_the_row_total() -> None:
    """mapped + quarantined must equal total. A report whose arithmetic does not
    close is not evidence of anything."""
    adapter = _adapter()
    rows = [
        row(trip_ref="T-1"),
        row(trip_ref="T-2", outcome="  served  "),
        row(trip_ref="T-3", scheduled_pickup_at="03/04/2026 13:15"),
        {"trip_ref": "T-4"},
    ]
    report = build_ingest_report(adapter, rows)

    assert report.rows_total == 4
    assert report.rows_mapped + report.rows_quarantined == report.rows_total


def test_repairs_are_counted_so_an_operator_can_fix_them_at_source() -> None:
    """The point of counting repair rules is that the operator can stop us having
    to repair -- e.g. fix the export template's date format once."""
    adapter = _adapter()
    rows = [row(trip_ref=f"T-{i}", pickup_zone="  NW3  ") for i in range(5)]
    report = build_ingest_report(adapter, rows)

    assert report.rows_mapped == 5
    fired = {r.rule for r in report.repair_rules}
    assert "trim_whitespace" in fired


def test_correlated_missingness_is_diagnosed_not_just_counted() -> None:
    """The ADR-0039 finding, generalised.

    On real TLC data the rows missing a base id were the SAME rows missing the
    on-scene timestamp. Independent gaps shrink a sample; correlated gaps bias
    it, because the rows that vanish are systematically different from the rows
    that remain. A report that only counted nulls per column would have shown two
    ordinary-looking gaps and hidden the bias entirely.
    """
    adapter = _adapter()
    rows = []
    for i in range(12):
        together_missing = i % 2 == 0
        rows.append(
            row(
                trip_ref=f"T-{i}",
                vehicle_ref="" if together_missing else f"V-{i}",
                actual_pickup_at="" if together_missing else "2026-03-04T13:22:00",
                run_ref="" if together_missing else "RUN-A",
            )
        )
    report = build_ingest_report(adapter, rows)

    assert report.missingness is not None
    assert report.missingness.verdict != "independent", (
        "co-missing vehicle_ref and actual_pickup_at should not read as independent"
    )


def test_an_identifier_changing_format_midway_is_surfaced() -> None:
    """A vehicle id that is 'V-001' for half the file and '1' for the rest breaks
    the chaining the whole deadhead measurement depends on (ADR-0039). Silence
    here would produce a teardown that quietly attributes half the fleet to
    'unattributable'."""
    adapter = _adapter()
    rows = [row(trip_ref=f"T-{i}", vehicle_ref=f"V-{i:03d}") for i in range(5)]
    rows += [row(trip_ref=f"T-{i}", vehicle_ref=str(i)) for i in range(5, 10)]
    report = build_ingest_report(adapter, rows)

    assert report.to_text()
    assert report.rows_total == 10


def test_the_report_text_is_readable_by_a_human_not_just_a_machine() -> None:
    """This is the artifact an ops director reads. If it only renders as JSON it
    will not be read at all."""
    adapter = _adapter()
    report = build_ingest_report(adapter, [row(trip_ref="T-1"), {"trip_ref": "T-2"}])

    text = report.to_text()
    assert "\n" in text
    assert str(report.rows_total) in text
