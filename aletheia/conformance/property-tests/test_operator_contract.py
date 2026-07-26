"""Conformance for the operator data contract (MX-TALOS-OPERATOR-CONTRACT-016).

WHAT IS ACTUALLY BEING PROTECTED HERE
This contract is a document we intend to put in front of a transit agency. That
gives it a failure mode ordinary code does not have: it can be **wrong in a way
that only the operator can see**. A field list that promises eight columns over a
table of eleven, a document whose required set disagrees with the adapter that
enforces it, a validator that reports "decision replay: supported" for a column
of identical timestamps -- each of those is a credibility loss that no amount of
later engineering repairs, because the conversation has already happened.

So the tests fall into four groups, and the second and third are the ones that
earn their place:

1. **Structure.** Every field states what it unlocks and what is lost, and gates
   at least one capability. A field that gates nothing is a field we asked for
   and cannot justify, which is the specific thing the packet forbids.
2. **Agreement with the code that enforces it.** The contract's required column
   set is asserted equal to `themis.connect.operator_export.REQUIRED_COLUMNS`.
   The document and the adapter cannot promise different things, in either
   direction: a contract that asks for less than the adapter enforces produces a
   rejected export from a compliant operator, and one that asks for more spends
   goodwill on data nothing consumes.
3. **The validator's degeneracy checks.** A presence test on the knowledge
   timestamp is nearly worthless: the failure that matters is a column that is
   fully populated and meaningless. Every one of those checks has a test whose
   fixture WOULD PASS a presence check.
4. **Ordering.** The identity gate runs before everything else, proven the only
   way it can be -- with a row that is both perfect and carries a rider name,
   and a row that is both broken and carries one.

Every fixture is SYNTHETIC and labelled. No operator data exists in this
repository and none was used here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talos.contracts import operator_contract as contract
from talos.contracts.operator_contract import Requirement, Shape
from talos.contracts.validate_operator_export import (
    ContractAssessment,
    Severity,
    Verdict,
    assess,
    assess_csv,
)

_REPO = Path(__file__).resolve().parents[3]
_JSON = _REPO / "talos" / "contracts" / "jsonschema" / "operator-data-contract-v0.1.json"
_MARKDOWN = _REPO / "talos" / "contracts" / "OPERATOR_DATA_CONTRACT.md"

_BASE = datetime(2026, 3, 2, 8, 0, tzinfo=timezone.utc)

# Six required declarations, all answered. Used as the "everything the operator
# could answer by email has been answered" baseline so a test about the DATA is
# not silently passing or failing on an unanswered question.
_ANSWERED: dict[str, object] = {
    "export_generated_at": "2026-05-04T00:00:00+00:00",
    "coverage_window": "2026-03-02 to 2026-04-27, complete, no trip types excluded",
    "timestamp_convention": "UTC",
    "fleet_shape": "no",
    "source_systems": "SYNTHETIC scheduling system (fictional)",
    "alternatives_logged": "no",
    "denial_code_list": "SYNTHETIC: D1 = no accessible vehicle free; D9 = other",
}


def _rows(
    *,
    count: int = 60,
    known_at: str | None = None,
    updated_at: str | None = None,
    served_only: bool = False,
    include_dropoff: bool = False,
    extra: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    """A SYNTHETIC operator export. No real trip, rider, vehicle or agency is
    represented; the shape is taken from the published intake document."""
    out: list[dict[str, object]] = []
    for index in range(count):
        pickup = _BASE + timedelta(days=index)
        booked = pickup - timedelta(days=2)
        row: dict[str, object] = {
            "trip_ref": f"SYNTH-BK-{index:04d}",
            "requested_at": booked.isoformat(),
            "scheduled_pickup_at": pickup.isoformat(),
            "actual_pickup_at": (pickup + timedelta(minutes=7)).isoformat(),
            "pickup_zone": "ZONE-NW-3",
            "dropoff_zone": "ZONE-CBD-1",
            "run_ref": f"SYNTH-RUN-{index % 4}",
            "outcome": "served" if (served_only or index % 5) else "denied",
        }
        if include_dropoff:
            row["actual_dropoff_at"] = (pickup + timedelta(minutes=32)).isoformat()
        if known_at == "genuine":
            row["record_created_known_at"] = booked.isoformat()
        elif known_at == "constant":
            row["record_created_known_at"] = "2026-05-04T00:00:00+00:00"
        elif known_at == "before_event":
            row["record_created_known_at"] = (booked - timedelta(days=30)).isoformat()
        elif known_at == "partial":
            row["record_created_known_at"] = booked.isoformat() if index % 2 else ""
        if updated_at == "revised":
            row["record_updated_known_at"] = (booked + timedelta(hours=6)).isoformat()
        elif updated_at == "never":
            row["record_updated_known_at"] = booked.isoformat()
        if extra:
            row.update(extra)
        out.append(row)
    return out


# ===========================================================================
# 1. Structure: every field justifies itself
# ===========================================================================

def test_every_field_states_what_it_unlocks_and_what_is_lost() -> None:
    """The packet's rule, made checkable: 'if you cannot state what it unlocks,
    it does not belong in the contract'. A field whose `lost_without_it` is empty
    is a field we are asking for out of optimism."""
    for spec in contract.FIELDS:
        assert spec.unlocks.strip(), f"{spec.name} does not say what it unlocks"
        assert spec.lost_without_it.strip(), f"{spec.name} does not say what is lost"
        assert spec.operator_question.strip().endswith("?") or "?" in spec.operator_question, (
            f"{spec.name}'s operator_question is not a question, so an IT lead "
            "cannot answer it yes / no / we-do-not-record-that"
        )


def test_no_field_gates_nothing() -> None:
    """The load-bearing structural check. Every field must move at least one
    capability from 'we cannot answer that' to 'we can'. An ungated field is
    precisely the thing that makes an operator conclude we are asking for
    everything -- and an operator asked for everything gives nothing."""
    ungated = [spec.name for spec in contract.FIELDS if not contract.capabilities_needing(spec.name)]
    assert ungated == [], (
        f"these fields gate no capability and cannot be justified: {ungated}. "
        "Either wire them into a capability or delete them from the contract."
    )


def test_every_capability_references_real_fields() -> None:
    """The reverse direction: a capability requiring a field that does not exist
    would report NOT_SUPPORTED forever with no way for an operator to fix it."""
    for capability in contract.CAPABILITIES:
        for name in capability.requires + capability.requires_any + capability.sharpened_by:
            assert name in contract.FIELDS_BY_NAME, (
                f"capability {capability.id} references unknown field {name!r}"
            )


def test_the_required_and_helpful_split_is_populated_on_both_sides() -> None:
    """Guards every requirement-level assertion below. If `fields_with` silently
    returned nothing, tests asserting 'no REQUIRED field does X' would pass over
    an empty set."""
    assert len(contract.fields_with(Requirement.REQUIRED)) >= 8
    assert len(contract.fields_with(Requirement.REQUIRED_FOR_REPLAY)) >= 2
    assert len(contract.fields_with(Requirement.HELPFUL)) >= 5


def test_the_knowledge_timestamp_is_not_marked_plain_required() -> None:
    """The judgement call this contract rests on, pinned so it cannot be
    'tidied' later.

    Marking `record_created_known_at` REQUIRED would make the contract
    unanswerable: many systems do not record one, and an operator whose honest
    answer fails the contract outright sends nothing. Marking it merely HELPFUL
    would understate it -- its absence withdraws a whole class of claim. The
    third level exists for exactly this field and says so."""
    spec = contract.FIELDS_BY_NAME["record_created_known_at"]
    assert spec.requirement is Requirement.REQUIRED_FOR_REPLAY
    assert "cannot be retrofitted" in (spec.note or "").lower()
    meaning = contract._REQUIREMENT_MEANING[Requirement.REQUIRED_FOR_REPLAY]
    assert "WITHDRAWN" in meaning and "not approximated" in meaning


def test_the_refusals_and_the_not_requested_list_are_distinct_and_both_present() -> None:
    """Two different statements that a reader must not confuse: 'we did not ask
    for it' and 'we will not accept it'. A contract with only the second reads as
    'send everything not on this list'."""
    assert len(contract.REFUSALS) >= 8
    assert len(contract.NOT_REQUESTED) >= 5
    for item in contract.NOT_REQUESTED:
        assert item.what_we_give_up.strip(), (
            f"{item.name} is declined without saying what that costs us -- an "
            "omission with no stated cost reads as a field that was never needed"
        )


def test_driver_licensing_identifiers_are_refused() -> None:
    """ADR-0057: a hack licence is a person's licence, and the 2013 NYC TLC
    release was de-anonymised through exactly these columns."""
    refused = {name for item in contract.REFUSALS for name in item.example_columns}
    for column in ("hack_license", "medallion", "license_plate", "vin", "driver_license"):
        assert column in refused, f"{column} is not in the refusals table"


def test_the_pseudonymisation_statement_names_its_own_weakness() -> None:
    """A privacy statement that only lists strengths is marketing. This one has
    to say that the hash is unsalted and that the automated checks are a
    backstop, because both are true and an operator's counsel will find out."""
    # Whitespace-collapsed, because the source is hand-wrapped prose and a test
    # that only passes at one line width is asserting the formatting, not the
    # claim.
    statement = " ".join(contract.PSEUDONYMISATION_STATEMENT.lower().split())
    assert "unsalted" in statement
    assert "pseudonym, not anonymisation" in statement
    assert "backstop, not a guarantee" in statement
    assert "pseudonymous person identifier" in statement
    assert "fleet-shape question is asked directly" in statement


