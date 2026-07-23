"""Adversarial evidence conformance (Program I, v0.1 slice): a tampered
decision ledger must never produce an EvidencePacket that looks trustworthy.
Uses the same tampering technique as conformance/adversarial/
test_tamper_and_isolation.py (SqliteCanonicalStore.tamper_with_row) so the
attack is against real stored bytes, not a hand-faked packet.
"""

from __future__ import annotations

import pytest

from packages.canonical.events import compute_hash
from packages.evidence import build_evidence_packet, build_experience_packet

from conformance.fixtures.evidence_builders import build_recommendation_override_outcome_chain


def test_tampered_payload_flags_the_packet_as_unverified_and_blocks_experience() -> None:
    store, tenant_id, aggregate_id, outcome = build_recommendation_override_outcome_chain()
    history = store.history(tenant_id, aggregate_id)
    recommendation_event_id = history[0].event_id

    # Attack: rewrite the recommended vehicle after the fact, without
    # recomputing the hash -- exactly the threat model
    # test_tamper_and_isolation.py already exercises for packages.verify
    # directly; here we prove the *evidence packet* surfaces it too, rather
    # than silently reporting the tampered payload as fact.
    store.tamper_with_row(recommendation_event_id, payload_json='{"recommended_vehicle_id": "attacker-installed"}')

    events = store.history(tenant_id, aggregate_id)
    raw_rows = store.raw_rows_for_tenant(tenant_id)
    packet = build_evidence_packet(events, raw_rows, outcome=outcome)

    assert packet.integrity_verified is False
    assert any(v.kind == "hash_mismatch" for v in packet.chain_violations)
    # The tampered payload is still visible in the reconstructed narrative --
    # the packet must not hide it, only flag it as unverified.
    assert packet.known_inputs[0].payload == {"recommended_vehicle_id": "attacker-installed"}

    with pytest.raises(ValueError):
        build_experience_packet(packet, outcome)


def test_forged_hash_that_breaks_the_downstream_chain_link_is_still_caught() -> None:
    """A more sophisticated attacker recomputes *a* hash after tampering but
    does not chain-update every downstream event's prev_hash -- the packet
    must still flag integrity_verified=False because verify_chain checks the
    whole chain, not just each event's own hash in isolation."""
    store, tenant_id, aggregate_id, outcome = build_recommendation_override_outcome_chain()
    history = store.history(tenant_id, aggregate_id)
    target = history[0]

    forged_payload = {"recommended_vehicle_id": "attacker-installed"}
    forged_hash = compute_hash(target.prev_hash, forged_payload, target.sequence, aggregate_id)
    store.tamper_with_row(
        target.event_id,
        payload_json='{"recommended_vehicle_id": "attacker-installed"}',
        hash=forged_hash,
    )

    events = store.history(tenant_id, aggregate_id)
    raw_rows = store.raw_rows_for_tenant(tenant_id)
    packet = build_evidence_packet(events, raw_rows, outcome=outcome)

    assert packet.integrity_verified is False
    assert any(v.kind == "prev_hash_mismatch" for v in packet.chain_violations)
