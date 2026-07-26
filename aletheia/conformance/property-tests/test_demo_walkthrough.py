"""Conformance: the evidence walkthrough actually runs, and says what it claims.

A demo that silently rots is worse than no demo, so this suite RUNS
`argus.demo.walkthrough.run_walkthrough` once per session and asserts on the values it
computed -- not on its prose. Every assertion below is a load-bearing claim the
walkthrough or forge/knowledge/docs/DEMO.md makes to a reader:

  * the intake refuses a PII-carrying file in full and lets no identifier value
    into the quarantine record,
  * an ambiguous date is quarantined while its unambiguous twin is repaired,
  * no row is lost: imported + quarantined == submitted,
  * the decision is solved, independently feasibility-checked, and its denial
    carries real reason codes recorded at decision time,
  * every candidate vehicle is probed rather than asserted,
  * the teardown's attribution reconciles and its unattributable time stays out
    of the ranking,
  * no cost envelope exists without an operator cost split, and no figure is a
    guaranteed saving,
  * the conformal interval's guarantee is withdrawn under measured drift and
    granted on an exchangeable control -- so the monitor can come back either way,
  * the written pack re-derives from its own bytes through the verification
    path, which never imports the generator -- and FAILS on four separate
    tampers, without which "re-derived" would be an unfalsifiable claim.

The walkthrough writes into `tmp_path`, never the repo's artifacts directory.

SKIP DISCIPLINE. The synthetic export and the NTD economics table are committed,
so the intake/decide/teardown/evidence assertions always run. Only the drift
step depends on the two committed panels; if a checkout lacks them (a partial
clone), the drift assertions skip and everything else still runs -- the same
condition the walkthrough itself degrades on.
"""

from __future__ import annotations

import json

import pytest

from argus.demo.walkthrough import (
    AAR_PANEL,
    EXPORT_PART1,
    EXPORT_PART2,
    WEATHER_PANEL,
    run_walkthrough,
)
from argus.demo.verify_pack import verify_pack_file

_HAVE_PANELS = AAR_PANEL.exists() and WEATHER_PANEL.exists()


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo-walkthrough")
    return run_walkthrough(out, quiet=True)


# --------------------------------------------------------------------------
# intake
# --------------------------------------------------------------------------


def test_the_pii_carrying_first_send_is_refused_in_full(run) -> None:
    assert run.part1_rows == 4
    assert run.part1_accepted == 0
    # Not merely "quarantined": quarantined ON PII GROUNDS. A row rejected for a
    # bad timestamp would satisfy a weaker assertion and prove nothing here.
    assert run.part1_pii_quarantines == run.part1_rows


def test_no_identifier_value_survives_into_the_quarantine_record(run) -> None:
    assert run.part1_redaction_leaked is False


def test_the_resend_imports_and_the_count_closes(run) -> None:
    assert run.part2_rows == 24
    assert run.part2_accepted == 15
    assert run.part2_quarantined == 9
    assert run.conservation_holds is True
    assert run.part2_accepted + run.part2_quarantined == run.part2_rows


def test_the_walkthrough_exercises_the_whole_repair_vocabulary_it_claims(run) -> None:
    """The narration says "repair what is unambiguous"; these are the rules that
    actually fired. Named individually so a rule silently ceasing to fire (a
    regression in the adapter, or an edit to the export file) fails here rather
    than quietly shrinking the demo."""
    assert set(run.part2_repair_rules) == {
        "date_order_ddmm",
        "enum_synonym",
        "integral_float_identifier",
        "iso8601_utc_designator",
        "iso8601_variant",
        "requested_at_date_only",
        "trim_whitespace",
        "twelve_hour_clock",
    }
    assert run.semantic_loss_records > 0


def test_every_quarantine_class_the_walkthrough_narrates_is_present(run) -> None:
    assert set(run.part2_quarantine_codes) == {
        "ambiguous_date_order",
        "empty_row",
        "missing_required_field",
        "no_vehicle_or_run_ref",
        "pii_address_in_zone",
        "pii_direct_identifier",
        "repeated_header_row",
        "served_without_actual_pickup",
        "unknown_outcome_value",
    }


def test_the_ambiguous_date_is_declined_and_its_unambiguous_twin_repaired(run) -> None:
    """The pair is the refusal. Asserting only the quarantine would pass on an
    adapter that quarantined every slash date, which would be brittleness, not
    judgement."""
    assert run.ambiguous_date_quarantined is True
    assert run.unambiguous_date_repaired is True


def test_a_denial_and_a_no_show_become_records_rather_than_absences(run) -> None:
    assert run.canonical_requests == run.part2_accepted
    assert run.canonical_denied == 1
    assert run.canonical_no_show == 1


# --------------------------------------------------------------------------
# decide
# --------------------------------------------------------------------------


def test_the_decision_is_solved_and_independently_feasibility_checked(run) -> None:
    assert run.decision_status == "optimal"
    assert run.decision_proven_optimal is True
    assert run.decision_served == 4
    assert run.decision_denied == 1
    assert run.feasibility_violations == 0


