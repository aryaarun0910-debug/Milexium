"""Program I depth: a deadhead teardown carried in an evidence pack, and
independently RE-DERIVED from it.

ADR-0039's teardown is the artifact a design partner is handed -- a specific,
checkable finding about their own operation. ADR-0017's pack is what a third
party re-verifies without Milexium. These tests prove the join is real:

- the pack carries the teardown's manifest, method, figures AND the segments
  those figures must follow from;
- `verify_evidence_pack` RECOMPUTES the headline figures from those segments
  and the manifest's declared inputs -- the load-bearing tamper tests alter a
  figure, re-anchor the bundle checksum so the outer hash is happy, and prove
  re-verification still FAILS;
- re-derivation is structurally non-circular: the module that recomputes
  imports nothing from `app.replay`, so it cannot be satisfied by the
  generator agreeing with itself;
- redaction is honest: no run identifier survives it, the figures that remain
  checkable are still checked, and the check that becomes impossible is
  reported as not-checked rather than as passed.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.canonical import DecisionEventType, SqliteCanonicalStore
from app.evidence import (
    EvidencePack,
    TeardownCaptureError,
    build_evidence_pack,
    capture_teardown,
    redact_pack,
    rederive_teardown,
    verify_evidence_pack,
)
from app.evidence.export import _bundle_hash
from app.evidence.teardown_evidence import (
    REDACTED_RUN_REF,
    TeardownEvidence,
    TeardownFigures,
    rederive_segment_fingerprint,
)
from app.replay import CostBasis, VehicleSegment, teardown_deadhead

from conformance.fixtures.builders import example_tenant

# A fixed real-calendar anchor: Monday 2026-07-20, so weekday() is unambiguous.
MONDAY = datetime(2026, 7, 20, tzinfo=timezone.utc)

RUN_A = "RUN-A"
RUN_B = "RUN-B"


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def seg(
    *,
    day: int = 0,
    hour: int = 9,
    minute: int = 0,
    minutes: float = 30.0,
    kind: str = "deadhead",
    run: str | None = RUN_A,
) -> VehicleSegment:
    start = MONDAY + timedelta(days=day, hours=hour, minutes=minute)
    return VehicleSegment(
        started_at=start, ended_at=start + timedelta(minutes=minutes), kind=kind, run_ref=run
    )


def _segments() -> tuple[VehicleSegment, ...]:
    """A small week with: an hour-straddling segment (09:50-10:20), two runs,
    a second day, and one segment the export never identified a run for."""
    return (
        seg(day=0, hour=9, minute=50, minutes=30.0, kind="deadhead", run=RUN_A),
        seg(day=0, hour=6, minutes=120.0, kind="revenue", run=RUN_A),
        seg(day=0, hour=22, minutes=45.0, kind="deadhead", run=RUN_B),
        seg(day=0, hour=12, minutes=200.0, kind="revenue", run=RUN_B),
        seg(day=2, hour=4, minutes=20.0, kind="deadhead", run=RUN_B),
        seg(day=2, hour=5, minutes=15.0, kind="deadhead", run=None),
        seg(day=2, hour=7, minutes=90.0, kind="revenue", run=None),
    )


def _cost_basis(**overrides) -> CostBasis:
    kwargs = dict(
        cost_per_vehicle_hour=76.885,
        currency="USD",
        source="2024 NTD demand-response filings, national median cost_per_vrh (stand-in)",
        avoidable_share_low=0.2,
        avoidable_share_high=0.45,
    )
    kwargs.update(overrides)
    return CostBasis(**kwargs)


def _teardown_evidence(*, cost: CostBasis | None = None, provenance: str = "real_public"):
    segments = _segments()
    torn = teardown_deadhead(
        segments,
        dataset_label="fixture-week",
        data_provenance=provenance,
        run_ref_source="run_ref (fixture)",
        cost_basis=_cost_basis() if cost is None else cost,
    )
    return torn, capture_teardown(torn, segments)


def _seeded_chain() -> tuple[SqliteCanonicalStore, str, str]:
    store = SqliteCanonicalStore()
    tenant = example_tenant()
    store.create_tenant(tenant)
    aggregate_id = "req-teardown-0001"
    store.append_event(
        tenant_id=tenant.tenant_id,
        aggregate_id=aggregate_id,
        aggregate_type="ServiceRequest",
        occurred_at=_utc(2026, 7, 24, 8, 0),
        actor_type="system",
        actor_id="scheduler",
        event_type=DecisionEventType.RECOMMENDATION,
        payload={"assignment": "vehicle-7", "rider_note": "prefers front seat"},
    )
    return store, tenant.tenant_id, aggregate_id


def _pack(**kwargs) -> EvidencePack:
    store, tenant_id, aggregate_id = _seeded_chain()
    events = store.history(tenant_id, aggregate_id)
    raw = store.raw_rows_for_tenant(tenant_id)
    return build_evidence_pack(events, raw, **kwargs)


def _packed(**kwargs) -> EvidencePack:
    _, evidence = _teardown_evidence(**kwargs)
    return _pack(teardown=evidence)


def _reanchor(pack: EvidencePack) -> EvidencePack:
    """Recompute the bundle checksum over tampered content -- i.e. play the
    attacker who fixes the outer hash so only the re-derivation can catch them."""
    teardown_dump = pack.teardown.model_dump(mode="json") if pack.teardown else None
    manifest = pack.manifest.model_copy(
        update={
            "bundle_sha256": _bundle_hash(
                pack.evidence, pack.raw_events, pack.outcome, teardown_dump
            )
        }
    )
    return pack.model_copy(update={"manifest": manifest})


def _with_figures(pack: EvidencePack, **figure_overrides) -> EvidencePack:
    figures = pack.teardown.figures.model_copy(update=figure_overrides)
    return pack.model_copy(update={"teardown": pack.teardown.model_copy(update={"figures": figures})})


# --------------------------------------------------------------------------
# The pack carries the teardown
# --------------------------------------------------------------------------


def test_pack_carries_the_manifest_method_and_the_segments_the_figures_follow_from() -> None:
    torn, evidence = _teardown_evidence()
    pack = _pack(teardown=evidence)

    assert pack.manifest.teardown_included
    assert pack.manifest.teardown_id == torn.manifest.teardown_id
    assert pack.manifest.teardown_segment_count == len(_segments())

    manifest = pack.teardown.manifest
    assert manifest["segment_sha256"] == torn.manifest.segment_sha256
    # every input recorded as (name, value, source), and the numbered method
    assert {record["name"] for record in manifest["inputs"]} >= {
        "segment_count",
        "reduction_fraction",
        "cost_per_vehicle_hour",
        "avoidable_share_of_cost_per_hour",
    }
    assert all({"name", "value", "source"} <= set(record) for record in manifest["inputs"])
    assert [step["step"][:1] for step in manifest["method"]] == ["1", "2", "3", "4", "5"]
    # the inputs the figures must be recomputed from are actually embedded
    assert len(pack.teardown.segments) == len(_segments())


def test_pack_round_trips_through_json_and_the_teardown_still_rederives() -> None:
    pack = _packed()

    restored = EvidencePack.from_json(pack.to_json())
    result = verify_evidence_pack(restored)

    assert result.reverified
    assert result.teardown_present
    assert result.teardown_figures_rederived is True
    assert result.teardown_fingerprint_rederived is True
    assert result.teardown_mismatches == ()
    assert result.bundle_hash_matches and result.chain_reverified


def test_a_pack_without_a_teardown_is_unchanged_and_reports_no_teardown() -> None:
    """The capability must not alter the ADR-0017 pack that does not use it --
    including its checksum, which is a published artifact."""
    plain = _pack()
    result = verify_evidence_pack(plain)

    assert plain.teardown is None
    assert not plain.manifest.teardown_included
    assert plain.manifest.bundle_sha256 == _bundle_hash(
        plain.evidence, plain.raw_events, plain.outcome
    )
    assert result.reverified
    assert result.teardown_present is False
    assert result.teardown_figures_rederived is None


# --------------------------------------------------------------------------
# Re-derivation is real -- and structurally non-circular
# --------------------------------------------------------------------------


def test_rederivation_recomputes_the_headline_figures_from_the_segments() -> None:
    """The re-derived figures must match arithmetic done by hand here, not just
    match the pack: 30 + 45 + 20 + 15 = 110 empty minutes, 410 earning."""
    pack = _packed()
    figures = pack.teardown.figures

    # figures are emitted rounded to 6 decimal places, hence the absolute bound
    assert figures.total_deadhead_minutes == pytest.approx(110.0, abs=1e-6)
    assert figures.total_revenue_minutes == pytest.approx(410.0, abs=1e-6)
    assert figures.deadhead_share_of_vehicle_time == pytest.approx(110.0 / 520.0, abs=1e-6)
    assert figures.value_at_full_cost == pytest.approx((110.0 / 60.0) * 76.885, abs=1e-6)
    assert figures.modelled_envelope_low == pytest.approx(
        (110.0 / 60.0) * 76.885 * 0.10 * 0.2, abs=1e-6
    )
    assert figures.modelled_envelope_high == pytest.approx(
        (110.0 / 60.0) * 76.885 * 0.10 * 0.45, abs=1e-6
    )

    result = rederive_teardown(pack.teardown)
    assert result.figures_rederived
    # the money figures are re-derived from the DECLARED rate, not read back
    assert "value_at_full_cost" in result.checked
    assert "modelled_envelope_high" in result.checked
    assert "total_deadhead_minutes" in result.checked


def test_rederivation_never_imports_the_generator() -> None:
    """A verifier that called teardown_deadhead again would only prove the
    generator agrees with itself. The re-derivation module is generator-free by
    construction, and this is the test that keeps it that way -- checked against
    the module's actual import statements, not its prose."""
    imported = _imports_of("app", "evidence", "teardown_evidence.py")

    assert imported, "no imports found -- the parse, not the module, is broken"
    assert not [name for name in imported if name.startswith("app.replay")]
    # and the pack itself stays clean: export.py reaches the generator through
    # nothing at all.
    assert not [
        name
        for name in _imports_of("app", "evidence", "export.py")
        if name.startswith("app.replay")
    ]


