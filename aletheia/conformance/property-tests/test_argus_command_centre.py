"""Argus command-centre conformance (packet MX-ARGUS-COMMAND-CENTRE-016).

A generated artifact that silently rots is worse than none, so these tests run
the real generator and assert on what it produced. Nothing here is a fixture
standing in for the page.

SIX CLAIMS ARE ON TRIAL.

1. **EVERY NUMBER CARRIES ITS SOURCE.** Not "the code has a Source class" --
   every figure the generator emitted must appear in the rendered HTML *with*
   its citation, and every table on the page must carry one too. The test walks
   the emitted ledger rather than a list written here, so a figure added later
   is covered the day it is added.

2. **ARGUS DID NOT ORIGINATE ANYTHING.** Values attributed to Themis, Metis or
   Aletheia must actually equal what those layers return when asked
   independently, and the module must not carry a fallback for the case where a
   layer declines. Both are checked against live calls, not against constants.

3. **THE DECLARED INPUTS ARE DISCLOSED, NOT BLENDED.** A figure that depends on
   a declared modelling assumption must be attributed to it and must appear in
   the disclosure table. The attribution machinery takes the WEAKEST input,
   which is the direction an author forgets.

4. **THE REFUSALS ARE ON THE PAGE.** Each one is asserted by what it refused,
   and the drift refusal must carry the monitor's own withdrawal text rather
   than a paraphrase.

5. **THE ACCESSIBLE-CAPACITY LAYER IS NOT INERT.** `can_bind` must be true and
   at least one authority must actually refuse on accessible capacity. A page
   whose equipment constraint could never bite would be reporting nothing while
   looking like it reported something -- this repository has shipped that bug
   before (ADR-0073).

6. **THE PAGE IS SELF-CONTAINED AND SAYS WHAT IT IS.** No network reference, no
   script, a declared charset, and the synthetic/Demonstrated status on the page
   itself rather than in a README.

The generator is run ONCE per module. It reads a 571k-row committed panel for
the drift section, so this suite is measured in seconds rather than
milliseconds; that is the price of testing the artifact instead of a mock of it.
"""

from __future__ import annotations

import json
import re

import pytest

from argus.command_centre.attribution import (
    ORIGIN_LABELS,
    Figure,
    FigureLedger,
    Source,
    UnattributedFigure,
)
from argus.command_centre.picture import (
    ARGUS_PROHIBITION,
    CAPACITY_DRAWS,
    CAPACITY_SCENARIOS,
    SYNTHETIC_BANNER,
    build_operating_picture,
)
from argus.command_centre.render import render_html, write_artifact


@pytest.fixture(scope="module")
def picture():
    return build_operating_picture(include_real_drift=True)


@pytest.fixture(scope="module")
def page(picture) -> str:
    return render_html(picture)


_PROJECTION_CACHE: dict[str, object] = {}


def _rebuild_projection(picture):
    """Rebuild the DARP projection the page was built from, once per session.

    The generator does not keep it, and several tests need to interrogate the
    instance directly rather than through the figures it produced -- which is
    the point: a test that can only see the page's own summary of a thing
    cannot tell whether that thing was doing any work.
    """
    from argus.command_centre import picture as module
    from argus.demo import walkthrough as demo

    if "projection" in _PROJECTION_CACHE:
        return _PROJECTION_CACHE["projection"]

    quiet = lambda *a, **k: None  # noqa: E731
    client, recorded_at = demo._new_client()
    result = demo.WalkthroughResult()
    demo._step_1_pii(quiet, result, recorded_at)
    summary, raw_rows, accepted = demo._step_2_intake(quiet, result, client, recorded_at)
    records = demo._step_3_canonical(quiet, result, summary, raw_rows)
    pairs = module._pair_records_to_rows(records, accepted)

    scratch = module.OperatingPicture(
        generated_at=picture.generated_at,
        service_day=picture.service_day,
        ledger=FigureLedger(),
    )
    module._current_state(scratch, result, summary, records, pairs, accepted)
    projection = module._build_projection(scratch, pairs, accepted)
    _PROJECTION_CACHE["projection"] = projection
    _PROJECTION_CACHE["pairs"] = pairs
    _PROJECTION_CACHE["records"] = records
    _PROJECTION_CACHE["accepted"] = accepted
    return projection


