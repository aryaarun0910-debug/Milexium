"""Conformance for the panel-findings gate (MX-OUTREACH-PANEL-FINDINGS-009).

What these tests are actually protecting
----------------------------------------
`outreach/build_panel_findings.py` produces claims that go, in writing, to
career transit executives who know their own books. One wrong figure ends the
relationship, and we would probably never learn why. So the properties held
here are not "the code runs" -- they are:

1. The GATE CANNOT BE SKIPPED. A finding that never ran a composition,
   concentration or mode-provenance check is rejected for that reason alone.
   Silence is not a pass.
2. THE FOUR ESTABLISHED FINDINGS DO NOT DRIFT. Their numbers are hard-coded
   here, not read from the artifact and compared to itself. If a refactor moves
   the headline productivity decline, these fail.
3. THE KILLED CLAIM STAYS KILLED. "Demand-response demand is uniquely volatile"
   is false and sells well, which is a dangerous combination. There is a test
   whose only job is to fail if it ever reappears in `survived`.
4. NO NUMBER REACHES COPY WITHOUT A CITATION. The email generator refuses to
   write a draft containing a figure it cannot trace to a named field of
   panel_findings.json.

The committed `outreach/panel_findings.json` is the artifact under test for the
regression properties, so they run in a fresh clone with no raw data on disk.
The recomputation tests at the bottom re-derive the headline numbers from the
raw CSVs and skip cleanly when those (gitignored) bytes are absent.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_OUTREACH = _REPO / "outreach"
_ARTIFACT = _OUTREACH / "panel_findings.json"


def _load(name: str):
    """Import an outreach script by path -- outreach/ is deliberately not a
    package (it is a workspace of runnable scripts, not importable library
    code), so these tests load the modules rather than adding an __init__.py
    that would change how the rest of the repo sees that directory."""
    spec = importlib.util.spec_from_file_location(name, _OUTREACH / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


bpf = _load("build_panel_findings")
gee = _load("generate_expert_emails")


@pytest.fixture(scope="module")
def artifact() -> dict:
    if not _ARTIFACT.exists():
        pytest.fail("outreach/panel_findings.json is committed evidence and must "
                    "be present; regenerate with build_panel_findings.py")
    return json.loads(_ARTIFACT.read_text(encoding="utf-8"))


def _by_id(artifact: dict, fid: str) -> dict:
    for d in artifact["survived"] + artifact["rejected"]:
        if d["id"] == fid:
            return d
    raise AssertionError(f"{fid} missing from panel_findings.json")


def _passing(name: str) -> bpf.Check:
    return bpf.Check(name, True, "synthetic pass")


def _all_required_passing() -> list:
    return [_passing(n) for n in bpf.REQUIRED_CHECKS]


# ===========================================================================
# 1. The gate cannot be skipped
# ===========================================================================
@pytest.mark.parametrize("omitted", bpf.REQUIRED_CHECKS)
def test_finding_missing_any_required_check_is_rejected(omitted):
    """Forgetting to run a check must not read as passing it."""
    f = bpf.Finding(id="x", claim="c", source="s", numbers={})
    for name in bpf.REQUIRED_CHECKS:
        if name != omitted:
            f.add(_passing(name))
    d = f.as_dict()
    assert d["status"] == "rejected"
    assert "gate incomplete" in d["rejected_because"]
    assert omitted in d["rejected_because"]


def test_finding_with_no_checks_at_all_is_rejected():
    d = bpf.Finding(id="x", claim="c", source="s", numbers={}).as_dict()
    assert d["status"] == "rejected"
    for name in bpf.REQUIRED_CHECKS:
        assert name in d["rejected_because"]


def test_finding_with_every_required_check_passing_survives():
    f = bpf.Finding(id="x", claim="c", source="s", numbers={})
    for c in _all_required_passing():
        f.add(c)
    d = f.as_dict()
    assert d["status"] == "survived"
    assert "rejected_because" not in d


@pytest.mark.parametrize("failing", bpf.REQUIRED_CHECKS)
def test_any_single_failed_check_rejects_the_finding(failing):
    f = bpf.Finding(id="x", claim="c", source="s", numbers={})
    for name in bpf.REQUIRED_CHECKS:
        f.add(bpf.Check(name, name != failing, f"detail for {name}"))
    d = f.as_dict()
    assert d["status"] == "rejected"
    assert failing in d["rejected_because"]


def test_forced_rejection_beats_every_passing_check():
    """A claim known to be false stays rejected even if the arithmetic passes."""
    f = bpf.Finding(id="x", claim="c", source="s", numbers={})
    for c in _all_required_passing():
        f.add(c)
    f.forced_rejection = "known false"
    d = f.as_dict()
    assert d["status"] == "rejected"
    assert d["rejected_because"] == "known false"


# ===========================================================================
# 2. Each check actually discriminates
# ===========================================================================
def test_composition_passes_when_balanced_agrees_with_unbalanced():
    assert bpf.check_composition(-10.0, -11.0, 250).passed


def test_composition_rejects_a_sign_flip():
    """The aggregate fell but the same agencies rose: a composition effect."""
    c = bpf.check_composition(-10.0, +9.0, 250)
    assert not c.passed
    assert "FLIPPED" in c.detail


def test_composition_rejects_magnitude_collapse():
    """Balanced keeps the sign but loses most of the effect."""
    assert not bpf.check_composition(-10.0, -2.0, 250).passed


def test_composition_boundary_is_the_declared_constant():
    """Exactly at COMPOSITION_RETAIN passes; below it does not."""
    edge = -10.0 * bpf.COMPOSITION_RETAIN
    assert bpf.check_composition(-10.0, edge, 100).passed
    assert not bpf.check_composition(-10.0, edge * 0.99, 100).passed


def test_concentration_rejects_when_median_contradicts_aggregate():
    c = bpf.check_concentration(-10.0, +4.0, -9.0, -11.0, 3.0)
    assert not c.passed


def test_concentration_rejects_when_median_is_a_fraction_of_aggregate():
    """Aggregate -10%, typical operator -1%: one big operator is carrying it."""
    assert not bpf.check_concentration(-10.0, -1.0, -9.0, -11.0, 3.0).passed


def test_concentration_rejects_when_leave_one_out_flips_the_sign():
    """Dropping one operator reverses the finding."""
    assert not bpf.check_concentration(-10.0, -9.5, +2.0, -11.0, 40.0).passed


def test_concentration_passes_a_genuinely_diffuse_result():
    c = bpf.check_concentration(-11.4, -11.0, -12.7, -10.2, 5.8)
    assert c.passed
    assert "per-agency median" in c.detail


def test_mode_provenance_rejects_below_the_floor():
    assert not bpf.check_mode_provenance(80.0, 400, "all-mode denominator").passed
    assert bpf.check_mode_provenance(100.0, 400, "DR-only denominator").passed


def test_inflation_check_reports_both_nominal_and_real():
    c = bpf.check_inflation(77.2, 33.9, 2015, 2024)
    assert c.passed
    assert "nominal" in c.detail and "REAL" in c.detail
    assert "77.2" in c.detail and "33.9" in c.detail
    assert bpf.CPI_SOURCE in c.detail


def test_inflation_check_rejects_a_rise_that_is_only_inflation():
    """+26% nominal over a decade with CPI at +32% is a real DECREASE."""
    assert not bpf.check_inflation(26.0, -4.5, 2015, 2024).passed


def test_control_mode_check_discriminates_in_both_directions():
    assert bpf.check_control_mode(2.0, 1.0, "m", must_exceed=True).passed
    assert not bpf.check_control_mode(1.0, 2.0, "m", must_exceed=True).passed
    assert bpf.check_control_mode(1.0, 2.0, "m", must_exceed=False).passed


def test_effect_size_uses_the_declared_thresholds():
    assert bpf.check_effect(bpf.MIN_EFFECT_PCT).passed
    assert not bpf.check_effect(bpf.MIN_EFFECT_PCT - 0.1).passed
    assert bpf.check_effect(bpf.MIN_SPREAD_RATIO, kind="spread").passed
    assert not bpf.check_effect(bpf.MIN_SPREAD_RATIO - 0.01, kind="spread").passed


def test_effect_size_is_symmetric_for_falls_and_rises():
    assert bpf.check_effect(-11.4).passed and bpf.check_effect(11.4).passed


# ===========================================================================
# 3. The four established findings do not drift
#
# Expected values are written out here on purpose. Reading them from the
# artifact and comparing it to itself would pass no matter what the code did.
# ===========================================================================
def test_established_productivity_decline_reproduces(artifact):
    n = _by_id(artifact, "dr_productivity_decline_2005_2024")["numbers"]
    assert n["trips_per_vrh_2005"] == pytest.approx(2.02, abs=0.01)
    assert n["trips_per_vrh_2024"] == pytest.approx(1.79, abs=0.01)
    assert n["change_pct"] == pytest.approx(-11.4, abs=0.3)
    assert n["per_agency_median_change_pct"] == pytest.approx(-11.0, abs=0.3)
    assert n["pct_of_agencies_less_productive"] == pytest.approx(63.5, abs=1.0)
    assert n["n_balanced_agencies"] == 263


def test_productivity_decline_is_not_covid(artifact):
    """2024 landed on 2019. If this ever drifts, the whole 'structural, not
    pandemic' reading of the finding goes with it."""
    n = _by_id(artifact, "dr_productivity_decline_2005_2024")["numbers"]
    assert abs(n["change_2019_to_2024_pct"]) < 2.0
    assert n["trips_per_vrh_2019"] == pytest.approx(1.83, abs=0.02)


