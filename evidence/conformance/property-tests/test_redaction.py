"""Program I conformance: `redact_pack` actually redacts.

ADR-0017 makes the redacted pack the SHAREABLE artifact -- the procurement /
partner bundle of ADR-0020, the copy that leaves the building. ADR-0044 recorded
that it did not do the one thing it exists to do: the mask was applied to
`pack.raw_events` and the same values rode out untouched in `pack.evidence`, the
`EvidencePacket` dump that embeds every event payload. Silently, so the caller
saw a "redacted" pack and handed it on.

The deliverable here is the leak test: a distinctive sensitive value goes into an
event payload, the pack is redacted, and the value must appear NOWHERE in the
pack's full serialized JSON -- asserted against the raw serialized text, not
against a parsed subset, because a leak that a subset does not cover is exactly
the defect being fixed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.canonical import DecisionEventType, SqliteCanonicalStore
from app.evidence import (
    EvidencePack,
    build_evidence_pack,
    redact_pack,
    verify_evidence_pack,
)

from conformance.fixtures.builders import example_tenant

SENSITIVE = "Wilhelmina Okonkwo-Rutherford, flat 14b Beechcroft Lane"
"""Distinctive on purpose: if this string survives anywhere in the pack, it is
this payload's value that survived and nothing else."""

NOT_SENSITIVE = "vehicle-3"


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _seeded_chain(
    payload: dict | None = None, aggregate_id: str = "req-redaction-0001"
) -> tuple[SqliteCanonicalStore, str, str]:
    store = SqliteCanonicalStore()
    tenant = example_tenant()
    store.create_tenant(tenant)
    store.append_event(
        tenant_id=tenant.tenant_id,
        aggregate_id=aggregate_id,
        aggregate_type="ServiceRequest",
        occurred_at=_utc(2026, 7, 25, 8, 0),
        actor_type="system",
        actor_id="scheduler",
        event_type=DecisionEventType.RECOMMENDATION,
        payload={"assignment": "vehicle-7"},
    )
    store.append_event(
        tenant_id=tenant.tenant_id,
        aggregate_id=aggregate_id,
        aggregate_type="ServiceRequest",
        occurred_at=_utc(2026, 7, 25, 9, 0),
        actor_type="human",
        actor_id="dispatcher-2",
        event_type=DecisionEventType.OVERRIDE,
        payload=payload if payload is not None else {"assignment": NOT_SENSITIVE, "rider_note": SENSITIVE},
    )
    return store, tenant.tenant_id, aggregate_id


def _pack(payload: dict | None = None, aggregate_id: str = "req-redaction-0001") -> EvidencePack:
    store, tenant_id, aggregate = _seeded_chain(payload, aggregate_id)
    return build_evidence_pack(store.history(tenant_id, aggregate), store.raw_rows_for_tenant(tenant_id))


# --------------------------------------------------------------------------
# The leak test -- the deliverable
# --------------------------------------------------------------------------


def test_a_redacted_pack_carries_the_sensitive_value_nowhere_in_its_serialized_json() -> None:
    """THE test. Not "absent from raw_events" -- absent from the bytes."""
    pack = _pack()
    assert SENSITIVE in pack.model_dump_json()  # present before redaction

    redacted = redact_pack(pack, sensitive_payload_keys=("rider_note",))

    assert SENSITIVE not in redacted.model_dump_json()
    # ...and the same holds for the artifact's other serialization path, the one
    # a partner is actually handed as a file.
    assert SENSITIVE not in redacted.to_json()


def test_the_leak_this_fixes_lived_in_the_embedded_evidence_packet() -> None:
    """Pins the exact regression ADR-0044 recorded: the value was in
    `pack.evidence` (the EvidencePacket dump), which masking never touched, so
    an assertion scoped to raw_events passed over a live leak."""
    pack = _pack()
    assert SENSITIVE in json.dumps(pack.evidence)  # where it used to survive

    redacted = redact_pack(pack, sensitive_payload_keys=("rider_note",))

    assert SENSITIVE not in json.dumps(redacted.evidence)
    assert redacted.evidence != pack.evidence  # masking genuinely reached it
    # the pre-fix assertion still holds -- raw_events masking is unchanged
    assert SENSITIVE not in " ".join(row["payload_json"] for row in redacted.raw_events)
    assert "[REDACTED]" in " ".join(row["payload_json"] for row in redacted.raw_events)


def test_a_sensitive_key_nested_anywhere_in_a_payload_is_masked() -> None:
    """The walk follows the data, so a payload key does not escape by being one
    level deeper than the masker's author imagined."""
    nested = f"nested::{SENSITIVE}"
    pack = _pack(
        payload={
            "assignment": NOT_SENSITIVE,
            "escalation": {"handoff": [{"rider_note": nested}]},
        }
    )
    assert nested in pack.model_dump_json()

    redacted = redact_pack(pack, sensitive_payload_keys=("rider_note",))

    assert nested not in redacted.model_dump_json()


# --------------------------------------------------------------------------
# Redaction is not over-broad
# --------------------------------------------------------------------------


