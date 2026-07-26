"""Program I extension conformance: period, incident, and procurement bundles.

Period and incident bundles compose many single-aggregate EvidencePacks. The
load-bearing property is unchanged from ADR-0017: every embedded pack stays
independently re-verifiable, and each bundle adds only an outer checksum a third
party can recompute. The procurement bundle is a scaffold that must honestly
separate what this repository substantiates from what needs external input --
and must make no compliance claim.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.canonical import DecisionEventType, SqliteCanonicalStore
from app.evidence import (
    AggregateHistory,
    build_incident_pack,
    build_period_pack,
    build_procurement_bundle,
    verify_incident_pack,
    verify_period_pack,
)
from app.evidence.packs import PeriodEvidencePack, _outer_bundle_hash

from conformance.fixtures.builders import example_tenant


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _seed_multi_aggregate() -> tuple[SqliteCanonicalStore, str]:
    """One tenant, three aggregates with distinct event mixes so the rollup has
    unambiguous counts: recommendations=2, overrides=1, denials=1, outcomes=1."""
    store = SqliteCanonicalStore()
    tenant = example_tenant()
    store.create_tenant(tenant)
    t = tenant.tenant_id

    # req-A: recommendation then human override
    store.append_event(
        tenant_id=t, aggregate_id="req-A", aggregate_type="ServiceRequest",
        occurred_at=_utc(2026, 7, 20, 8, 0), actor_type="system", actor_id="scheduler",
        event_type=DecisionEventType.RECOMMENDATION, payload={"assignment": "vehicle-7"},
    )
    store.append_event(
        tenant_id=t, aggregate_id="req-A", aggregate_type="ServiceRequest",
        occurred_at=_utc(2026, 7, 20, 9, 0), actor_type="human", actor_id="dispatcher-2",
        event_type=DecisionEventType.OVERRIDE,
        payload={"assignment": "vehicle-3", "rider_note": "prefers front seat"},
    )

    # req-B: recommendation then recorded outcome
    store.append_event(
        tenant_id=t, aggregate_id="req-B", aggregate_type="ServiceRequest",
        occurred_at=_utc(2026, 7, 21, 10, 0), actor_type="system", actor_id="scheduler",
        event_type=DecisionEventType.RECOMMENDATION, payload={"assignment": "vehicle-5"},
    )
    store.append_event(
        tenant_id=t, aggregate_id="req-B", aggregate_type="ServiceRequest",
        occurred_at=_utc(2026, 7, 21, 12, 0), actor_type="system", actor_id="ops",
        event_type=DecisionEventType.OUTCOME_RECORDED, payload={"served": True, "on_time": True},
    )

    # req-C: a denial (rejection)
    store.append_event(
        tenant_id=t, aggregate_id="req-C", aggregate_type="ServiceRequest",
        occurred_at=_utc(2026, 7, 22, 7, 30), actor_type="system", actor_id="scheduler",
        event_type=DecisionEventType.REJECTION, payload={"reason": "no accessible vehicle"},
    )
    return store, t


def _history(store: SqliteCanonicalStore, tenant_id: str, aggregate_id: str) -> AggregateHistory:
    # WHY: whole-tenant raw rows are fine -- build_evidence_pack filters per aggregate.
    return AggregateHistory(
        events=store.history(tenant_id, aggregate_id),
        raw_rows=tuple(store.raw_rows_for_tenant(tenant_id)),
    )


def _all_three(store: SqliteCanonicalStore, tenant_id: str) -> list[AggregateHistory]:
    return [_history(store, tenant_id, agg) for agg in ("req-A", "req-B", "req-C")]


# --------------------------------------------------------------------------- #
# Period                                                                       #
# --------------------------------------------------------------------------- #


def test_period_pack_reverifies_over_multiple_aggregates() -> None:
    store, t = _seed_multi_aggregate()
    period = build_period_pack(
        _all_three(store, t),
        period_start=_utc(2026, 7, 20, 0, 0),
        period_end=_utc(2026, 7, 23, 0, 0),
        label="week-30 review",
    )

    restored = PeriodEvidencePack.from_json(period.to_json())
    result = verify_period_pack(restored)

    assert result.reverified
    assert result.bundle_hash_matches
    assert result.all_packs_reverified
    assert result.rollup_consistent
    assert result.coverage_consistent
    assert result.pack_count == 3
    assert restored.manifest.independently_verifiable
    assert restored.manifest.aggregate_count == 3


def test_period_rollup_counts_recorded_events_only() -> None:
    store, t = _seed_multi_aggregate()
    period = build_period_pack(
        _all_three(store, t),
        period_start=_utc(2026, 7, 20, 0, 0),
        period_end=_utc(2026, 7, 23, 0, 0),
    )
    rollup = period.body.rollup
    assert rollup.aggregate_count == 3
    assert rollup.event_count == 5
    assert rollup.recommendations == 2
    assert rollup.overrides == 1
    assert rollup.denials == 1
    assert rollup.outcomes_recorded == 1
    # honest framing: counts, not causal/performance claims
    assert "NOT causal" in rollup.note
    # declared window vs actual coverage are both recorded
    assert period.body.covered_from == _utc(2026, 7, 20, 8, 0)
    assert period.body.covered_to == _utc(2026, 7, 22, 7, 30)


def test_period_pack_empty_is_refused() -> None:
    try:
        build_period_pack([], period_start=_utc(2026, 7, 20), period_end=_utc(2026, 7, 23))
    except ValueError as exc:
        assert "zero aggregates" in str(exc)
    else:
        raise AssertionError("expected ValueError on an empty period selection")


def test_period_pack_refuses_to_mix_tenants() -> None:
    store_a, ta = _seed_multi_aggregate()
    store_b, tb = _seed_multi_aggregate()
    try:
        build_period_pack(
            [_history(store_a, ta, "req-A"), _history(store_b, tb, "req-B")],
            period_start=_utc(2026, 7, 20),
            period_end=_utc(2026, 7, 23),
        )
    except ValueError as exc:
        assert "one tenant" in str(exc)
    else:
        raise AssertionError("expected ValueError on a cross-tenant period pack")


def test_period_tampered_embedded_pack_is_detected_by_outer_checksum() -> None:
    store, t = _seed_multi_aggregate()
    period = build_period_pack(
        _all_three(store, t),
        period_start=_utc(2026, 7, 20),
        period_end=_utc(2026, 7, 23),
    )

    # edit an embedded pack's event payload, leave the outer checksum alone
    victim = period.body.packs[0]
    tampered_rows = [dict(row) for row in victim.raw_events]
    tampered_rows[0]["payload_json"] = json.dumps({"assignment": "vehicle-99"})
    tampered_victim = victim.model_copy(update={"raw_events": tuple(tampered_rows)})
    new_packs = (tampered_victim,) + period.body.packs[1:]
    tampered_body = period.body.model_copy(update={"packs": new_packs})
    tampered = period.model_copy(update={"body": tampered_body})

    result = verify_period_pack(tampered)
    assert not result.reverified
    assert not result.bundle_hash_matches


def test_period_reanchored_outer_hash_still_fails_on_embedded_pack() -> None:
    """Even if an attacker recomputes the outer checksum after editing an
    embedded event, that embedded pack no longer self-verifies (its own bundle
    hash / hash chain break), so the period bundle is still rejected."""
    store, t = _seed_multi_aggregate()
    period = build_period_pack(
        _all_three(store, t),
        period_start=_utc(2026, 7, 20),
        period_end=_utc(2026, 7, 23),
    )

    victim = period.body.packs[0]
    tampered_rows = [dict(row) for row in victim.raw_events]
    tampered_rows[0]["payload_json"] = json.dumps({"assignment": "vehicle-99"})
    tampered_victim = victim.model_copy(update={"raw_events": tuple(tampered_rows)})
    new_packs = (tampered_victim,) + period.body.packs[1:]
    tampered_body = period.body.model_copy(update={"packs": new_packs})
    reanchored_manifest = period.manifest.model_copy(
        update={"bundle_sha256": _outer_bundle_hash(tampered_body.model_dump(mode="json"))}
    )
    reanchored = period.model_copy(
        update={"body": tampered_body, "manifest": reanchored_manifest}
    )

    result = verify_period_pack(reanchored)
    assert result.bundle_hash_matches          # attacker fixed the outer checksum...
    assert not result.all_packs_reverified     # ...but the embedded pack still breaks
    assert not result.reverified


def test_period_tampered_rollup_is_detected() -> None:
    store, t = _seed_multi_aggregate()
    period = build_period_pack(
        _all_three(store, t),
        period_start=_utc(2026, 7, 20),
        period_end=_utc(2026, 7, 23),
    )

    # inflate the override count and re-anchor the outer checksum
    lying_rollup = period.body.rollup.model_copy(update={"overrides": 99})
    lying_body = period.body.model_copy(update={"rollup": lying_rollup})
    reanchored_manifest = period.manifest.model_copy(
        update={"bundle_sha256": _outer_bundle_hash(lying_body.model_dump(mode="json"))}
    )
    lying = period.model_copy(update={"body": lying_body, "manifest": reanchored_manifest})

    result = verify_period_pack(lying)
    assert result.bundle_hash_matches      # checksum re-anchored...
    assert not result.rollup_consistent    # ...but the rollup no longer matches the packs
    assert not result.reverified


# --------------------------------------------------------------------------- #
# Incident                                                                     #
# --------------------------------------------------------------------------- #


def test_incident_pack_reverifies_primary_plus_related() -> None:
    store, t = _seed_multi_aggregate()
    incident = build_incident_pack(
        incident_id="inc-0007",
        summary="rider disputes the vehicle change on req-A",
        primary=[_history(store, t, "req-A")],
        related=[_history(store, t, "req-B")],
        context_note="same dispatcher shift, 2026-07-20/21",
    )

    from app.evidence.packs import IncidentEvidencePack

    restored = IncidentEvidencePack.from_json(incident.to_json())
    result = verify_incident_pack(restored)

    assert result.reverified
    assert result.bundle_hash_matches
    assert result.all_packs_reverified
    assert result.primary_count == 1
    assert result.related_count == 1
    assert restored.manifest.incident_id == "inc-0007"


def test_incident_pack_preserves_the_decision_narrative() -> None:
    store, t = _seed_multi_aggregate()
    incident = build_incident_pack(
        incident_id="inc-0007",
        summary="rider disputes the vehicle change on req-A",
        primary=[_history(store, t, "req-A")],
    )

    evidence = incident.body.primary_packs[0].evidence
    # the reused EvidencePacket narrative is embedded faithfully
    assert evidence["executed"]["event_type"] == DecisionEventType.OVERRIDE.value
    assert len(evidence["known_inputs"]) == 1
    assert len(evidence["approved_or_overridden"]) == 1


def test_incident_pack_needs_a_primary_aggregate() -> None:
    store, t = _seed_multi_aggregate()
    try:
        build_incident_pack(incident_id="inc-x", summary="none", primary=[])
    except ValueError as exc:
        assert "primary" in str(exc)
    else:
        raise AssertionError("expected ValueError with no primary aggregate")


def test_incident_tampered_related_pack_is_detected() -> None:
    store, t = _seed_multi_aggregate()
    incident = build_incident_pack(
        incident_id="inc-0007",
        summary="dispute",
        primary=[_history(store, t, "req-A")],
        related=[_history(store, t, "req-B")],
    )

    victim = incident.body.related_packs[0]
    tampered_rows = [dict(row) for row in victim.raw_events]
    tampered_rows[0]["payload_json"] = json.dumps({"assignment": "vehicle-99"})
    tampered_victim = victim.model_copy(update={"raw_events": tuple(tampered_rows)})
    tampered_body = incident.body.model_copy(update={"related_packs": (tampered_victim,)})
    tampered = incident.model_copy(update={"body": tampered_body})

    result = verify_incident_pack(tampered)
    assert not result.reverified
    assert not result.bundle_hash_matches


# --------------------------------------------------------------------------- #
# Procurement                                                                  #
# --------------------------------------------------------------------------- #


def test_procurement_bundle_separates_available_from_not_yet_available() -> None:
    bundle = build_procurement_bundle("Harland County Mobility")

    available_keys = {i.key for i in bundle.available}
    not_yet_keys = {i.key for i in bundle.not_yet_available}

    # things this repository can honestly substantiate today
    assert {"architecture_data_flow", "model_policy_governance", "known_gaps_remediation"} <= available_keys
    # things that require external legal/ops/audit input -- honest placeholders
    assert {
        "encryption_key_management",
        "subprocessor_deployment_list",
        "current_certifications",
        "accessibility_statement",
    } <= not_yet_keys

    # a key is never in two buckets at once
    assert available_keys.isdisjoint(not_yet_keys)
    # the three buckets partition every item
    assert len(bundle.available) + len(bundle.partial) + len(bundle.not_yet_available) == len(bundle.items)


def test_procurement_not_yet_items_require_external_input_and_have_no_references() -> None:
    bundle = build_procurement_bundle()
    for item in bundle.not_yet_available:
        assert item.requires_external_input, item.key
        assert item.references == (), item.key
    for item in bundle.available:
        assert not item.requires_external_input, item.key
        assert item.references, item.key


def test_procurement_bundle_makes_no_compliance_claim() -> None:
    bundle = build_procurement_bundle()
    # no item note asserts compliance
    for item in bundle.items:
        assert "compliant" not in item.note.lower(), item.key
    # certifications item is explicitly empty and defers to an external audit
    certs = next(i for i in bundle.items if i.key == "current_certifications")
    assert certs.status == "not_yet_available"
    assert "external audit" in certs.note
    # the disclaimer disclaims compliance outright
    assert "NO compliance claim" in bundle.disclaimer


def test_procurement_bundle_round_trips_through_json() -> None:
    bundle = build_procurement_bundle("Harland County Mobility")
    restored = type(bundle).from_json(bundle.to_json())
    assert restored.items == bundle.items
    assert restored.generated_for == "Harland County Mobility"
    assert len(restored.items) == 13