def test_established_recovery_dispersion_reproduces(artifact):
    n = _by_id(artifact, "dr_recovery_dispersion_2019_2024")["numbers"]
    assert n["median_recovery_pct"] == pytest.approx(87.4, abs=0.5)
    assert n["p10_recovery_pct"] == pytest.approx(60.8, abs=0.5)
    assert n["p90_recovery_pct"] == pytest.approx(152.2, abs=1.0)
    assert n["p90_over_p10"] == pytest.approx(2.5, abs=0.05)


def test_recovery_dispersion_beats_the_single_national_number(artifact):
    """The point of the finding is that the aggregate describes almost nobody."""
    n = _by_id(artifact, "dr_recovery_dispersion_2019_2024")["numbers"]
    assert n["p90_recovery_pct"] - n["p10_recovery_pct"] > 80


def test_established_deadhead_level_reproduces(artifact):
    n = _by_id(artifact, "dr_deadhead_level_2024")["numbers"]
    assert n["n_operators"] == 406
    assert n["median_deadhead_pct"] == pytest.approx(15.1, abs=0.2)
    assert n["p90_deadhead_pct"] == pytest.approx(25.5, abs=0.3)


def test_deadhead_finding_is_labelled_as_a_single_year_cross_section(artifact):
    """No deadhead time series exists in anything we hold. If a future edit
    quietly starts claiming a trend, this fails."""
    d = _by_id(artifact, "dr_deadhead_level_2024")
    assert "2024" in d["numbers"]["year_scope"]
    assert "cross-section" in d["numbers"]["year_scope"]
    assert any("deadhead" in s.lower() and "time series" in s.lower()
               for s in artifact["not_computable"])