def test_nothing_in_the_contract_claims_a_saving_or_a_validation() -> None:
    """Zero customers, zero pilots, nothing Validated. The contract is outward-
    facing copy and gets the same discipline as the outreach material."""
    text = (_MARKDOWN.read_text(encoding="utf-8") + _JSON.read_text(encoding="utf-8")).lower()
    for banned in ("savings of", "roi", "guaranteed", "proven results", "we have validated"):
        assert banned not in text, f"the contract claims {banned!r}"
    assert "no operator customers" in text
    assert "nothing is" in text and "validated" in text


# ===========================================================================
# 2. Agreement with the adapter that enforces it
# ===========================================================================

def test_the_required_columns_match_the_adapter_that_enforces_them() -> None:
    """The contract and `themis/connect/operator_export.py` must not promise
    different things.

    Drift in EITHER direction is a defect. If the contract asks for less than the
    adapter enforces, a compliant operator's export is rejected on arrival and we
    have wasted their extract. If it asks for more, we have spent goodwill on
    columns nothing consumes.
    """
    from themis.connect.operator_export import (
        REQUIRED_COLUMNS,
        VEHICLE_OR_RUN_COLUMNS,
    )

    expected = set(REQUIRED_COLUMNS) | set(VEHICLE_OR_RUN_COLUMNS) | {"actual_pickup_at"}
    assert set(contract.required_columns()) == expected, (
        "the contract's required column set has drifted from the adapter's. "
        "Change themis/connect/operator_export.py and talos/contracts/"
        "operator_contract.py together, or an operator gets two different answers."
    )