def test_the_denial_carries_real_reason_codes_recorded_at_decision_time(run) -> None:
    from themis.canonical import ReasonCode

    assert run.denial_reason_codes
    for code in run.denial_reason_codes:
        assert ReasonCode(code)  # a member of the closed vocabulary, not prose


def test_every_candidate_vehicle_was_probed_and_none_could_take_the_trip(run) -> None:
    assert run.alternatives_probed == 3
    assert run.infeasible_alternatives == 3


def test_the_ledger_chain_verifies(run) -> None:
    assert run.ledger_events == 3
    assert run.ledger_integrity_verified is True
    assert run.ledger_chain_violations == 0


# --------------------------------------------------------------------------
# teardown
# --------------------------------------------------------------------------


def test_the_teardown_measures_what_it_can_and_counts_what_it_cannot(run) -> None:
    assert run.segments == 22
    assert run.revenue_segments == 13
    assert run.deadhead_segments == 9
    # A no-show, a denial and one over-long gap: excluded, and COUNTED rather
    # than silently treated as zero empty time.
    assert run.unmeasured_segments == 3
    assert run.total_deadhead_minutes > 0
    assert 0.0 < run.deadhead_share < 1.0


def test_unattributable_empty_time_is_kept_out_of_the_ranking_and_reconciles(run) -> None:
    assert run.unattributable_deadhead_minutes > 0
    assert run.attribution_reconciles is True
    # Two runs are named in the export; the third vehicle names none, so it must
    # NOT appear as a ranked run.
    assert run.attributed_run_count == 2


def test_the_cost_basis_is_the_real_committed_ntd_table(run) -> None:
    """Not a constant in the demo: recomputed from forge/business/ntd/agency_economics.csv this
    run. The band is wide enough to survive an NTD refresh and narrow enough to
    fail if the column stopped being a dollar rate."""
    assert 40.0 < run.ntd_cost_per_vrh < 200.0
    assert run.ntd_agency_count > 500
    assert 0.0 < run.ntd_deadhead_median < run.ntd_deadhead_p90 < 1.0


def test_no_envelope_without_the_operators_own_cost_split(run) -> None:
    assert "not supplied" in run.envelope_without_split
    assert run.value_at_full_cost is not None and run.value_at_full_cost > 0


def test_no_figure_is_presented_as_a_guaranteed_saving(run) -> None:
    assert run.is_guaranteed_saving is False
    assert run.envelope_low is not None and run.envelope_high is not None
    assert run.envelope_low < run.envelope_high
    # The envelope must sit strictly inside the accounting value: if it ever
    # equalled it, the "how much of this is real" hedge would be decorative.
    assert run.envelope_high < run.value_at_full_cost


# --------------------------------------------------------------------------
# drift
# --------------------------------------------------------------------------


@pytest.mark.skipif(not _HAVE_PANELS, reason="committed AAR/weather panels absent")
def test_the_interval_withdraws_its_guarantee_under_measured_drift(run) -> None:
    assert run.drift_assessed is True
    assert run.drift_serving_status == "drift"
    assert run.drift_serving_guarantee == "unsupported"
    assert len(run.drifted_features) >= 5


@pytest.mark.skipif(not _HAVE_PANELS, reason="committed AAR/weather panels absent")
def test_the_same_monitor_grants_the_guarantee_on_an_exchangeable_control(run) -> None:
    """Without this, "drift detected" would be unfalsifiable: a monitor that
    always says drift proves nothing about the serving window."""
    assert run.drift_control_status == "no_drift"
    assert run.drift_control_guarantee == "unqualified"


@pytest.mark.skipif(not _HAVE_PANELS, reason="committed AAR/weather panels absent")
def test_the_artifact_is_asked_for_its_reference_and_honestly_has_none(run) -> None:
    assert run.artifact_carried_reference is False
    # Two schema features the reference cannot cover, each recorded with a reason
    # rather than dropped: the categorical zone column and the holiday flag.
    assert "borough" in run.drift_skipped_features
    assert run.drift_reference_rows >= 30


# --------------------------------------------------------------------------
# the punchline
# --------------------------------------------------------------------------


def test_the_written_pack_rederives_from_its_own_bytes(run) -> None:
    assert run.pack_path is not None and run.pack_path.exists()
    assert run.pack_reverified is True
    assert run.chain_reverified is True
    assert run.manifest_consistent is True
    assert run.narrative_consistent is True
    assert run.teardown_figures_rederived is True
    assert run.teardown_fingerprint_rederived is True
    assert run.teardown_mismatches == ()
    # A re-derivation that checked nothing would also report no mismatches.
    assert run.teardown_checks > 50


def _tampered(run, tmp_path, mutate) -> dict:
    """Write a mutated copy of the exported pack and re-run the SAME verifier
    the walkthrough ran. Every mutation below is one a dishonest exporter would
    plausibly make."""
    pack = json.loads(run.pack_path.read_text(encoding="utf-8"))
    mutate(pack)
    path = tmp_path / "evidence_pack.json"
    path.write_text(json.dumps(pack), encoding="utf-8")
    return verify_pack_file(path, say=lambda *a, **k: None)