# =========================================================================== #
# 1. EVERY NUMBER CARRIES ITS SOURCE
# =========================================================================== #
def test_every_emitted_figure_appears_on_the_page_with_its_citation(picture, page):
    """The claim the artifact exists to make, checked over the artifact.

    Walks the ledger the generator produced -- so this covers figures nobody has
    written yet -- and requires the rendered value, the origin label and the
    citation to all be present. A page that showed the number and dropped the
    attribution passes a weaker test than this one and fails this one.
    """
    import html as html_module

    missing: list[str] = []
    for figure in picture.ledger.figures:
        for needle in (
            figure.display,
            ORIGIN_LABELS[figure.source.origin],
            figure.source.citation,
        ):
            if html_module.escape(needle, quote=True) not in page:
                missing.append(f"{figure.key}: {needle!r}")
    assert not missing, "figures rendered without their attribution:\n" + "\n".join(missing)


def test_every_table_renders_its_source(picture, page):
    """Tables carry numbers too.

    Asserted POSITIVELY: every registered table source's citation and detail
    must be on the page. Checking only for the absence of the defect marker was
    the first version of this test, and a renderer that emitted nothing at all
    passed it -- the exact vacuity shape this repository keeps finding, because
    the assertion never reached the case it was guarding.
    """
    import html as html_module

    assert "UNATTRIBUTED TABLE" not in page
    assert len(picture.table_sources) >= 8, "tables were added without registering a source"
    for key, source in picture.table_sources.items():
        assert html_module.escape(source.citation, quote=True) in page, f"table {key}"
        assert html_module.escape(source.detail, quote=True) in page, f"table {key}"


def test_the_renderer_marks_a_table_it_was_given_no_source_for():
    """The other half: the defect marker has to actually appear when the case
    arises, or the test above is checking for the absence of something that can
    never be present."""
    from argus.command_centre.render import _table

    assert "UNATTRIBUTED TABLE" in _table(["h"], [["1"]], None)
    attributed = _table(["h"], [["1"]], Source(origin="themis", citation="c", detail="d"))
    assert "UNATTRIBUTED TABLE" not in attributed
    assert "c" in attributed and "d" in attributed


def test_a_figure_cannot_be_built_without_saying_where_it_came_from():
    """The prohibition, at the level of the type. Each of these is a different
    way of arriving at an unattributed number."""
    with pytest.raises(UnattributedFigure):
        Source(origin="metis", citation="", detail="x")
    with pytest.raises(UnattributedFigure):
        Source(origin="metis", citation="x", detail="   ")
    with pytest.raises(UnattributedFigure):
        Source(origin="folklore", citation="x", detail="y")  # type: ignore[arg-type]
    with pytest.raises(UnattributedFigure):
        Figure.derived_from("k", "l", "d", [], detail="derived from nothing at all")


def test_the_ledger_refuses_a_duplicate_key(picture):
    """Two figures under one key would make the page and its sidecar disagree
    about which one a reader is looking at."""
    ledger = FigureLedger()
    source = Source(origin="themis", citation="c", detail="d")
    ledger.emit("k", "l", "1", source)
    with pytest.raises(UnattributedFigure):
        ledger.emit("k", "l", "2", source)


# =========================================================================== #
# 2. ARGUS DID NOT ORIGINATE ANYTHING
# =========================================================================== #
def test_governed_figures_match_what_the_layers_independently_return(picture):
    """Re-drive the intake through the SDK and require the page's governed
    counts to equal what comes back. If the command centre had transcribed,
    rounded or adjusted any of them, this fails."""
    from argus.demo import walkthrough as demo

    client, recorded_at = demo._new_client()
    result = demo.WalkthroughResult()
    quiet = lambda *a, **k: None  # noqa: E731
    demo._step_1_pii(quiet, result, recorded_at)
    summary, raw_rows, _accepted = demo._step_2_intake(quiet, result, client, recorded_at)

    assert picture.figure("export_rows").display == str(len(raw_rows))
    assert picture.figure("requests_in_play").display == str(summary.accepted)
    assert picture.figure("quarantined").display == str(summary.quarantined)
    assert picture.figure("repair_records").display == str(len(summary.semantic_loss))
    assert summary.accepted + summary.quarantined == len(raw_rows)