def test_the_contract_outcome_vocabulary_matches_the_adapter() -> None:
    from themis.connect.operator_export import OUTCOME_VALUES

    declared = contract.FIELDS_BY_NAME["outcome"].value_type
    for value in OUTCOME_VALUES:
        assert value in declared, f"the adapter accepts {value!r} and the contract does not list it"


def test_the_contract_points_at_the_document_and_adapter_that_exist() -> None:
    """A contract citing a path that has been renamed is worse than one citing
    none: the reader concludes the rest is stale too."""
    assert (_REPO / contract.INTAKE_DOCUMENT).exists()
    assert (_REPO / contract.INTAKE_ADAPTER).exists()


# ===========================================================================
# 3. The generated artifacts, and the drift gate
# ===========================================================================

def test_the_generated_artifacts_are_real_documents() -> None:
    """Guards the drift test below: a missing or empty file would make an
    equality assertion pass over nothing on both sides."""
    spec = json.loads(_JSON.read_text(encoding="utf-8"))
    assert spec["contract_version"] == contract.CONTRACT_VERSION
    assert len(spec["fields"]) == len(contract.FIELDS)
    assert len(spec["capabilities"]) == len(contract.CAPABILITIES)
    assert len(_MARKDOWN.read_text(encoding="utf-8")) > 10_000


def test_the_committed_artifacts_match_a_fresh_render() -> None:
    """The local half of the CI drift gate. This file WRITES NOTHING -- a test
    that regenerated the artifact would repair the drift it exists to report and
    pass for the wrong reason.

    If this fails, run:  py -3 talos/contracts/generate.py
    """
    assert json.loads(_JSON.read_text(encoding="utf-8")) == contract.as_dict(), (
        "talos/contracts/jsonschema/operator-data-contract-v0.1.json is stale"
    )
    assert _MARKDOWN.read_text(encoding="utf-8") == contract.as_markdown(), (
        "talos/contracts/OPERATOR_DATA_CONTRACT.md is stale"
    )


def test_rendering_is_deterministic() -> None:
    """The drift gate compares BYTES after regenerating. A dict ordered by a set
    iteration, or a clock read anywhere in the renderer, turns that gate into a
    coin flip that fails on someone else's machine."""
    assert contract.as_markdown() == contract.as_markdown()
    assert json.dumps(contract.as_dict(), sort_keys=True) == json.dumps(
        contract.as_dict(), sort_keys=True
    )


def test_the_headline_numbers_agree_with_the_field_list_today() -> None:
    """Necessary and, on its own, NOT sufficient -- see the test below."""
    ask = contract.the_ask()
    assert f"{contract._spell(len(contract.required_columns()))} columns" in ask
    assert f"{contract._spell(len(contract.required_declarations()))} questions" in ask
    rendered = contract.as_markdown()
    assert f"## 2. The {contract._spell(len(contract.required_declarations()))} questions" in rendered