def _imports_of(*parts: str) -> list[str]:
    tree = ast.parse(Path(Path(__file__).parents[3], *parts).read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_hour_straddling_minutes_are_rederived_into_the_hours_they_happened_in() -> None:
    """Method step 2 is re-implemented by the verifier, not trusted: the
    09:50-10:20 segment must re-derive as 10 minutes in hour 09 and 20 in 10."""
    pack = _packed()
    by_hour = {b.hour_of_day: b for b in pack.teardown.by_hour_of_day}

    assert by_hour[9].deadhead_minutes == pytest.approx(10.0)
    assert by_hour[10].deadhead_minutes == pytest.approx(20.0)

    # move a minute from one hour to the other: still sums to 110, still caught
    tampered_buckets = tuple(
        b.model_copy(update={"deadhead_minutes": b.deadhead_minutes + 1.0})
        if b.hour_of_day == 9
        else b.model_copy(update={"deadhead_minutes": b.deadhead_minutes - 1.0})
        if b.hour_of_day == 10
        else b
        for b in pack.teardown.by_hour_of_day
    )
    tampered = _reanchor(
        pack.model_copy(
            update={"teardown": pack.teardown.model_copy(update={"by_hour_of_day": tampered_buckets})}
        )
    )

    result = verify_evidence_pack(tampered)
    assert result.bundle_hash_matches
    assert result.teardown_figures_rederived is False
    assert not result.reverified


def test_top_runs_are_rederived_from_the_segments_and_unattributable_is_not_folded_in() -> None:
    pack = _packed()
    ranked = {row.run_ref: row for row in pack.teardown.top_runs}

    assert ranked[RUN_B].deadhead_minutes == pytest.approx(65.0)
    assert ranked[RUN_A].deadhead_minutes == pytest.approx(30.0)
    assert pack.teardown.unattributable is not None
    assert pack.teardown.unattributable.run_ref is None
    assert pack.teardown.unattributable.attributable is False
    assert pack.teardown.unattributable.deadhead_minutes == pytest.approx(15.0)

    assert verify_evidence_pack(pack).teardown_figures_rederived is True


# --------------------------------------------------------------------------
# TAMPER: the load-bearing tests
# --------------------------------------------------------------------------


def test_tampering_with_a_headline_figure_fails_verification() -> None:
    """THE load-bearing test. An operator-flattering edit to the money figure,
    with the bundle checksum re-anchored so the outer hash is happy again, is
    still caught -- because verification recomputes the figure from the
    embedded segments and the declared rate instead of reading it back."""
    pack = _packed()
    honest = pack.teardown.figures.value_at_full_cost

    tampered = _reanchor(_with_figures(pack, value_at_full_cost=honest * 3.0))
    result = verify_evidence_pack(tampered)

    assert result.bundle_hash_matches          # the attacker fixed the outer checksum...
    assert result.teardown_figures_rederived is False   # ...but the figure does not follow from the data
    assert not result.reverified
    assert any("value_at_full_cost" in m for m in result.teardown_mismatches)
    assert any("teardown:" in reason for reason in result.reasons)


def test_tampering_with_the_empty_minutes_fails_verification() -> None:
    pack = _packed()
    tampered = _reanchor(_with_figures(pack, total_deadhead_minutes=110.0 * 2))

    result = verify_evidence_pack(tampered)
    assert result.bundle_hash_matches
    assert result.teardown_figures_rederived is False
    assert any("total_deadhead_minutes" in m for m in result.teardown_mismatches)


def test_tampering_with_a_figure_without_reanchoring_is_caught_by_the_checksum_too() -> None:
    """Both nets, independently: the outer checksum catches any byte change,
    the re-derivation catches changes that survive re-anchoring."""
    pack = _packed()
    tampered = _with_figures(pack, total_deadhead_minutes=1.0)

    result = verify_evidence_pack(tampered)
    assert not result.bundle_hash_matches
    assert result.teardown_figures_rederived is False
    assert not result.reverified


def test_swapping_in_a_flattering_segment_set_is_caught_by_the_fingerprint() -> None:
    """Making the data agree with a tampered figure does not work either: the
    manifest's segment_sha256 no longer covers the substituted segments."""
    pack = _packed()
    fewer = pack.teardown.segments[:-2]
    swapped = pack.teardown.model_copy(update={"segments": fewer})
    tampered = _reanchor(pack.model_copy(update={"teardown": swapped}))

    result = verify_evidence_pack(tampered)
    assert result.bundle_hash_matches
    assert result.teardown_fingerprint_rederived is False
    assert not result.reverified
    assert any("segment_sha256" in m for m in result.teardown_mismatches)


def test_the_money_figure_is_recomputed_from_the_declared_rate_not_read_back() -> None:
    """Proof the derivation runs inputs -> figures. Change only the manifest's
    DECLARED cost per vehicle-hour and leave the money figure alone: a verifier
    that re-read the recorded number would still pass, and this one does not."""
    pack = _packed()
    inputs = [
        {**record, "value": "1000.0 USD"} if record["name"] == "cost_per_vehicle_hour" else record
        for record in pack.teardown.manifest["inputs"]
    ]
    manifest = {**pack.teardown.manifest, "inputs": inputs}
    tampered = _reanchor(
        pack.model_copy(update={"teardown": pack.teardown.model_copy(update={"manifest": manifest})})
    )

    result = verify_evidence_pack(tampered)
    assert result.bundle_hash_matches
    assert result.teardown_figures_rederived is False
    assert any("value_at_full_cost" in m for m in result.teardown_mismatches)


def test_a_manifest_that_misdescribes_its_own_teardown_fails() -> None:
    pack = _packed()
    lying = pack.manifest.model_copy(update={"teardown_data_provenance": "synthetic"})
    tampered = _reanchor(pack.model_copy(update={"manifest": lying}))

    result = verify_evidence_pack(tampered)
    assert not result.reverified
    assert any("provenance" in m for m in result.teardown_mismatches)


def test_capture_refuses_segments_that_are_not_the_ones_the_teardown_ran_on() -> None:
    torn, _ = _teardown_evidence()
    with pytest.raises(TeardownCaptureError, match="fingerprint mismatch|not the segments"):
        capture_teardown(torn, _segments()[:-1])


# --------------------------------------------------------------------------
# The hedging and the provenance survive into the pack
# --------------------------------------------------------------------------


def test_the_hedge_and_the_modelled_not_causal_framing_are_carried_verbatim() -> None:
    from app.replay import (
        DEADHEAD_TEARDOWN_NOTE,
        FIXED_COST_HEDGE,
        MODELLED_COMPARISON_NOTE,
    )

    pack = _packed()

    assert pack.teardown.figures.hedge == FIXED_COST_HEDGE
    assert pack.teardown.interpretation == DEADHEAD_TEARDOWN_NOTE
    assert pack.teardown.manifest["note"] == DEADHEAD_TEARDOWN_NOTE
    assert pack.teardown.manifest["replay_discipline_note"] == MODELLED_COMPARISON_NOTE
    assert pack.teardown.is_modelled and pack.teardown.causal_proof is False


def test_no_pack_field_may_present_the_envelope_as_a_guaranteed_saving() -> None:
    pack = _packed()
    figures = pack.teardown.figures

    assert figures.is_guaranteed_saving is False
    with pytest.raises(ValueError, match="guaranteed or realised saving"):
        TeardownFigures.model_validate({**figures.model_dump(), "is_guaranteed_saving": True})
    with pytest.raises(ValueError, match="causal proof"):
        TeardownEvidence.model_validate(
            {**pack.teardown.model_dump(mode="json"), "causal_proof": True}
        )

    # every mention of a saving in the pack's own prose is a denial of one --
    # checked by requiring the negation, not merely the absence of the word
    prose = " ".join(
        [
            pack.manifest.note,
            pack.teardown.note,
            pack.teardown.interpretation,
            figures.hedge or "",
            figures.envelope_basis or "",
        ]
    ).lower()
    assert "never a guaranteed or realised saving" in prose
    assert "not guaranteed cash" in prose
    assert "not a saving" in prose
    for sentence in prose.replace("--", " ").split("."):
        if "saving" in sentence:
            assert any(word in sentence for word in ("not", "never", "no ")), sentence


def test_provenance_survives_and_there_is_no_operator_value() -> None:
    pack = _packed()
    assert pack.manifest.teardown_data_provenance == "real_public"
    assert pack.teardown.data_provenance == "real_public"
    assert pack.teardown.manifest["data_provenance"] == "real_public"
    assert "real_public" in pack.to_json()

    with pytest.raises(ValueError, match="no 'operator' provenance"):
        TeardownEvidence.model_validate(
            {**pack.teardown.model_dump(mode="json"), "data_provenance": "operator"}
        )


def test_without_the_operators_split_no_envelope_is_packed_or_invented() -> None:
    _, evidence = _teardown_evidence(
        cost=_cost_basis(avoidable_share_low=None, avoidable_share_high=None)
    )
    pack = _pack(teardown=evidence)
    figures = pack.teardown.figures

    assert figures.value_at_full_cost is not None      # the accounting value stands
    assert figures.modelled_envelope_low is None       # the recoverable fraction does not
    assert figures.modelled_envelope_high is None
    assert "is not guessed" in (figures.envelope_basis or "")
    assert verify_evidence_pack(pack).reverified


def test_claiming_an_envelope_with_no_declared_split_fails_rederivation() -> None:
    """The refusal is enforced by the verifier too: a pack cannot acquire an
    envelope the manifest declares no inputs for."""
    _, evidence = _teardown_evidence(
        cost=_cost_basis(avoidable_share_low=None, avoidable_share_high=None)
    )
    pack = _pack(teardown=evidence)
    tampered = _reanchor(_with_figures(pack, modelled_envelope_low=1.0, modelled_envelope_high=2.0))

    result = verify_evidence_pack(tampered)
    assert result.teardown_figures_rederived is False
    assert any("envelope" in m for m in result.teardown_mismatches)


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------


def test_redaction_leaks_no_run_identifier_anywhere_in_the_pack() -> None:
    pack = _packed()
    assert RUN_A in pack.to_json() and RUN_B in pack.to_json()  # present before

    redacted = redact_pack(pack, sensitive_payload_keys=("rider_note",))
    text = redacted.to_json()

    assert RUN_A not in text
    assert RUN_B not in text
    assert REDACTED_RUN_REF in text
    assert all(row.run_ref in (None, REDACTED_RUN_REF) for row in redacted.teardown.segments)
    assert all(row.run_ref == REDACTED_RUN_REF for row in redacted.teardown.top_runs)
    assert "teardown.segments[].run_ref" in redacted.manifest.redacted_fields


def test_redaction_keeps_an_unidentified_run_unidentified_rather_than_masked() -> None:
    """`None` means "the export never said"; overwriting it with a mask would
    make the redaction a false statement about the source data."""
    redacted = redact_pack(_packed(), sensitive_payload_keys=())

    assert redacted.teardown.unattributable.run_ref is None
    assert redacted.teardown.unattributable.attributable is False
    assert sum(1 for row in redacted.teardown.segments if row.run_ref is None) == 2


def test_a_redacted_pack_is_still_figure_verifiable_and_says_what_it_cannot_prove() -> None:
    pack = _packed()
    redacted = redact_pack(pack, sensitive_payload_keys=("rider_note",))
    result = verify_evidence_pack(redacted)

    # the minute/money figures never depended on run identity, so they are still checked
    assert result.teardown_figures_rederived is True
    # ...but the binding to the original segment set is gone, and is reported as
    # not-checked -- neither silently passed nor mislabelled as a failure
    assert result.teardown_fingerprint_rederived is None
    assert any("segment fingerprint not re-checkable" in r for r in result.reasons)
    assert any("run attribution not re-checked" in r for r in result.reasons)

    # the pack as a whole still refuses to claim independent verifiability
    assert not result.reverified
    assert not redacted.manifest.independently_verifiable
    assert "REMAIN re-derivable" in redacted.manifest.note
    assert "not built in ADR-0017" in redacted.teardown.note


def test_a_redacted_pack_still_fails_on_a_tampered_figure() -> None:
    """Redaction must not become a laundering path: the checks that survive it
    still bite."""
    redacted = redact_pack(_packed(), sensitive_payload_keys=("rider_note",))
    tampered = _reanchor(_with_figures(redacted, total_deadhead_minutes=9999.0))

    result = verify_evidence_pack(tampered)
    assert result.bundle_hash_matches
    assert result.teardown_figures_rederived is False
    assert any("total_deadhead_minutes" in m for m in result.teardown_mismatches)


def test_redacting_a_pack_without_a_teardown_is_unchanged() -> None:
    redacted = redact_pack(_pack(), sensitive_payload_keys=("rider_note",))

    assert redacted.teardown is None
    assert redacted.manifest.redacted_fields == ("rider_note",)


# --------------------------------------------------------------------------
# Privacy boundary
# --------------------------------------------------------------------------


def test_a_packed_segment_carries_trip_structure_and_nothing_else() -> None:
    """A rider identifier cannot reach a pack because a packed segment has
    exactly four structural fields and forbids extras -- the same boundary
    ADR-0039 enforces at the input end, enforced again at the export end."""
    pack = _packed()
    row = pack.teardown.segments[0]

    assert set(row.model_dump()) == {"started_at", "ended_at", "kind", "run_ref"}
    with pytest.raises(ValueError):
        row.model_validate({**row.model_dump(), "rider_id": "R-1"})

    for embedded in json.loads(pack.to_json())["teardown"]["segments"]:
        assert set(embedded) == {"started_at", "ended_at", "kind", "run_ref"}


def test_the_embedded_segments_are_the_fingerprinted_ones() -> None:
    """The pack's own binding: what is embedded is what the manifest pinned."""
    torn, evidence = _teardown_evidence()
    assert rederive_segment_fingerprint(evidence.segments) == torn.manifest.segment_sha256
