"""Program I extension conformance: the evidence pack round-trips through JSON
and re-verifies independently; a tampered pack fails; redaction is honest about
its weaker guarantee.

This is the "hand a partner a self-contained, independently-verifiable evidence
artifact" capability -- the machine-verifiable export of blueprint 07.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from packages.canonical import DecisionEventType, SqliteCanonicalStore
from packages.evidence import (
    EvidencePack,
    build_evidence_pack,
    redact_pack,
    verify_evidence_pack,
)

from conformance.fixtures.builders import example_tenant


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _seeded_chain() -> tuple[SqliteCanonicalStore, str, str]:
    store = SqliteCanonicalStore()
    tenant = example_tenant()
    store.create_tenant(tenant)
    aggregate_id = "req-export-0001"
    store.append_event(
        tenant_id=tenant.tenant_id, aggregate_id=aggregate_id, aggregate_type="ServiceRequest",
        occurred_at=_utc(2026, 7, 23, 8, 0), actor_type="system", actor_id="scheduler",
        event_type=DecisionEventType.RECOMMENDATION, payload={"assignment": "vehicle-7"},
    )
    store.append_event(
        tenant_id=tenant.tenant_id, aggregate_id=aggregate_id, aggregate_type="ServiceRequest",
        occurred_at=_utc(2026, 7, 23, 9, 0), actor_type="human", actor_id="dispatcher-2",
        event_type=DecisionEventType.OVERRIDE, payload={"assignment": "vehicle-3", "rider_note": "prefers front seat"},
    )
    return store, tenant.tenant_id, aggregate_id


def _pack_for(store, tenant_id, aggregate_id) -> EvidencePack:
    events = store.history(tenant_id, aggregate_id)
    raw = store.raw_rows_for_tenant(tenant_id)
    return build_evidence_pack(events, raw)


def test_pack_round_trips_through_json_and_reverifies() -> None:
    store, tenant_id, aggregate_id = _seeded_chain()
    pack = _pack_for(store, tenant_id, aggregate_id)

    restored = EvidencePack.from_json(pack.to_json())
    result = verify_evidence_pack(restored)

    assert result.reverified
    assert result.bundle_hash_matches
    assert result.chain_reverified
    assert restored.manifest.independently_verifiable
    assert restored.manifest.aggregate_id == aggregate_id
    assert restored.manifest.event_count == 2


def test_altering_pack_content_after_export_is_detected() -> None:
    store, tenant_id, aggregate_id = _seeded_chain()
    pack = _pack_for(store, tenant_id, aggregate_id)

    # A recipient (or an attacker) edits an embedded event payload but leaves
    # the manifest checksum alone.
    tampered_events = [dict(row) for row in pack.raw_events]
    tampered_events[0]["payload_json"] = json.dumps({"assignment": "vehicle-99"})
    tampered = pack.model_copy(update={"raw_events": tuple(tampered_events)})

    result = verify_evidence_pack(tampered)
    assert not result.reverified
    assert not result.bundle_hash_matches  # the bundle checksum catches it


def test_reserializing_a_tampered_event_still_fails_chain_reverification() -> None:
    """Even if an attacker recomputes the bundle checksum after editing an
    event (so bundle_hash_matches), the embedded hash chain no longer verifies
    because the stored per-event hash was computed over the original payload."""
    store, tenant_id, aggregate_id = _seeded_chain()
    pack = _pack_for(store, tenant_id, aggregate_id)

    tampered_events = [dict(row) for row in pack.raw_events]
    tampered_events[0]["payload_json"] = json.dumps({"assignment": "vehicle-99"})
    tampered = pack.model_copy(update={"raw_events": tuple(tampered_events)})
    # attacker re-anchors the bundle hash to the tampered content
    from packages.evidence.export import _bundle_hash

    reanchored_manifest = tampered.manifest.model_copy(
        update={"bundle_sha256": _bundle_hash(tampered.evidence, tampered.raw_events, tampered.outcome)}
    )
    reanchored = tampered.model_copy(update={"manifest": reanchored_manifest})

    result = verify_evidence_pack(reanchored)
    assert result.bundle_hash_matches      # attacker fixed the outer checksum...
    assert not result.chain_reverified     # ...but the inner hash chain still breaks
    assert not result.reverified


def test_redaction_masks_fields_and_marks_the_pack_non_verifiable() -> None:
    store, tenant_id, aggregate_id = _seeded_chain()
    pack = _pack_for(store, tenant_id, aggregate_id)

    redacted = redact_pack(pack, sensitive_payload_keys=("rider_note",))

    # the sensitive field is masked in the embedded events
    joined = " ".join(row["payload_json"] for row in redacted.raw_events)
    assert "prefers front seat" not in joined
    assert "[REDACTED]" in joined

    assert not redacted.manifest.independently_verifiable
    assert redacted.manifest.redacted_fields == ("rider_note",)
    assert "NOT HIPAA de-identification" in redacted.manifest.note

    # verify is honest: a redacted pack cannot chain-reverify, and says why
    result = verify_evidence_pack(redacted)
    assert not result.reverified
    assert any("redacted" in r.lower() for r in result.reasons)


def test_redacted_pack_bundle_checksum_still_detects_later_tampering() -> None:
    store, tenant_id, aggregate_id = _seeded_chain()
    pack = _pack_for(store, tenant_id, aggregate_id)
    redacted = redact_pack(pack, sensitive_payload_keys=("rider_note",))

    tampered_events = [dict(row) for row in redacted.raw_events]
    tampered_events[0]["payload_json"] = json.dumps({"assignment": "vehicle-42"})
    tampered = redacted.model_copy(update={"raw_events": tuple(tampered_events)})

    result = verify_evidence_pack(tampered)
    assert not result.bundle_hash_matches