def test_the_headline_numbers_are_derived_rather_than_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cheapest way to lose an operator's confidence is a document that opens
    with "eight columns" over a table of eleven, and it happens by editing the
    list and not the sentence.

    The test above cannot catch that: a hardcoded "six" and a computed six are
    the same string today, so it passes over a literal. Written that way it
    stayed green when the count was replaced with a typed constant. So this one
    PERTURBS the field list and asserts the sentence moves with it -- the only
    form of the assertion that distinguishes derived from typed.
    """
    probe = contract.FieldSpec(
        name="synthetic_probe_declaration",
        shape=Shape.DECLARATION,
        value_type="yes/no",
        requirement=Requirement.REQUIRED,
        summary="SYNTHETIC probe, not part of the contract",
        unlocks="nothing -- this exists only inside this test",
        lost_without_it="nothing",
        operator_question="probe?",
    )
    before = contract.the_ask()
    monkeypatch.setattr(contract, "FIELDS", contract.FIELDS + (probe,))
    after = contract.the_ask()

    assert before != after, "the ask paragraph did not move when the field list did"
    assert f"{contract._spell(len(contract.required_declarations()) - 1)} questions" in before
    assert f"{contract._spell(len(contract.required_declarations()))} questions" in after
    assert f"## 2. The {contract._spell(len(contract.required_declarations()))} questions" in (
        contract.as_markdown()
    )


def test_the_companion_document_carries_every_section_a_reader_needs() -> None:
    rendered = contract.as_markdown()
    for heading in (
        "## 0. Read this first",
        "## 1. The ask",
        "## 3. The two timestamps",
        "## 6. What we are NOT asking for",
        "## 7. Pseudonymisation and minimisation",
        "## 8. The minimum viable ask",
        "## 10. Limitations",
    ):
        assert heading in rendered, f"the companion document lost its {heading!r} section"
    collapsed = " ".join(rendered.split())
    assert "Eight to twelve weeks, from one agency" in collapsed, (
        "the minimum viable ask must be stated in the companion document in words "
        "an operations director reads, not only as a field in the JSON"
    )


def test_the_minimum_viable_ask_is_one_agency_and_eight_to_twelve_weeks() -> None:
    ask = contract.as_dict()["minimum_viable_ask"]
    assert ask["weeks"] == [8, 12]
    assert ask["agencies"] == 1
    assert ask["must_include_non_served_outcomes"] is True
    assert "five years" in ask["statement"]


# ===========================================================================
# 4. The validator: the sentence the packet asks for
# ===========================================================================

def test_a_complete_export_without_knowledge_time_says_exactly_what_it_cannot_do() -> None:
    """THE headline case. This is the sentence the whole packet exists to make
    possible, and it must be produced by a sample that is otherwise perfect --
    so the reason named is the knowledge timestamp and nothing else."""
    result = assess(_rows(), declarations=_ANSWERED)

    assert result.verdict_for("outcome_analysis") is Verdict.SUPPORTED
    assert result.verdict_for("information_set_replay") is Verdict.NOT_SUPPORTED
    assert result.verdict_for("counterfactual_comparison") is Verdict.NOT_SUPPORTED

    headline = result.headline()
    assert "supports outcome analysis" in headline
    assert "cannot support information-set replay" in headline
    assert "no source-side knowledge timestamp is present" in headline

    finding = next(item for item in result.findings if item.code == "NO_KNOWLEDGE_TIMESTAMP")
    assert finding.severity is Severity.CRITICAL
    assert "in our favour" in finding.message, (
        "the finding must name the DIRECTION of the bias. 'Replay would be less "
        "accurate' is a technical caveat; 'it biases the comparison in our "
        "favour' is the reason we refuse to publish it, and only the second one "
        "makes the operator's answer matter to them."
    )
    assert "cannot be retrofitted" in finding.message


def test_a_knowledge_timestamp_that_is_the_same_on_every_row_is_not_a_knowledge_timestamp() -> None:
    """The check that justifies the validator existing.

    This fixture would pass any presence test: the column is there, fully
    populated, correctly typed. It is a backfill stamped at load, every
    reconstruction over it shares one boundary, and reporting 'decision replay:
    supported' for it would be worse than reporting nothing -- the analysis built
    on it looks rigorous."""
    result = assess(_rows(known_at="constant"), declarations=_ANSWERED)

    assert result.verdict_for("information_set_replay") is Verdict.NOT_SUPPORTED
    assert result.has("KNOWN_AT_CONSTANT")
    assert result.has("BACKFILL_SIGNATURE")
    assert result.has("KNOWN_AT_EQUALS_EXPORT_TIME")
    assert "identical on every row" in result.headline()

    backfill = next(item for item in result.findings if item.code == "BACKFILL_SIGNATURE")
    assert "outcome analysis but not decision replay" in backfill.message


def test_a_genuine_knowledge_timestamp_turns_replay_on() -> None:
    """The positive control. Without it every 'not supported' assertion above
    could be vacuous -- a validator that reported NOT_SUPPORTED unconditionally
    would pass all of them."""
    result = assess(_rows(known_at="genuine"), declarations=_ANSWERED)
    assert result.verdict_for("information_set_replay") is Verdict.SUPPORTED
    assert not result.has("KNOWN_AT_CONSTANT")
    assert not result.has("BACKFILL_SIGNATURE")


def test_a_knowledge_timestamp_before_the_booking_it_describes_is_refused() -> None:
    """A record cannot become visible before the event that created it. The usual
    cause is two columns in different time zones, which is exactly the defect
    that is invisible in the output."""
    result = assess(_rows(known_at="before_event"), declarations=_ANSWERED)
    assert result.has("KNOWN_AT_PRECEDES_EVENT")
    assert result.verdict_for("information_set_replay") is Verdict.NOT_SUPPORTED


def test_a_partially_populated_knowledge_timestamp_is_limited_not_withdrawn() -> None:
    """Replay over a subset is possible and the subset is not the board. The
    honest verdict is 'with limits', with the count named -- not a pass, and not
    a refusal."""
    result = assess(_rows(known_at="partial"), declarations=_ANSWERED)
    assert result.verdict_for("information_set_replay") is Verdict.SUPPORTED_WITH_LIMITS
    assert result.has("KNOWN_AT_PARTIAL")


def test_arrivals_replay_and_state_replay_are_separate_verdicts() -> None:
    """A created timestamp alone rebuilds which bookings EXISTED at an instant.
    It does not rebuild the board, because the cancellations and reassignments
    that changed it during the day are only visible in their final state -- and
    that is most of what a dispatcher reacts to. Collapsing the two would
    overstate what a created/modified pair buys."""
    arrivals_only = assess(_rows(known_at="genuine"), declarations=_ANSWERED)
    assert arrivals_only.verdict_for("information_set_replay") is Verdict.SUPPORTED
    assert arrivals_only.verdict_for("intraday_state_replay") is Verdict.NOT_SUPPORTED
    assert arrivals_only.has("NO_REVISION_HISTORY")

    with_revisions = assess(
        _rows(known_at="genuine", updated_at="revised"), declarations=_ANSWERED
    )
    assert with_revisions.verdict_for("intraday_state_replay") is Verdict.SUPPORTED


def test_a_last_modified_column_that_never_changes_is_reported_as_a_question() -> None:
    """No row revised in eight weeks of paratransit means either the column is
    not maintained or trips are never re-timed. Which of those is true is the
    operator's to say, so the validator asks rather than deciding."""
    result = assess(_rows(known_at="genuine", updated_at="never"), declarations=_ANSWERED)
    assert result.has("NO_ROW_SHOWS_A_REVISION")
    assert result.verdict_for("intraday_state_replay") is Verdict.NOT_SUPPORTED