# --- the killed candidate -------------------------------------------------
def test_volatility_myth_is_rejected(artifact):
    """THE regression test. 'Demand-response demand is uniquely volatile, so you
    need forecasting' is FALSE and it sells, which is why it keeps coming back.

    Asserts the PERMANENT rejection specifically, not merely that the finding
    is currently rejected: the claim is also caught by its failing control-mode
    check, and if the deliberate kill were removed the finding would still be
    rejected today for an incidental reason and could quietly come back the
    moment the underlying numbers moved.
    """
    d = _by_id(artifact, "dr_demand_is_uniquely_volatile")
    assert d["status"] == "rejected"
    assert "FALSE" in d["rejected_because"]
    assert "PERMANENTLY DEAD" in d["rejected_because"]


def test_volatility_myth_also_fails_its_control_check(artifact):
    """Defence in depth: even without the permanent kill, the arithmetic
    rejects it. Both mechanisms are asserted so neither can be removed
    silently."""
    d = _by_id(artifact, "dr_demand_is_uniquely_volatile")
    control = [c for c in d["checks"] if c["check"] == "control_mode"]
    assert control and control[0]["verdict"] == "FAIL", control


def test_volatility_myth_never_appears_in_the_survived_list(artifact):
    assert all(d["id"] != "dr_demand_is_uniquely_volatile"
               for d in artifact["survived"])