def test_the_record_row_pairing_guard_actually_fires(picture):
    """CONSTRUCT THE VIOLATING CASE for the guard that attaches a trip
    reference to every figure about a trip.

    The pairing holds on this fixture, so deleting the check changes nothing and
    the mutation survived the first version of this suite. Here the violation is
    built: rows in a different order, and a row count that does not match. Both
    must raise rather than silently attributing V-118's figures to V-204.
    """
    from argus.command_centre import picture as module

    _rebuild_projection(picture)
    records = _PROJECTION_CACHE["records"]
    accepted = _PROJECTION_CACHE["accepted"]

    module._pair_records_to_rows(records, accepted)  # the honest case still passes

    shuffled = list(reversed(accepted))
    assert [r["VehicleNo"] for r in shuffled] != [r["VehicleNo"] for r in accepted]
    with pytest.raises(RuntimeError, match="pairing broke"):
        module._pair_records_to_rows(records, shuffled)

    with pytest.raises(RuntimeError, match="cannot attribute a figure"):
        module._pair_records_to_rows(records, accepted[:-1])


def test_the_binding_constraints_are_the_solvers_own_reason_codes(picture):
    """Every constraint named on the page must be a real `ReasonCode` value, or
    the checker's own no-schedule marker. Prose written by this layer would not
    be in the enum."""
    from themis.canonical import ReasonCode

    known = {code.value for code in ReasonCode} | {"NO_FEASIBLE_SCHEDULE", "—"}
    for option in picture.options:
        for token in option.binding.split(", "):
            assert token in known, f"{option.label}: {token!r} is not a reason code"


def test_no_forecast_is_shown_and_no_substitute_is_offered(picture, page):
    """The prohibition at its bluntest. The registry has no champion; the page
    must render that refusal and must not contain a demand number.

    Checked in the strong direction too: the module is required to carry no
    fallback estimate anywhere, so grep the emitted figure for anything that
    looks like a served forecast.
    """
    figure = picture.figure("forecast_available")
    assert "NONE" in figure.display
    assert not re.search(r"\d", figure.display), (
        f"the forecast box shows a number: {figure.display!r}"
    )
    assert any(r.key == "no_forecast" for r in picture.refusals)
    assert "no champion model promoted" in figure.source.detail


def test_the_forecast_refusal_is_metis_own_exception_not_a_guess():
    """Ask the runtime directly and require the same exception type. If the
    command centre had pre-empted the call with its own `if registry.empty`,
    this would still pass -- so the message is compared too."""
    from metis.forecast.runtime import ForecastRuntime, NoChampionError
    from themis.core import ModelRegistry
    from datetime import datetime, timezone

    runtime = ForecastRuntime(ModelRegistry(), artifact_resolver=lambda mv: None)
    now = datetime.now(timezone.utc)
    with pytest.raises(NoChampionError) as raised:
        runtime.forecast(
            "forecast.demand", {}, horizon_start=now, horizon_end=now, issued_at=now
        )
    assert "no champion model promoted" in str(raised.value)


def test_the_teardown_figures_are_the_teardown_s_own(picture):
    """The empty-time figures must reconcile the way the teardown says they do,
    recomputed here rather than read back from the same string."""
    unattributable = float(
        picture.figure("unattributable_minutes").display.replace(" min", "").replace(",", "")
    )
    total = float(
        picture.figure("deadhead_minutes").display.split(" min")[0].replace(",", "")
    )
    assert 0.0 < unattributable < total, (
        "the unattributable bucket is empty or swallowed the whole total; either way the "
        "refusal it demonstrates is not being demonstrated"
    )


# =========================================================================== #
# 3. THE DECLARED INPUTS ARE DISCLOSED, NOT BLENDED
# =========================================================================== #
def test_figures_resting_on_a_declared_assumption_say_so(picture):
    """These four all depend on values no layer produced. Each must carry the
    scenario attribution, which is what puts the purple tag on the page."""
    for key in (
        "wheelchair_requests",
        "accessible_vehicles",
        "wheelchair_positions_total",
        "reach_committed_fleet",
    ):
        assert picture.figure(key).source.origin == "scenario", (
            f"{key} is attributed to {picture.figure(key).source.origin}, hiding that it "
            "rests on a declared modelling input"
        )