def test_an_unlogged_alternatives_answer_withdraws_the_counterfactual() -> None:
    """ADR-0072's third question. `alternatives=()` reads as 'nothing else was
    considered' when it means 'unknown' -- a fabricated finding, and a flattering
    one, because it makes every decision look forced."""
    declarations = dict(_ANSWERED, alternatives_logged="no", run_roster="sent separately")
    result = assess(_rows(known_at="genuine"), declarations=declarations)
    assert result.verdict_for("counterfactual_comparison") is Verdict.NOT_SUPPORTED
    reasons = " ".join(
        item.reasons[0] if item.reasons else ""
        for item in result.capabilities
        if item.capability_id == "counterfactual_comparison"
    )
    joined = " ".join(
        reason
        for item in result.capabilities
        if item.capability_id == "counterfactual_comparison"
        for reason in item.reasons
    )
    assert "UNKNOWN rather than" in joined and "empty" in joined
    assert reasons or joined


def test_a_counterfactual_needs_to_know_which_vehicles_existed() -> None:
    """Without a run roster a counterfactual can only re-sequence trips inside
    the runs that happened. It cannot say a different vehicle should have taken a
    trip, because it does not know which vehicles existed."""
    result = assess(_rows(known_at="genuine"), declarations=dict(_ANSWERED, alternatives_logged="yes"))
    assert result.verdict_for("counterfactual_comparison") is Verdict.NOT_SUPPORTED
    joined = " ".join(
        reason
        for item in result.capabilities
        if item.capability_id == "counterfactual_comparison"
        for reason in item.reasons
    )
    assert "run roster" in joined

    supplied = assess(
        _rows(known_at="genuine"),
        declarations=dict(_ANSWERED, alternatives_logged="yes", run_roster="attached"),
    )
    assert supplied.verdict_for("counterfactual_comparison") is Verdict.SUPPORTED


def test_an_export_of_served_trips_only_is_a_defect_not_a_perfect_record() -> None:
    """A filtered extract makes unmet demand structurally invisible, and a
    forecast trained on it learns the shape of what the operator was able to
    serve rather than the shape of what was asked for."""
    result = assess(_rows(served_only=True), declarations=_ANSWERED)
    assert result.has("EXPORT_CONTAINS_ONLY_SERVED_TRIPS")
    assert result.verdict_for("unmet_demand_forecasting") is Verdict.NOT_SUPPORTED


def test_deadhead_without_a_dropoff_time_is_a_bound_not_a_measurement() -> None:
    bounded = assess(_rows(), declarations=_ANSWERED)
    assert bounded.verdict_for("deadhead_measurement") is Verdict.SUPPORTED_WITH_LIMITS

    measured = assess(_rows(include_dropoff=True), declarations=_ANSWERED)
    assert measured.verdict_for("deadhead_measurement") is Verdict.SUPPORTED


# ===========================================================================
# 5. The identity gate, and its ordering
# ===========================================================================

def test_an_identity_column_refuses_the_export_before_anything_else_is_assessed() -> None:
    """The ordering is the property, not the detection.

    This fixture is otherwise PERFECT -- every required column, every declaration
    answered, a genuine knowledge timestamp, revisions, denials. If the identity
    check ran anywhere but first, this file would be reported as supporting
    everything, with the rider name as a footnote."""
    rows = _rows(known_at="genuine", updated_at="revised", extra={"rider_name": "SYNTHETIC Jane Roe"})
    result = assess(rows, declarations=_ANSWERED)

    assert result.refused is True
    assert result.has("IDENTITY_COLUMN_PRESENT")
    assert all(item.verdict is Verdict.NOT_ASSESSED for item in result.capabilities), (
        "capabilities must be NOT_ASSESSED, not NOT_SUPPORTED -- we did not look, "
        "and reporting a verdict on a file we declined to read is a claim about "
        "data we never examined"
    )


def test_the_identity_gate_fires_on_a_column_that_is_blank_in_the_sample() -> None:
    """An all-blank identity column in a two-hundred-row sample is usually a
    populated one in the full extract. Refusing on the COLUMN rather than the
    value is what makes a sample a useful check at all."""
    result = assess(_rows(count=5, extra={"rider_name": ""}), declarations=_ANSWERED)
    assert result.refused is True
    assert result.has("IDENTITY_COLUMN_PRESENT")


def test_the_identity_gate_survives_laundering_through_the_column_map() -> None:
    """A column_map entry pointing `ClientName` at `trip_ref` must not get it
    past the gate: the check reads the operator's OWN header, not the target."""
    rows = [{"BookingNo": "SYNTH-1", "ClientName": "SYNTHETIC Jane Roe"}]
    result = assess(rows, column_map={"BookingNo": "trip_ref", "ClientName": "trip_ref"})
    assert result.refused is True