def test_rederivation_catches_a_tampered_teardown_figure(run, tmp_path) -> None:
    """The load-bearing test of the whole demo. Move ONE claimed number and the
    verifier that passed above must fail -- otherwise "independently re-derived"
    means nothing and every other assertion here is decoration."""

    def inflate(pack: dict) -> None:
        figures = pack["teardown"]["figures"]
        figures["total_deadhead_minutes"] = figures["total_deadhead_minutes"] + 10.0

    result = _tampered(run, tmp_path, inflate)
    assert result["teardown_figures_rederived"] is False
    assert any("total_deadhead_minutes" in m for m in result["teardown_mismatches"])
    assert result["reverified"] is False


def test_rederivation_catches_a_swapped_segment_set(run, tmp_path) -> None:
    """Tamper with an INPUT rather than a claim: drop one embedded segment. The
    figures no longer follow from the data AND the fingerprint no longer covers
    what is embedded, so both checks must fail."""

    def drop_segment(pack: dict) -> None:
        pack["teardown"]["segments"] = pack["teardown"]["segments"][:-1]

    result = _tampered(run, tmp_path, drop_segment)
    assert result["teardown_figures_rederived"] is False
    assert result["teardown_fingerprint_rederived"] is False
    assert result["reverified"] is False


def test_rederivation_catches_a_tampered_event_ledger(run, tmp_path) -> None:
    """The other half of the pack. Edit a recorded event's payload and the hash
    chain must fail to re-verify -- tamper-evidence is the claim the whole
    evidence story rests on."""

    def rewrite_history(pack: dict) -> None:
        row = next(r for r in pack["raw_events"] if "payload_json" in r)
        row["payload_json"] = row["payload_json"].replace("optimal", "timeout", 1)

    result = _tampered(run, tmp_path, rewrite_history)
    assert result["chain_reverified"] is False
    assert result["reverified"] is False


def test_rederivation_catches_a_manifest_that_describes_a_different_pack(
    run, tmp_path
) -> None:
    """The bundle checksum deliberately excludes the manifest -- it is where the
    checksum lives -- so a manifest claim is exactly what a checksum cannot
    protect. It is re-derived from the body instead."""

    def overstate(pack: dict) -> None:
        pack["manifest"]["event_count"] = 99

    result = _tampered(run, tmp_path, overstate)
    assert result["manifest_consistent"] is False
    assert result["reverified"] is False


def test_rederivation_catches_an_overstated_teardown_manifest_claim(
    run, tmp_path
) -> None:
    """The teardown's own manifest claims are re-derived too, and by a different
    route than the pack-level ones: this one surfaces as a teardown mismatch
    rather than a manifest problem. Asserted separately because a single
    "reverified is False" would not show which check did the work."""

    def overstate_teardown(pack: dict) -> None:
        pack["manifest"]["teardown_segment_count"] = 999

    result = _tampered(run, tmp_path, overstate_teardown)
    assert result["reverified"] is False
    assert any(
        "teardown_segment_count" in m for m in result["teardown_mismatches"]
    )
    # The figures themselves still follow from the embedded segments: the lie
    # was in the summary, not in the arithmetic, and the report says which.
    assert result["teardown_figures_rederived"] is True


# --------------------------------------------------------------------------
# the honesty invariants
# --------------------------------------------------------------------------


def test_the_run_manifest_states_its_own_boundaries(run) -> None:
    manifest = json.loads(run.manifest_path.read_text(encoding="utf-8"))
    assert manifest["demo"] == "milexium.walkthrough"
    assert "Demonstrated" in manifest["status_label"]
    assert "never Validated" in manifest["status_label"]
    assert manifest["teardown"]["is_guaranteed_saving"] is False
    assert len(manifest["boundaries"]) >= 5
    # The gaps this run found in the platform are recorded in the artifact, not
    # only in a report a reader may never see.
    assert len(manifest["known_gaps_found_by_this_run"]) >= 4


def test_the_synthetic_inputs_are_labelled_synthetic_in_their_own_filenames(run) -> None:
    """The rule is that a synthetic number is labelled on the line it appears.
    The strongest version of that is a filename nobody can print without the
    label coming along."""
    for path in (EXPORT_PART1, EXPORT_PART2):
        assert path.name.startswith("SYNTHETIC_")
    manifest = json.loads(run.manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["synthetic_inputs"].values():
        if isinstance(entry, dict) and "path" in entry:
            assert "SYNTHETIC" in entry["path"]


def test_the_walkthrough_finishes_well_inside_its_stated_budget(run) -> None:
    """forge/knowledge/docs/DEMO.md tells a reader this takes well under three minutes. On CI
    hardware slower than a laptop the margin still has to hold."""
    assert run.runtime_seconds < 120.0