def test_demand_response_is_measurably_less_volatile_than_bus(artifact):
    """The truthful statement of the same measurement, with the ordering that
    makes the myth false."""
    n = _by_id(artifact, "dr_demand_is_more_stable_than_bus")["numbers"]
    assert n["dr_median_cv_pct"] < n["bus_median_cv_pct"]
    assert n["dr_median_amplitude_pct"] < n["bus_median_amplitude_pct"]
    assert n["dr_median_cv_pct"] == pytest.approx(7.8, abs=0.3)
    assert n["bus_median_cv_pct"] == pytest.approx(10.2, abs=0.3)


def test_deadhead_extreme_tail_stays_rejected(artifact):
    """The dramatic tail reads well and is not a sector finding: it is 2% of
    filers, and two of the nine run under 1,000 vehicle-hours a year."""
    d = _by_id(artifact, "dr_deadhead_extreme_tail_2024")
    assert d["status"] == "rejected"
    n = d["numbers"]
    assert n["rate_above_40pct_all_filers"] < 5.0
    assert n["rate_above_40pct_above_size_floor"] < n["rate_above_40pct_all_filers"]
    assert n["n_tail_below_1000_annual_hours"] >= 1


def test_the_extreme_tail_is_NOT_blamed_on_mode_mix(artifact):
    """A guard against a plausible-sounding error we nearly shipped.

    "Nine agencies exceed 40%, but only one of the demand-response-dominant
    ones does, so the tail is a fixed-route artifact" is arithmetic about
    subgroup size, not evidence: only 11% of filers are DR-dominant, so one
    survivor out of nine is exactly the expected count. The two RATES are equal
    to two decimal places. If a future edit reinstates the mode-mix story, the
    rates will have to disagree first -- and this fails if they do not.
    """
    n = _by_id(artifact, "dr_deadhead_extreme_tail_2024")["numbers"]
    assert n["rate_above_40pct_all_filers"] == pytest.approx(
        n["rate_above_40pct_among_dr_dominant"], abs=0.5), (
        "the mode-mix explanation is only admissible if the rates actually "
        "differ; state whatever the numbers say, not the tidy story")
    composition = [c for c in _by_id(artifact, "dr_deadhead_extreme_tail_2024")["checks"]
                   if c["check"] == "composition"][0]
    assert composition["verdict"] == "pass"
    assert "NOT a mode-mix artifact" in composition["detail"]


# ===========================================================================
# 4. Artifact-wide invariants
# ===========================================================================
def test_every_survived_finding_passed_every_check_it_ran(artifact):
    for d in artifact["survived"]:
        failed = [c for c in d["checks"] if c["verdict"] != "pass"]
        assert not failed, f"{d['id']} survived with failures: {failed}"


def test_every_survived_finding_ran_every_required_check(artifact):
    for d in artifact["survived"]:
        ran = {c["check"] for c in d["checks"]}
        missing = set(bpf.REQUIRED_CHECKS) - ran
        assert not missing, f"{d['id']} survived without running {missing}"


def test_every_rejected_finding_says_why_with_numbers(artifact):
    for d in artifact["rejected"]:
        why = d.get("rejected_because", "")
        assert why, f"{d['id']} rejected with no reason"
        assert any(ch.isdigit() for ch in why), (
            f"{d['id']} rejected on an opinion, not a measurement: {why}")


def test_every_finding_names_a_real_source_file(artifact):
    known = {bpf.SRC_MONTHLY, bpf.SRC_OPEX, bpf.SRC_ECON}
    for d in artifact["survived"] + artifact["rejected"]:
        assert any(s in d["source"] for s in known), (
            f"{d['id']} does not name a source file: {d['source']}")