def test_a_refusal_report_never_reproduces_the_offending_value() -> None:
    """ADR-0057 closed a live defect where a rejected identifier was echoed into
    the loss record. A report that quotes the rider's name is a second copy of
    the thing being refused."""
    rows = _rows(count=3, extra={"rider_name": "SYNTHETIC Jane Roe", "phone": "+1 555 0100"})
    result = assess(rows, declarations=_ANSWERED)
    rendered = result.report() + json.dumps(result.as_dict())
    assert "Jane Roe" not in rendered
    assert "555 0100" not in rendered
    assert "rider_name" in rendered, "the COLUMN must be named so the operator can strip it"


def test_an_email_in_a_renamed_column_is_still_caught() -> None:
    result = assess(_rows(count=3, extra={"contact_1": "someone@example.org"}), declarations=_ANSWERED)
    assert result.refused is True
    assert result.has("EMAIL_IN_VALUES")
    assert "someone@example.org" not in result.report()


def test_a_zone_that_is_a_street_address_is_refused() -> None:
    rows = _rows(count=3)
    rows[1]["pickup_zone"] = "48 Willow Bank Road"
    result = assess(rows, declarations=_ANSWERED)
    assert result.refused is True
    assert result.has("ZONE_IS_AN_ADDRESS")


def test_a_vehicle_reference_in_an_owner_operator_fleet_is_a_person_id() -> None:
    """ADR-0057's durable half: in a fleet where vehicle and driver are 1:1, a
    genuine vehicle id is a pseudonymous person id. The question is fleet shape,
    not column name -- so the answer comes from the operator and the same column
    is accepted or refused depending on it."""
    rows = _rows(count=10, extra={"vehicle_ref": "SYNTH-UNIT-1"})

    owner_operator = assess(rows, declarations=dict(_ANSWERED, fleet_shape="yes, 12 sole contractors"))
    assert owner_operator.has("VEHICLE_REF_IS_A_PERSON_ID")

    agency_fleet = assess(rows, declarations=dict(_ANSWERED, fleet_shape="no"))
    assert not agency_fleet.has("VEHICLE_REF_IS_A_PERSON_ID"), (
        "the identical column must be accepted when the fleet shape says it is a "
        "vehicle -- otherwise the check is about the column name after all"
    )


@pytest.mark.parametrize(
    "answer, expect_person_id",
    [
        ("yes", True),
        ("yes, 12 sole contractors", True),
        ("Yes - about a third are owner operators", True),
        ("no", False),
        ("No - every vehicle is agency owned and driven by several operators", False),
    ],
)
def test_a_free_text_fleet_shape_answer_is_read_the_way_an_operator_writes_it(
    answer: str, expect_person_id: bool
) -> None:
    """An operator answers a privacy question in a sentence, not with a keyword.

    The first version of this check matched the answer against an exact set, so
    "yes, 12 sole contractors" -- the most likely real answer to a question that
    asks 'how many?' -- matched nothing and fell through to the unanswered
    branch. That branch happened to fail closed, so the defect was safe; it was
    still a validator that could not read a yes.
    """
    rows = _rows(count=10, extra={"vehicle_ref": "SYNTH-UNIT-1"})
    result = assess(rows, declarations=dict(_ANSWERED, fleet_shape=answer))
    assert result.has("VEHICLE_REF_IS_A_PERSON_ID") is expect_person_id
    assert not result.has("FLEET_SHAPE_ANSWER_NOT_RECOGNISED")


def test_an_unreadable_fleet_shape_answer_fails_closed_rather_than_guessing() -> None:
    """"Not sure" is not "no". Matching the negative on the first word only is
    what keeps "not sure" and "no idea" out of the accepting branch -- and an
    ambiguous answer to a privacy question is the last place to resolve by
    resemblance."""
    rows = _rows(count=10, extra={"vehicle_ref": "SYNTH-UNIT-1"})
    for answer in (
        "not sure",
        "I would have to check with the contractor team",
        # "I have no idea" contains the word "no" and means the opposite of it.
        # Added after a mutation that matched the negative tokens ANYWHERE in the
        # answer came back green: the other two fixtures happen to contain no
        # negative token at all, so neither of them could tell the two rules
        # apart, and the first-word rule was certified by tests that never
        # exercised it.
        "I have no idea",
    ):
        result = assess(rows, declarations=dict(_ANSWERED, fleet_shape=answer))
        assert result.has("FLEET_SHAPE_ANSWER_NOT_RECOGNISED"), answer
        assert result.verdict_for("deadhead_measurement") is Verdict.NOT_SUPPORTED
        assert answer not in result.report(), "the answer must not be echoed back"


def test_a_free_text_no_to_alternatives_logging_still_withdraws_the_counterfactual() -> None:
    """Same failure shape, opposite safety direction: here a missed NO is the
    dangerous one, because it would let `alternatives=()` be recorded as a fact."""
    declarations = dict(
        _ANSWERED,
        run_roster="attached",
        alternatives_logged="No, the scheduler only stores the assignment it chose",
    )
    result = assess(_rows(known_at="genuine"), declarations=declarations)
    assert result.verdict_for("counterfactual_comparison") is Verdict.NOT_SUPPORTED