def test_a_value_that_was_never_sensitive_survives_redaction_untouched() -> None:
    pack = _pack()
    redacted = redact_pack(pack, sensitive_payload_keys=("rider_note",))
    text = redacted.model_dump_json()

    assert NOT_SENSITIVE in text
    assert "vehicle-7" in text
    # unmasked keys keep their exact recorded values, in both places
    payloads = [json.loads(row["payload_json"]) for row in redacted.raw_events]
    assert payloads[1]["assignment"] == NOT_SENSITIVE
    assert redacted.evidence["executed"]["payload"]["assignment"] == NOT_SENSITIVE
    # structure survives: only the named key's value changed
    assert set(payloads[1]) == {"assignment", "rider_note"}


def test_the_documented_redaction_contract_is_unchanged() -> None:
    """The ADR-0017 surface a caller already depends on: the same marker, the
    same declared fields, the same refusal to claim verifiability."""
    redacted = redact_pack(_pack(), sensitive_payload_keys=("rider_note",))

    assert redacted.manifest.redacted_fields == ("rider_note",)
    assert not redacted.manifest.independently_verifiable
    assert "NOT HIPAA de-identification" in redacted.manifest.note
    assert redacted.teardown is None


# --------------------------------------------------------------------------
# The redacted pack stays internally consistent, and verification stays honest
# --------------------------------------------------------------------------


def test_verification_re_derives_that_the_masking_actually_happened() -> None:
    redacted = redact_pack(_pack(), sensitive_payload_keys=("rider_note",))
    result = verify_evidence_pack(redacted)

    # the bundle checksum was re-anchored over the MASKED content, so a redacted
    # pack is still tamper-evident as a whole
    assert result.bundle_hash_matches
    # masking is re-derived from the pack, not read off the manifest
    assert result.masking_complete is True
    assert result.unmasked_paths == ()
    # ...and nothing more is claimed: no chain proof on masked events
    assert not result.reverified
    assert not result.chain_reverified
    assert any("redacted" in reason.lower() for reason in result.reasons)
    assert any("integrity_verified flag" in reason for reason in result.reasons)


def test_verification_refuses_a_pack_that_claims_a_redaction_it_did_not_perform() -> None:
    """The failure mode this packet exists to kill: a pack that SAYS it is
    redacted while the values are still in it. Verification recomputes the
    claim instead of believing it, and names where it broke."""
    pack = _pack()
    liar = pack.model_copy(
        update={"manifest": pack.manifest.model_copy(update={"redacted_fields": ("rider_note",)})}
    )

    result = verify_evidence_pack(liar)

    assert result.masking_complete is False
    assert any(path.startswith("evidence.") for path in result.unmasked_paths)
    assert any("raw_events[1].payload.rider_note" == path for path in result.unmasked_paths)
    assert any("unmasked value" in reason for reason in result.reasons)
    # every other check still passes -- only the redaction claim fails, and that
    # is enough to withhold re-verification
    assert result.bundle_hash_matches
    assert result.chain_reverified
    assert not result.reverified


def test_an_unredacted_pack_reports_masking_as_not_checked_rather_than_clean() -> None:
    """`None` means "no redaction was claimed, so nothing was checked" --
    deliberately distinct from True, exactly as the teardown reports a
    fingerprint it could not check."""
    result = verify_evidence_pack(_pack())

    assert result.masking_complete is None
    assert result.unmasked_paths == ()
    assert result.reverified


def test_the_bundle_checksum_covers_the_masked_evidence() -> None:
    """The redacted pack is re-anchored over what it actually carries: editing
    the masked EvidencePacket afterwards is caught."""
    redacted = redact_pack(_pack(), sensitive_payload_keys=("rider_note",))
    tampered_evidence = dict(redacted.evidence)
    tampered_evidence["aggregate_type"] = "SomethingElse"
    tampered = redacted.model_copy(update={"evidence": tampered_evidence})

    assert verify_evidence_pack(redacted).bundle_hash_matches
    assert not verify_evidence_pack(tampered).bundle_hash_matches


# --------------------------------------------------------------------------
# What masking cannot reach is stated, not hidden
# --------------------------------------------------------------------------


def test_a_value_masking_could_not_reach_is_reported_in_the_pack() -> None:
    """Key-based masking cannot remove a value that was also recorded somewhere
    that is not a payload key -- here, the aggregate id itself. The pack says so
    in its own manifest note, naming WHERE (never the value), instead of
    presenting itself as clean."""
    leaked_id = "req-leak-9001"
    pack = _pack(payload={"assignment": NOT_SENSITIVE, "rider_note": leaked_id}, aggregate_id=leaked_id)

    redacted = redact_pack(pack, sensitive_payload_keys=("rider_note",))
    note = redacted.manifest.note

    assert "NOT fully masked" in note
    assert "no masked string value surviving" not in note
    assert "evidence.aggregate_id" in note or "raw_events[0].aggregate_id" in note
    # the report names locations, never the value it is reporting on
    assert note.count(leaked_id) == 0
    # and the honest consequence: the value IS still in the pack, which is
    # precisely why the pack has to say so
    assert leaked_id in redacted.model_dump_json()


def test_a_clean_redaction_says_the_scan_found_nothing() -> None:
    redacted = redact_pack(_pack(), sensitive_payload_keys=("rider_note",))

    assert "no masked string value surviving" in redacted.manifest.note
    assert "NOT fully masked" not in redacted.manifest.note