def test_findings_quoting_money_over_years_carry_the_inflation_check(artifact):
    """A nominal-only money change over a decade is a misleading claim even
    when every digit is right."""
    for d in artifact["survived"]:
        money = any("usd" in k for k in d["numbers"])
        multiyear = "2015" in d["source"] and "2024" in d["source"]
        if money and multiyear:
            ran = {c["check"] for c in d["checks"]}
            assert "inflation" in ran, f"{d['id']} quotes money over years with no CPI check"


def test_inflation_adjusted_figure_is_smaller_than_the_nominal_one(artifact):
    n = _by_id(artifact, "dr_cost_growth_split_2015_2024")["numbers"]
    assert n["cost_per_trip_change_real_pct"] < n["cost_per_trip_change_nominal_pct"]
    assert n["cost_per_trip_change_nominal_pct"] == pytest.approx(77.2, abs=1.0)
    assert n["cost_per_trip_change_real_pct"] == pytest.approx(33.9, abs=1.0)
    assert n["cpi_source"] == bpf.CPI_SOURCE


def test_the_gate_actually_rejects_things(artifact):
    """A gate that never rejects anything is decoration. Rejected findings are
    the evidence that it does something."""
    assert artifact["counts"]["rejected"] >= 3
    assert artifact["counts"]["survived"] >= 3


def test_nothing_is_ever_claimed_as_validated(artifact):
    """Status vocabulary is exact. This is public data with no holdout and no
    counterfactual, so Validated is not available to it."""
    assert artifact["status"] == "Demonstrated"
    assert "Validated" in artifact["status_note"]
    blob = json.dumps(artifact)
    assert '"status": "Validated"' not in blob


def test_limitations_are_recorded_not_omitted(artifact):
    assert len(artifact["not_computable"]) >= 3
    joined = " ".join(artifact["not_computable"]).lower()
    assert "cause" in joined


def test_gate_constants_are_published_in_the_artifact(artifact):
    """A threshold that lives only in code is not auditable by the reader of a
    claim."""
    g = artifact["gate"]
    assert g["min_effect_pct"] == bpf.MIN_EFFECT_PCT
    assert g["composition_retain_fraction"] == bpf.COMPOSITION_RETAIN
    assert set(g["required_checks"]) == set(bpf.REQUIRED_CHECKS)


def test_external_constants_are_declared_as_external(artifact):
    """CPI is the one number here not drawn from a governed dataset. It says so."""
    ext = artifact["panel"]["external_constants"]
    assert "BLS" in ext["cpi"]
    assert set(ext["values"]) == {"2015", "2024"}


# ===========================================================================
# 5. No number reaches copy without a citation
# ===========================================================================
def test_untraceable_number_in_copy_is_refused():
    c = gee.Cited()
    c.n("15.1%", "some_finding", "median_deadhead_pct")
    with pytest.raises(gee.CopyError, match="UNTRACEABLE NUMBER"):
        c.verify("median is 15.1% and p90 is 25.5%")


def test_cited_numbers_pass_verification():
    c = gee.Cited()
    c.n("15.1%", "f", "a")
    c.n("25.5%", "f", "b")
    c.verify("median is 15.1% and p90 is 25.5%")


def test_a_year_outside_the_findings_source_window_is_refused():
    c = gee.Cited()
    finding = {"id": "f", "source": "file; report years 2015 and 2024"}
    assert c.year(2015, finding) == "2015"
    with pytest.raises(gee.CopyError, match="not in the source window"):
        c.year(2019, finding)


def test_provenance_is_recorded_for_every_cited_number():
    c = gee.Cited()
    c.n("$51.70", "dr_cost_growth_split_2015_2024", "cost_per_trip_2024_usd")
    prov = c.provenance()
    assert len(prov) == 1
    assert "panel_findings.json" in prov[0]
    assert "cost_per_trip_2024_usd" in prov[0]


def test_rationing_framing_is_refused():
    """This segment's published position rejects trip-by-trip restriction."""
    with pytest.raises(gee.CopyError, match="FORBIDDEN FRAMING"):
        gee.check_framing("You could serve fewer trips for the same money.")
    with pytest.raises(gee.CopyError, match="FORBIDDEN FRAMING"):
        gee.check_framing("Restrict eligibility on a trip-by-trip basis.")