def test_attribution_follows_the_weakest_input():
    """The direction that matters. A governed count mixed with a declared
    assumption must come out DECLARED, not governed."""
    governed = Source(origin="themis", citation="a", detail="d")
    declared = Source(origin="scenario", citation="b", detail="d")
    assert Figure.derived_from("k", "l", "1", [governed, declared], detail="d").source.origin == (
        "scenario"
    )
    assert Figure.derived_from("k", "l", "1", [declared, governed], detail="d").source.origin == (
        "scenario"
    )
    # And build metadata can never relabel a domain claim.
    build = Source(origin="argus", citation="c", detail="d")
    assert Figure.derived_from("k", "l", "1", [governed, build], detail="d").source.origin == (
        "themis"
    )


def test_every_declared_input_is_disclosed_on_the_page(picture, page):
    """It is not enough to tag them; the reader has to be able to see the whole
    set and what each one is."""
    assert len(picture.scenario_inputs) >= 8
    for declared in picture.scenario_inputs:
        assert declared.why.strip(), f"{declared.name} is disclosed without a reason"
        assert declared.name in page
        assert declared.value in page or declared.value.replace("%", "&#x25;") in page


# =========================================================================== #
# 4. THE REFUSALS ARE ON THE PAGE
# =========================================================================== #
def test_the_expected_refusals_are_all_present(picture):
    keys = {refusal.key for refusal in picture.refusals}
    assert {
        "pii",
        "ambiguous_date",
        "no_forecast",
        "interval_guarantee",
        "no_savings_envelope",
        "unattributable",
        "denial_reason",
    } <= keys, f"missing refusals: {keys}"


def test_the_interval_refusal_carries_the_monitors_own_words(picture):
    """The withdrawal text must be the monitor's, not a paraphrase written
    here. Paraphrasing a guarantee withdrawal is how a guarantee comes back."""
    refusal = next(r for r in picture.refusals if r.key == "interval_guarantee")
    assert "INTERVAL COVERAGE GUARANTEE NOT SUPPORTED" in refusal.refused
    assert "exchangeab" in refusal.refused.lower()
    assert picture.figure("drift_serving").display.startswith("drift /")
    assert "unsupported" in picture.figure("drift_serving").display


def test_the_drift_monitor_is_shown_answering_both_ways(picture):
    """A warning that is always on is not a test. The control window is
    exchangeable by construction and must come back clean."""
    assert "no_drift" in picture.figure("drift_control").display
    assert "unqualified" in picture.figure("drift_control").display


def test_every_refusal_is_rendered_with_its_source(picture, page):
    import html as html_module

    for refusal in picture.refusals:
        assert html_module.escape(refusal.headline, quote=True) in page
        assert html_module.escape(refusal.source.citation, quote=True) in page


# =========================================================================== #
# 5. THE ACCESSIBLE-CAPACITY LAYER IS NOT INERT
# =========================================================================== #
def test_the_equipment_constraint_can_actually_refuse_something(picture):
    """Metis's own vacuity guard, surfaced. False here would make every
    accessible-capacity statement on the page meaningless while still looking
    like a measurement."""
    assert picture.figure("equipment_layer_can_bind").display == "True"


def test_an_authority_actually_refuses_on_accessible_capacity(picture):
    """Not merely that the layer COULD bind -- that on this scenario something
    was refused because a wheelchair position was not available."""
    refused = [o for o in picture.options if "NO_ACCESSIBLE_CAPACITY" in o.binding]
    assert refused, (
        "no candidate placement was refused on accessible capacity, so the page's claim "
        "that accessible capacity is the binding resource is not demonstrated by it"
    )


def test_the_equipment_refusal_count_names_the_right_checker(picture):
    """The count on the page must be refusals by the EQUIPMENT checker, not by
    any checker.

    Recomputed here from the certification outcomes rather than read back, so
    widening the predicate to `if outcome.rejected_by` -- which would credit the
    equipment layer with the routing checker's work and make an inert layer look
    busy -- fails rather than passing quietly.
    """
    from metis.decide.compatibility import certify_insertion

    from argus.command_centre import picture as module

    projection = _rebuild_projection(picture)
    expected = 0
    for vehicle in range(projection.instance.num_vehicles):
        outcome = certify_insertion(
            projection.instance,
            projection.profile,
            vehicle,
            projection.routes[vehicle],
            projection.late_request,
        )
        if module.EQUIPMENT_CHECKER in outcome.rejected_by:
            expected += 1
    shown = int(picture.figure("equipment_checker_refusals").display.split(" of ")[0])
    assert shown == expected, (
        f"the page credits the equipment checker with {shown} refusal(s); it made {expected}"
    )