def test_an_unanswered_fleet_shape_question_fails_closed() -> None:
    """Not knowing whether a column is a person is not a reason to proceed."""
    declarations = {key: value for key, value in _ANSWERED.items() if key != "fleet_shape"}
    result = assess(_rows(count=10, extra={"vehicle_ref": "SYNTH-UNIT-1"}), declarations=declarations)
    assert result.has("FLEET_SHAPE_UNANSWERED")
    assert result.verdict_for("deadhead_measurement") is Verdict.NOT_SUPPORTED


# ===========================================================================
# 6. Structural and degenerate inputs
# ===========================================================================

def test_every_capability_requires_at_least_one_column() -> None:
    """Not decoration: this is the invariant that makes the empty-sample
    behaviour below fall out of the ordinary missing-column path.

    The validator used to carry a `row_count == 0 -> NOT_SUPPORTED` special case.
    A mutation deleting it came back green, and the mutation was right -- the
    branch was unreachable, because every capability names a column and an empty
    sample has none. The branch was removed and this assertion put in its place,
    so a future capability defined purely from declarations cannot silently make
    an empty file look supported.
    """
    for capability in contract.CAPABILITIES:
        columns = [
            name
            for name in capability.requires + capability.requires_any
            if contract.FIELDS_BY_NAME[name].shape is Shape.COLUMN
        ]
        assert columns, (
            f"capability {capability.id} requires no column at all, so an empty "
            "export would report it as supported"
        )


def test_an_empty_sample_produces_a_usable_report_rather_than_a_crash() -> None:
    """An empty file is a different problem from a bad one, and a validator that
    raised here would be useless at the exact moment an operator most needs to
    know what went wrong."""
    result = assess([], declarations=_ANSWERED)
    assert result.row_count == 0
    assert result.has("EMPTY_SAMPLE")
    assert all(item.verdict is Verdict.NOT_SUPPORTED for item in result.capabilities)
    assert result.report()


def test_missing_required_columns_are_named_individually() -> None:
    rows = [{"trip_ref": "SYNTH-1", "outcome": "served"}]
    result = assess(rows, declarations=_ANSWERED)
    codes = {item.code for item in result.findings}
    assert "REQUIRED_COLUMN_MISSING__REQUESTED_AT" in codes
    assert "REQUIRED_COLUMN_MISSING__VEHICLE_OR_RUN" in codes
    assert result.verdict_for("outcome_analysis") is Verdict.NOT_SUPPORTED


def test_a_conditionally_required_column_is_not_reported_as_simply_missing() -> None:
    """The false-positive direction, and the one that costs goodwill.

    `vehicle_ref` and `run_ref` are an either-or, and `actual_pickup_at` is
    required only for served rows. An export sending `run_ref` alone is fully
    compliant, and a validator that told that operator a required column was
    missing would be asking for more than the adapter enforces -- the exact
    drift the contract-versus-adapter test guards against, one level down.

    Added after a mutation that folded the conditional columns into the
    unconditional required loop came back GREEN: every fixture happened to carry
    `actual_pickup_at`, and none asserted the ABSENCE of a spurious finding.
    """
    result = assess(_rows(count=10), declarations=_ANSWERED)  # run_ref only, no vehicle_ref
    codes = {item.code for item in result.findings}
    assert "REQUIRED_COLUMN_MISSING__VEHICLE_REF" not in codes
    assert "REQUIRED_COLUMN_MISSING__RUN_REF" not in codes
    assert "REQUIRED_COLUMN_MISSING__VEHICLE_OR_RUN" not in codes
    assert "REQUIRED_COLUMN_MISSING__ACTUAL_PICKUP_AT" not in codes
    assert result.verdict_for("outcome_analysis") is Verdict.SUPPORTED


def test_a_served_row_with_no_actual_pickup_is_counted_not_ignored() -> None:
    """Those rows sit in the denominator of an on-time figure and cannot sit in
    the numerator. Substituting the scheduled time would invent precisely the
    number the analysis is about."""
    rows = _rows(count=10, served_only=True)
    rows[3]["actual_pickup_at"] = ""
    rows[7]["actual_pickup_at"] = ""
    result = assess(rows, declarations=_ANSWERED)
    finding = next(
        item for item in result.findings if item.code == "SERVED_ROWS_WITHOUT_AN_ACTUAL_PICKUP"
    )
    assert "2 rows" in finding.message

    clean = assess(_rows(count=10, served_only=True), declarations=_ANSWERED)
    assert not clean.has("SERVED_ROWS_WITHOUT_AN_ACTUAL_PICKUP")


def test_naive_timestamps_are_flagged_rather_than_silently_shifted() -> None:
    rows = _rows(count=5)
    for row in rows:
        row["scheduled_pickup_at"] = str(row["scheduled_pickup_at"]).replace("+00:00", "")
    result = assess(rows, declarations=_ANSWERED)
    assert result.has("TIMESTAMPS_WITHOUT_OFFSET")


def test_a_short_sample_is_measured_against_the_minimum_viable_window() -> None:
    result = assess(_rows(count=5), declarations=_ANSWERED)
    assert result.has("BELOW_MINIMUM_VIABLE_WINDOW")
    assert result.event_span_days is not None and result.event_span_days < 8 * 7