def test_compliance_as_a_ceiling_framing_is_refused():
    with pytest.raises(gee.CopyError, match="FORBIDDEN FRAMING"):
        gee.check_framing("It helps you stay compliant with the ADA.")


def test_releasing_capacity_framing_is_allowed():
    """The guard must not be so blunt that the correct framing cannot be said."""
    gee.check_framing("Capacity already paid for and sitting in the schedule.")


def test_a_rejected_finding_cannot_be_used_in_copy(artifact):
    with pytest.raises(gee.CopyError, match="REJECTED list"):
        gee._f(artifact, "dr_demand_is_uniquely_volatile")


def test_an_unknown_finding_cannot_be_used_in_copy(artifact):
    with pytest.raises(gee.CopyError, match="not in panel_findings.json"):
        gee._f(artifact, "no_such_finding")


def test_every_angle_builds_only_from_survived_findings(artifact):
    survived = {d["id"] for d in artifact["survived"]}
    for _, angle in gee.ANGLES:
        c = gee.Cited()
        subject, body = angle(artifact, c)
        assert subject and body
        assert c.tokens, f"{angle.__name__} emitted copy citing no numbers"
        used = {v.split(" :: ")[1] for v in c.tokens.values()}
        assert used <= survived, f"{angle.__name__} used non-survived {used - survived}"


# ===========================================================================
# 6. Send-safety holds
# ===========================================================================
def _consultancy_rows() -> list[dict]:
    import csv
    return list(csv.DictReader(
        (_OUTREACH / "targets_consultancies.csv").open(encoding="utf-8-sig")))


@pytest.mark.parametrize("needle,why", [
    ("Christian T. Kent",
     "he answered a cold email with his own time; sending him another from a "
     "target list is the clearest possible signal we never read it"),
    ("Foursquare ITP",
     "his named teaming partner -- same conflict, same cost"),
])
def test_kent_and_his_partner_are_held_by_their_exact_target_row(needle, why):
    """The hold is keyed on the `firm` column, so a key that does not match the
    CSV byte-for-byte is decorative. This resolves the firm from the target
    file itself and requires THAT string to be held -- a near-miss key (a
    rename, a prefix, a stray space) fails here rather than silently sending.
    """
    rows = [r for r in _consultancy_rows() if needle in r["firm"]]
    assert rows, f"{needle} is not in targets_consultancies.csv at all"
    for r in rows:
        assert r["firm"].strip() in gee.HOLD_FOR_VERIFICATION, (
            f"{r['firm']!r} would receive a cold email: {why}")


def test_the_hold_keys_all_correspond_to_real_target_rows():
    """The mirror property: a hold on a firm that is not in the list is a hold
    that protects nothing, and usually means the name drifted."""
    firms = {r["firm"].strip() for r in _consultancy_rows()}
    for key in gee.HOLD_FOR_VERIFICATION:
        assert key in firms, f"held firm {key!r} matches no row in the target file"


def test_competitors_are_blocked_as_a_segment():
    assert "B-COMPETITOR" in gee.BLOCKED_SEGMENTS


def test_held_targets_are_not_marked_do_not_contact():
    """A reversible sequencing hold must never be laundered into the permanent,
    structural opt-out column -- that would burn a valid target forever."""
    import csv
    rows = list(csv.DictReader(
        (_OUTREACH / "targets_consultancies.csv").open(encoding="utf-8-sig")))
    for r in rows:
        if r["firm"].strip() in gee.HOLD_FOR_VERIFICATION:
            assert not (r.get("do_not_contact") or "").strip(), (
                f"{r['firm']} is a temporary hold but carries do_not_contact")