def test_the_equipment_checker_can_refuse_on_this_pages_own_instance(picture):
    """CONSTRUCT THE VIOLATING CASE, on the projection the page is built from.

    `can_bind` is a statement about the configuration and the page's own
    equipment-refusal count is currently zero, so neither shows the equipment
    layer doing work. This asks the checker directly: a rider who needs a
    wheelchair-accessible vehicle, offered to a vehicle that has no position,
    must be refused with `NO_ACCESSIBLE_CAPACITY`.

    Written this way because making every vehicle accessible -- a one-character
    change to a declared input -- leaves `can_bind` true and every other
    accessible-capacity assertion on this page green. That mutation survived the
    first version of this suite.
    """
    from metis.decide.compatibility import certify_insertion

    from argus.command_centre import picture as module

    projection = _rebuild_projection(picture)
    profile, instance = projection.profile, projection.instance
    inaccessible = [
        v for v in range(instance.num_vehicles) if not profile.is_accessible(v)
    ]
    assert inaccessible, (
        "every vehicle in the projection is wheelchair-accessible, so the equipment "
        "constraint cannot refuse anything and every accessible-capacity figure on the "
        "page is describing a fleet with no scarcity in it"
    )
    wheelchair = sorted(profile.wheelchair_requests)
    assert wheelchair, "no request is labelled as needing a wheelchair-accessible vehicle"

    vehicle = inaccessible[0]
    on_board = {
        instance.request_of(node)
        for node in projection.routes[vehicle]
        if instance.is_pickup(node)
    }
    candidate = next(r for r in wheelchair if r not in on_board)
    outcome = certify_insertion(
        instance, profile, vehicle, projection.routes[vehicle], candidate
    )
    assert not outcome.certified
    assert module.EQUIPMENT_CHECKER in outcome.rejected_by, (
        f"the routing checker alone refused request {candidate}; the equipment layer "
        f"never got to speak ({outcome.rejected_by})"
    )
    assert "NO_ACCESSIBLE_CAPACITY" in {v.code.value for v in outcome.violations}


def test_accessible_foreclosure_travels_with_the_total_everywhere(picture):
    """An aggregate that hides a disabled rider losing their trip is the failure
    mode ADR-0073 exists to prevent."""
    for row in picture.capacity_rows:
        assert "accessible_trips_foreclosed" in row
        assert "accessible_stderr" in row
    for key in ("reach_empty_fleet", "reach_committed_fleet", "day_foreclosure"):
        figure = picture.figure(key)
        assert isinstance(figure.value, list) and len(figure.value) == 2, (
            f"{key} carries an aggregate with no cohort figure beside it"
        )
        assert "wheelchair" in figure.display or "accessible" in figure.display, (
            f"{key} renders the total without naming the cohort: {figure.display!r}"
        )


def test_the_foreclosure_estimate_carries_its_own_error_bar(picture):
    """A foreclosure difference smaller than its standard error is not a
    finding. The page must show the error bar and must state whether the
    estimate clears it."""
    counterfactual = [r for r in picture.capacity_rows if "COUNTERFACTUAL" in r["kind"]]
    assert counterfactual, "no counterfactual placement was priced"
    row = counterfactual[0]
    assert row["stderr"] >= 0.0
    assert row["distinguishable_from_zero"] == (abs(row["trips_foreclosed"]) > row["stderr"])
    assert picture.figure("counterfactual_foreclosure").display.count("±") == 2