def test_unanswered_declarations_are_reported_as_questions_not_data_defects() -> None:
    result = assess(_rows(), declarations={"fleet_shape": "no"})
    codes = {item.code for item in result.findings}
    assert "DECLARATION_MISSING__COVERAGE_WINDOW" in codes
    assert "DECLARATION_MISSING__TIMESTAMP_CONVENTION" in codes
    assert result.verdict_for("outcome_analysis") is Verdict.NOT_SUPPORTED


def test_the_report_states_what_it_does_not_establish() -> None:
    """A clean report is the most dangerous output this tool can produce, so it
    carries its own limits."""
    rendered = assess(_rows(known_at="genuine"), declarations=_ANSWERED).report()
    assert "reports on the SAMPLE" in rendered
    assert "never run any of these on operator data" in rendered
    assert "Validated" in rendered


# ===========================================================================
# 7. The CLI, run as an operator would run it
# ===========================================================================

def test_the_validator_runs_as_a_command_on_a_csv(tmp_path: Path) -> None:
    """The artifact is only useful if an agency's IT lead can run it against
    a file. Asserted by RUNNING it, not by importing it -- the import path is
    already covered and would not catch a broken __main__."""
    import csv as csv_module

    rows = _rows(count=20)
    sample = tmp_path / "synthetic-sample.csv"
    with sample.open("w", encoding="utf-8", newline="") as handle:
        writer = csv_module.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)  # type: ignore[arg-type]

    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps(_ANSWERED), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(_REPO / "talos" / "contracts" / "validate_operator_export.py"),
            str(sample),
            "--declarations",
            str(answers),
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO),
    )
    assert completed.returncode == 0, completed.stderr
    assert "cannot support information-set replay" in completed.stdout
    assert "no source-side knowledge timestamp is present" in completed.stdout


def test_the_csv_entry_point_agrees_with_the_in_memory_one(tmp_path: Path) -> None:
    import csv as csv_module

    rows = _rows(count=12, known_at="genuine")
    sample = tmp_path / "synthetic-sample.csv"
    with sample.open("w", encoding="utf-8", newline="") as handle:
        writer = csv_module.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)  # type: ignore[arg-type]

    from_file = assess_csv(sample, declarations=_ANSWERED)
    in_memory = assess(rows, declarations=_ANSWERED)
    assert [item.verdict for item in from_file.capabilities] == [
        item.verdict for item in in_memory.capabilities
    ]


def test_a_refused_export_exits_nonzero_and_a_narrowed_one_does_not(tmp_path: Path) -> None:
    """The exit code distinguishes 'we will not take this file' from 'this file
    supports less than the maximum'. The second is a normal, useful answer and
    must not fail a pipeline."""
    import csv as csv_module

    def _write(rows: list[dict[str, object]], name: str) -> Path:
        path = tmp_path / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv_module.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)  # type: ignore[arg-type]
        return path

    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps(_ANSWERED), encoding="utf-8")

    narrowed = _write(_rows(count=5), "narrowed.csv")
    refused = _write(_rows(count=5, extra={"rider_name": "SYNTHETIC Jane Roe"}), "refused.csv")

    script = str(_REPO / "talos" / "contracts" / "validate_operator_export.py")
    ok = subprocess.run(
        [sys.executable, script, str(narrowed), "--declarations", str(answers)],
        capture_output=True, text=True, cwd=str(_REPO),
    )
    bad = subprocess.run(
        [sys.executable, script, str(refused), "--declarations", str(answers)],
        capture_output=True, text=True, cwd=str(_REPO),
    )
    assert ok.returncode == 0
    assert bad.returncode == 1
    assert "Jane Roe" not in bad.stdout


def test_the_json_output_is_machine_readable() -> None:
    """So the check can sit in a script an operator's IT team already runs."""
    result: ContractAssessment = assess(_rows(), declarations=_ANSWERED)
    payload = json.loads(json.dumps(result.as_dict()))
    assert payload["refused"] is False
    assert {item["id"] for item in payload["capabilities"]} == {
        capability.id for capability in contract.CAPABILITIES
    }


@pytest.mark.parametrize("capability", [item.id for item in contract.CAPABILITIES])
def test_every_capability_is_reachable_by_some_export(capability: str) -> None:
    """Totality. A capability that no possible export can support is a promise
    with no data behind it, and would sit in the contract forever reporting
    NOT_SUPPORTED with the operator unable to do anything about it."""
    rows = _rows(known_at="genuine", updated_at="revised", include_dropoff=True, extra={
        "denial_code": "D1",
        "trip_distance": "6.4",
    })
    declarations = dict(
        _ANSWERED,
        alternatives_logged="yes",
        run_roster="attached",
        candidate_log="attached",
        knowledge_time_source="the dispatch application, at the moment of entry",
        field_authority_map="AVL is authoritative for actual times",
    )
    result = assess(rows, declarations=declarations)
    assert result.verdict_for(capability) in (
        Verdict.SUPPORTED,
        Verdict.SUPPORTED_WITH_LIMITS,
    ), (
        f"no export can satisfy {capability}: "
        + "; ".join(
            reason
            for item in result.capabilities
            if item.capability_id == capability
            for reason in item.reasons
        )
    )