def test_worksheet_holds_are_recorded_without_do_not_contact():
    """Same property on the agency worksheet: PSTA and CCCTA are held out of
    the tranche because they are the consultant's published clients, which is a
    sequencing decision for a human, not an opt-out."""
    import csv
    rows = list(csv.DictReader(
        (_OUTREACH / "contact_research_worksheet.csv").open(encoding="utf-8-sig")))
    held = {"Pinellas Suncoast Transit", "County Connection"}
    seen = set()
    for r in rows:
        if r["short_name"] in held:
            seen.add(r["short_name"])
            assert r["status"].startswith("HOLD"), f"{r['short_name']}: {r['status']}"
            assert not r["do_not_contact"].strip()
    assert seen == held


def test_the_opted_out_agency_is_still_opted_out():
    """Anne Arundel County asked to be removed. Nothing in this packet may
    weaken that."""
    import csv
    rows = list(csv.DictReader(
        (_OUTREACH / "contact_research_worksheet.csv").open(encoding="utf-8-sig")))
    row = next(r for r in rows if r["short_name"] == "Anne Arundel County")
    assert row["do_not_contact"].strip().startswith("YES")


def test_the_agency_operating_for_the_opted_out_county_is_never_contactable():
    """RTA runs service for Anne Arundel, who asked in writing to be removed.
    Approaching RTA could read as routing around that request.

    This test originally pinned the row as HOLD with `do_not_contact` EMPTY,
    because the question was awaiting a human and an agent must not resolve it
    either way. **The founder resolved it on 2026-07-26: do not contact.** So the
    assertion moved from "is parked" to the thing that actually has to stay true
    forever -- RTA is not contactable, and the reason names Anne Arundel.

    It is deliberately asserted on `do_not_contact` rather than on `status`.
    `outreach/README.md`: that column is "permanent and structural -- it is a
    column, not a status string, so no later merge can quietly return an
    opted-out organisation to a follow-up queue." A status string is exactly what
    a future tidy-up would rewrite.
    """
    import csv
    rows = list(csv.DictReader(
        (_OUTREACH / "contact_research_worksheet.csv").open(encoding="utf-8-sig")))
    row = next(r for r in rows
               if r["short_name"] == "Regional Transportation Agency of Central Maryland")

    dnc = row["do_not_contact"].strip()
    assert dnc, "RTA must remain permanently un-contactable via do_not_contact"
    assert "Anne Arundel" in dnc, (
        "the reason must name the relationship, or a later reader cannot tell "
        "why an agency that never contacted us is blocked"
    )
    # It must NOT be recorded as RTA's own opt-out. RTA has asked us for nothing;
    # claiming otherwise would be a false record about a third party.
    assert "NOT their own opt-out" in dnc or "FOUNDER DECISION" in dnc
    assert not row["contact_email"].strip(), "no address should be held for RTA"


# ===========================================================================
# 7. Generated copy obeys the researched budget
# ===========================================================================
@pytest.fixture(scope="module")
def generated() -> list[tuple[str, str]]:
    rows = [
        {"firm": "F", "what_they_do": w, "why_channel": "", "contact_name": "Jo Bloggs",
         "is_named_person_inbox": "named"}
        for w in ("cost and financial analysis", "procurement and rfp support",
                  "paratransit and ada consulting", "operations and scheduling")
    ]
    art = json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    return [gee.compose(r, art)[:2] for r in rows]


def test_every_generated_subject_is_short_and_lowercase(generated):
    for subject, _ in generated:
        assert subject == subject.lower()
        assert len(subject) <= gee.MAX_SUBJECT_CHARS, subject
        assert 2 <= len(subject.split()) <= 5, subject


def test_every_generated_body_is_inside_the_word_budget(generated):
    for _, body in generated:
        wc = len(body.split()) - 2
        assert 40 <= wc <= gee.MAX_WORDS, f"{wc} words: {body}"


def test_generated_copy_contains_no_links_or_attachments(generated):
    for _, body in generated:
        assert "http" not in body and "www." not in body


def test_generated_copy_makes_exactly_one_ask(generated):
    """Single-ask CTAs lift replies 35-42% (outreach/craft_notes.md). Two
    question marks means two asks."""
    for _, body in generated:
        assert body.count("?") <= 1, body


def test_shared_inbox_gets_no_first_name():
    art = json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    row = {"firm": "F", "what_they_do": "cost analysis", "why_channel": "",
           "contact_name": "Jo Bloggs", "is_named_person_inbox": "shared"}
    _, body, _ = gee.compose(row, art)
    assert "Hi there," in body
    assert "Jo" not in body