def test_the_incremental_marginal_equals_the_definition_it_shortcuts(picture):
    """The one arithmetic shortcut this package takes, pinned rather than argued.

    The per-vehicle rows are computed as `-value_of_replacement(committed, v,
    empty)` because it reuses the snapshot's reach matrix. That must equal
    `value_of(v emptied, committed)`, the definitional form, per draw. A
    shortcut that silently disagreed with what it shortcuts would be worse than
    no shortcut.
    """
    from metis.decide.capacity_value import build_ensemble, prior_from_observed
    from argus.command_centre import picture as module

    proj = _rebuild_projection(picture)
    instance, profile = proj.instance, proj.profile
    observed = [r for r in range(1, instance.num_requests + 1) if r != proj.late_request]
    ensemble = build_ensemble(
        instance,
        profile,
        prior_from_observed(instance, profile, observed),
        draws=CAPACITY_DRAWS,
        scenarios=CAPACITY_SCENARIOS,
        seed=module.CAPACITY_SEED,
    )
    committed = ensemble.snapshot(proj.routes)
    empty_route = [instance.depot_start, instance.depot_end]
    by_label = {
        row["label"]: row
        for row in picture.capacity_rows
        if "committed block" in row["kind"]
    }
    checked = 0
    for vehicle in range(instance.num_vehicles):
        if len(proj.routes[vehicle]) <= 2:
            continue
        without = [list(seq) for seq in proj.routes]
        without[vehicle] = list(empty_route)
        definitional = ensemble.value_of(without, proj.routes)
        shortcut = ensemble.value_of_replacement(committed, vehicle, empty_route)
        assert definitional.trips_foreclosed == pytest.approx(-shortcut.trips_foreclosed)
        assert definitional.accessible_trips_foreclosed == pytest.approx(
            -shortcut.accessible_trips_foreclosed
        )
        assert definitional.stderr == pytest.approx(shortcut.stderr)

        # And the ROW THE PAGE SHOWS must equal the definitional value, so a
        # dropped or flipped sign in the generator fails here rather than
        # shipping a released-capacity figure labelled as a cost.
        row = by_label[proj.vehicle_labels[vehicle]]
        assert row["trips_foreclosed"] == pytest.approx(
            round(definitional.trips_foreclosed, 3) or 0.0
        )
        assert row["accessible_trips_foreclosed"] == pytest.approx(
            round(definitional.accessible_trips_foreclosed, 3) or 0.0
        )
        checked += 1
    assert checked >= 2, "too few loaded vehicles to make this comparison mean anything"


def test_the_marginal_cost_reads_a_release_as_a_cost():
    """CONSTRUCT THE VIOLATING CASE for the one sign flip in this package.

    Every committed block on this scenario forecloses exactly zero, so a
    dropped negation is invisible in the artifact -- that mutation survived the
    first version of this suite, for the usual reason: the fixture never reached
    the case. So the function is called directly with a non-zero value.

    `value_of_replacement(committed, v, empty)` returns a NEGATIVE foreclosure
    when emptying a vehicle releases capacity, and the page's column is a cost,
    so the sign must flip. It must also not emit negative zero.
    """
    from argus.command_centre.picture import marginal_cost_of_a_block
    from metis.decide.capacity_value import CapacityValue

    def value(total: float, accessible: float) -> CapacityValue:
        return CapacityValue(
            draws=4,
            scenarios_per_draw=16,
            accessible_scenarios_per_draw=5.0,
            reach_before=10.0,
            reach_after=10.0 - total,
            accessible_reach_before=5.0,
            accessible_reach_after=5.0 - accessible,
            trips_foreclosed=total,
            accessible_trips_foreclosed=accessible,
            stderr=0.5,
            accessible_stderr=0.25,
            per_draw=(),
        )

    assert marginal_cost_of_a_block(value(-2.0, -1.5)) == (2.0, 1.5)
    assert marginal_cost_of_a_block(value(3.0, 1.0)) == (-3.0, -1.0)
    total, accessible = marginal_cost_of_a_block(value(0.0, 0.0))
    assert (total, accessible) == (0.0, 0.0)
    assert not str(total).startswith("-"), "the page would render negative zero"
    assert not str(accessible).startswith("-")


# =========================================================================== #
# 6. THE PAGE IS SELF-CONTAINED AND SAYS WHAT IT IS
# =========================================================================== #
def test_the_page_reaches_no_network_and_runs_no_script(page):
    """It must open from disk with the cable pulled."""
    for forbidden in ("<script", "<link", "<img", "@import", "url(", "http://", "https://"):
        assert forbidden not in page, f"the page contains {forbidden!r}"


