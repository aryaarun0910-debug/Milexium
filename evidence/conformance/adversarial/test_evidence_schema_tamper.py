"""Schema-conformance adversarial case for Evidence IR (Program I follow-up
slice, see knowledge/architecture/decisions/0009-evidence-ir-v0-1-conventions.md's
"Consequences"): proves the independent schema check
(app.verify.verify_against_schema) catches a DecisionEvent that reached
build_evidence_packet via a path that skipped normal Pydantic validation --
the one scenario where this check is not a tautology (see the module note in
app/evidence/builder.py). A real store round-trip cannot produce this
scenario: SqliteCanonicalStore.history() reconstructs every row via
DecisionEvent(...), which re-validates on every read. Only DecisionEvent.
model_construct, which bypasses __init__ validation entirely, can fabricate
it -- exactly the "already-Pydantic-validated objects only" assumption this
check exists to not blindly trust.

Hash-chain tampering (mutating stored bytes without recomputing the hash) is
already covered by evidence/conformance/adversarial/test_evidence_tamper.py; this file
is deliberately about a different, independent failure mode.
"""

from __future__ import annotations

import pytest

from app.canonical.entities import DecisionEvent, Outcome
from app.canonical.ids import RequestId, new_id
from app.evidence import build_evidence_packet, build_experience_packet

from conformance.fixtures.evidence_builders import build_recommendation_only_chain


def test_schema_invalid_event_is_caught_independently_of_the_hash_chain() -> None:
    store, tenant_id, aggregate_id = build_recommendation_only_chain()
    events = store.history(tenant_id, aggregate_id)
    raw_rows = store.raw_rows_for_tenant(tenant_id)
    valid = events[0]

    # actor_type must match "^(system|human)$" (app/canonical/entities.py);
    # model_construct bypasses that check entirely.
    malformed = DecisionEvent.model_construct(
        event_id=valid.event_id,
        tenant_id=valid.tenant_id,
        aggregate_id=valid.aggregate_id,
        aggregate_type=valid.aggregate_type,
        sequence=valid.sequence,
        occurred_at=valid.occurred_at,
        actor_type="attacker-injected-actor-type",
        actor_id=valid.actor_id,
        event_type=valid.event_type,
        payload=valid.payload,
        reason_codes=valid.reason_codes,
        idempotency_key=valid.idempotency_key,
        prev_hash=valid.prev_hash,
        hash=valid.hash,
    )

    packet = build_evidence_packet((malformed,), raw_rows)

    # The raw stored bytes were never touched -- the hash chain is still
    # intact. Only the independent schema check catches this.
    assert packet.chain_violations == ()
    assert packet.schema_violations != ()
    assert any("actor_type" in violation for violation in packet.schema_violations)
    assert packet.integrity_verified is False


def test_experience_packet_refuses_to_build_from_a_schema_invalid_packet() -> None:
    """The same guard build_experience_packet already applies to a hash-chain
    failure (evidence/conformance/adversarial/test_evidence_tamper.py) must also apply
    to a schema-only failure -- a schema-invalid packet is exactly as
    untrustworthy a precedent source as a hash-broken one."""
    store, tenant_id, aggregate_id = build_recommendation_only_chain()
    events = store.history(tenant_id, aggregate_id)
    raw_rows = store.raw_rows_for_tenant(tenant_id)
    valid = events[0]

    malformed = DecisionEvent.model_construct(
        event_id=valid.event_id,
        tenant_id=valid.tenant_id,
        aggregate_id=valid.aggregate_id,
        aggregate_type=valid.aggregate_type,
        sequence=valid.sequence,
        occurred_at=valid.occurred_at,
        actor_type="attacker-injected-actor-type",
        actor_id=valid.actor_id,
        event_type=valid.event_type,
        payload=valid.payload,
        reason_codes=valid.reason_codes,
        idempotency_key=valid.idempotency_key,
        prev_hash=valid.prev_hash,
        hash=valid.hash,
    )

    packet = build_evidence_packet((malformed,), raw_rows)
    assert packet.integrity_verified is False

    outcome = Outcome(tenant_id=tenant_id, request_id=new_id(RequestId), served=True)
    with pytest.raises(ValueError):
        build_experience_packet(packet, outcome)