def test_named_inbox_gets_the_first_name_only():
    art = json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    row = {"firm": "F", "what_they_do": "cost analysis", "why_channel": "",
           "contact_name": "Jo Bloggs", "is_named_person_inbox": "named"}
    _, body, _ = gee.compose(row, art)
    assert "Hi Jo," in body
    assert "Bloggs" not in body


def test_over_budget_copy_is_refused_not_merely_flagged(monkeypatch):
    """A warning next to a written file is a file that gets sent anyway."""
    art = json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    monkeypatch.setattr(gee, "MAX_WORDS", 10)
    row = {"firm": "F", "what_they_do": "cost analysis", "why_channel": "",
           "contact_name": "", "is_named_person_inbox": "shared"}
    with pytest.raises(gee.CopyError, match="MAX_WORDS"):
        gee.compose(row, art)


# ===========================================================================
# 8. Re-derivation from the raw bytes (skips on a fresh clone)
# ===========================================================================
_HAVE_RAW = bpf.MONTHLY.exists() and bpf.OPEX.exists() and bpf.ECON.exists()
_needs_raw = pytest.mark.skipif(
    not _HAVE_RAW, reason="raw NTD extracts are gitignored; re-acquire via the "
                          "governed estate pipeline to run re-derivation tests")


@pytest.fixture(scope="module")
def raw():
    return bpf.load_monthly(), bpf.load_opex(), bpf.load_econ()


@_needs_raw
def test_agency_economics_is_demand_response_scoped_not_all_modes(raw):
    """This was contested and is load-bearing: every deadhead claim in the file
    depends on it. Decided from the bytes, on every run."""
    monthly, opex, econ = raw
    agree, n, how = bpf.econ_mode_provenance(econ, opex)
    assert n > 1000
    assert agree >= 95.0, how
    assert bpf.check_mode_provenance(agree, n, how).passed


@_needs_raw
def test_deadhead_columns_inherit_that_demand_response_scope(raw):
    """actual_hours - deadhead_hours == vrh, and vrh is DR-only."""
    _, _, econ = raw
    e = econ[(econ.report_year == 2024) & econ.deadhead_pct_hours.notna()]
    assert bpf.deadhead_identity_agreement(e) > 80.0


@_needs_raw
def test_the_file_contains_no_separate_dt_mode_code(raw):
    """The industry says 'DR and DT'; NTD encodes the taxi/TNC variants as
    Mode=DR with a different Type of Service. If a future vintage introduces a
    real DT code, DR_MODES must be widened or the panel silently loses rows."""
    monthly, _, _ = raw
    assert (monthly["Mode"] == "DT").sum() == 0
    assert set(monthly[monthly["Mode"] == "DR"]["TOS"].unique()) >= {"DO", "PT", "TX"}


@_needs_raw
def test_headline_productivity_decline_recomputes_from_raw(raw):
    monthly, _, _ = raw
    ay = bpf.dr_agency_year(monthly)
    m = bpf._ratio_endpoints(ay, "upt", "vrh", 2005, 2024)
    assert m["agg_y0"] == pytest.approx(2.02, abs=0.01)
    assert m["agg_y1"] == pytest.approx(1.79, abs=0.01)
    assert m["balanced_pct"] == pytest.approx(-11.4, abs=0.3)


@_needs_raw
def test_month_completeness_counts_distinct_months_not_rows(raw):
    """An agency running demand response under two types of service files two
    rows per month. Counting rows silently dropped every multi-contract
    operator from the panel and moved the headline decline from -11.4% to
    -15.7%. This test is that bug's headstone."""
    monthly, _, _ = raw
    ay = bpf.dr_agency_year(monthly, complete_months=False)
    multi = ay[ay.months > 12]
    assert multi.empty, (
        "months must be a distinct-month count and can never exceed 12; "
        f"got max {ay.months.max()}")
    kept = bpf.dr_agency_year(monthly)
    assert len(kept[kept.year == 2005]) > 250