def test_the_page_declares_its_encoding_and_a_viewport(page):
    """A file opened from disk with no charset lets the browser guess, and every
    plus-minus sign on the page is a candidate for mojibake."""
    assert page.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in page
    assert 'name="viewport"' in page
    assert page.rstrip().endswith("</html>")


def test_the_status_is_on_the_page_not_in_a_readme(page):
    """Nothing here is Validated, the scenario is synthetic, and a viewer must
    be told both without leaving the page."""
    assert "SYNTHETIC SCENARIO" in page
    assert "zero customers" in page
    assert "Demonstrated. Not Validated." in page
    assert "Argus must never invent a fact" in page
    for banned in ("validated capability", "proven saving", "guaranteed saving"):
        assert banned.lower() not in page.lower()


def test_the_page_never_claims_a_guaranteed_saving(picture, page):
    """The teardown refuses to, and the page must not undo that in prose."""
    assert "is_guaranteed_saving=False" in " ".join(r.why for r in picture.refusals)
    assert "not a saving" in page.lower() or "NOT a saving" in page


def test_no_real_agency_name_appears_on_the_page(page):
    """The repository's NTD corpus carries hundreds of real agency names. Not one
    of them is a Milexium customer, so not one of them may appear on an operating
    picture that a viewer could read as a deployment.

    The name list is read from the committed corpus rather than typed here, so it
    covers every agency the repository knows about rather than the three someone
    thought of.
    """
    import csv
    from pathlib import Path

    corpus = Path(__file__).resolve().parents[3] / "forge" / "business" / "ntd" / "agency_economics.csv"
    if not corpus.exists():  # pragma: no cover -- committed input
        pytest.skip("NTD agency corpus not present")
    with corpus.open(newline="", encoding="utf-8") as handle:
        names = [
            row["agency"].strip()
            for row in csv.DictReader(handle)
            if row.get("agency") and len(row["agency"].strip()) > 6
        ]
    assert len(names) > 50, "the agency-name list is too short to be a real check"
    present = sorted({name for name in names if name in page})
    assert not present, f"real agency names on the page: {present[:5]}"


def test_the_page_claims_no_deployment(page):
    """`customer` may appear only in the disclaimer that there are none."""
    lowered = page.lower()
    for match in re.finditer(r"customer", lowered):
        window = lowered[max(0, match.start() - 12) : match.end() + 2]
        assert "no customer" in window or "zero customer" in window, (
            f"the page mentions customers outside the disclaimer: ...{window}..."
        )


def test_the_artifact_writes_both_files_and_they_agree(picture, tmp_path):
    """The sidecar is what a third party checks the page against, so the two
    must not be able to drift."""
    page_path, sidecar_path = write_artifact(picture, tmp_path)
    assert page_path.exists() and sidecar_path.exists()
    record = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert record["status"].startswith("Demonstrated")
    assert record["prohibition"] == ARGUS_PROHIBITION
    assert record["synthetic_banner"] == SYNTHETIC_BANNER
    assert len(record["figures"]) == len(picture.ledger)
    rendered = page_path.read_text(encoding="utf-8")
    for entry in record["figures"]:
        assert entry["source"]["citation"], f"{entry['key']} has no citation in the sidecar"
    assert rendered == render_html(picture)


def test_the_page_is_built_in_a_workable_time(picture):
    """Indicative, not a specification -- ADR-0056 recorded a 2.8x thermal swing
    on this machine and ADR-0061 saw 4.2x between two runs. The bound is loose
    enough to survive that and tight enough to catch an accidental full
    re-computation of something expensive.
    """
    assert picture.runtime_seconds < 60.0, (
        f"the page took {picture.runtime_seconds:.1f}s; it is meant to be a build step, "
        "not a batch job"
    )


def test_skipping_the_drift_section_removes_it_rather_than_faking_it():
    """The one runtime lever, checked in the direction that matters: the cheap
    build must be MISSING the section and must say so, never substituting a
    cached or plausible verdict."""
    cheap = build_operating_picture(include_real_drift=False)
    assert not cheap.has("drift_serving")
    assert not cheap.drift_features
    assert not any(r.key == "interval_guarantee" for r in cheap.refusals)
    assert any("no measured evidence" in limitation for limitation in cheap.limitations)
    rendered = render_html(cheap)
    assert "Uncertainty, and what would invalidate this" not in rendered
    assert "unsupported" not in rendered
