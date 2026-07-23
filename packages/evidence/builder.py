"""Builders for the Evidence IR / Experience IR models (Program I, v0.1 slice).

`build_evidence_packet` takes plain `events`/`raw_rows`/`outcome` values, not a
live store connection, so the exact same function reconstructs a packet
regardless of which storage backend produced the history -- SQLite today
(packages.canonical.storage.SqliteCanonicalStore) or a future PostgreSQL
store, so long as it returns DecisionEvent tuples and raw dict rows shaped
like packages.verify.verify_chain expects.

`DecisionAlternative` has no row of its own in the append-only ledger (see
packages/canonical/sql/schema_v0_1.sql's separate `decision_alternatives`
table, which packages/canonical does not yet expose a store method for) --
this module's contract is that a producer wanting alternatives to appear in
an evidence packet embeds them in a RECOMMENDATION event's
`payload["alternatives"]` as a list of dicts, each parseable as a
DecisionAlternative. This is a v0.1 convention owned by this package, not a
new capability grafted onto packages.canonical.
"""

from __future__ import annotations

from packages.canonical.entities import DecisionAlternative, DecisionEvent, Outcome
from packages.canonical.vocab import DecisionEventType
from packages.evidence.models import EvidencePacket, ExperiencePacket, KnownInput
from packages.verify.hash_chain_verifier import verify_chain


def _alternatives_from_payload(payload: dict) -> tuple[DecisionAlternative, ...]:
    raw = payload.get("alternatives")
    if not raw:
        return ()
    return tuple(DecisionAlternative.model_validate(item) for item in raw)


def _extract_policy_version(payload: dict) -> str | None:
    for key in ("policy_version", "policy_id"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return None


def build_evidence_packet(
    events: tuple[DecisionEvent, ...],
    raw_rows: list[dict],
    outcome: Outcome | None = None,
) -> EvidencePacket:
    """Reconstruct one aggregate's EvidencePacket from its DecisionEvent
    history, the raw storage rows backing that history (for the independent
    integrity check), and its Outcome if one has been recorded yet.

    `events` need not be pre-sorted by sequence; this function sorts them
    itself, matching packages.verify.verify_chain's own "does not depend on
    the caller's ordering guarantee" stance. `raw_rows` is filtered down to
    this aggregate_id before verification so an unrelated aggregate's rows
    (e.g. a whole tenant's raw_rows_for_tenant()) do not pollute this
    packet's chain_violations with violations that are not this packet's.
    """
    if not events:
        raise ValueError("cannot build an EvidencePacket from an empty event history")

    ordered = tuple(sorted(events, key=lambda e: e.sequence))
    tenant_id = ordered[0].tenant_id
    aggregate_id = ordered[0].aggregate_id
    aggregate_type = ordered[0].aggregate_type
    for event in ordered[1:]:
        if event.tenant_id != tenant_id or event.aggregate_id != aggregate_id:
            raise ValueError(
                "all events passed to build_evidence_packet must share one "
                f"tenant_id/aggregate_id; found {event.tenant_id}/{event.aggregate_id} "
                f"alongside {tenant_id}/{aggregate_id}"
            )

    known_inputs = tuple(
        KnownInput(
            event_id=e.event_id,
            occurred_at=e.occurred_at,
            reason_codes=e.reason_codes,
            payload=e.payload,
        )
        for e in ordered
        if e.event_type == DecisionEventType.RECOMMENDATION
    )

    proposed = tuple(
        e
        for e in ordered
        if e.event_type in (DecisionEventType.RECOMMENDATION, DecisionEventType.REJECTION)
    )

    alternatives_considered = tuple(
        alt
        for e in ordered
        if e.event_type == DecisionEventType.RECOMMENDATION
        for alt in _alternatives_from_payload(e.payload)
    )

    approved_or_overridden = tuple(e for e in ordered if e.event_type == DecisionEventType.OVERRIDE)

    outcome_events = tuple(e for e in ordered if e.event_type == DecisionEventType.OUTCOME_RECORDED)

    directives = tuple(
        e for e in ordered if e.event_type in (DecisionEventType.RECOMMENDATION, DecisionEventType.OVERRIDE)
    )
    executed = directives[-1] if directives else None

    relevant_raw_rows = [row for row in raw_rows if row.get("aggregate_id") == aggregate_id]
    violations = tuple(verify_chain(relevant_raw_rows))

    return EvidencePacket(
        tenant_id=tenant_id,
        aggregate_id=aggregate_id,
        aggregate_type=aggregate_type,
        known_inputs=known_inputs,
        proposed=proposed,
        alternatives_considered=alternatives_considered,
        approved_or_overridden=approved_or_overridden,
        outcome_events=outcome_events,
        executed=executed,
        observed=outcome,
        integrity_verified=len(violations) == 0,
        chain_violations=violations,
    )


def build_experience_packet(packet: EvidencePacket, outcome: Outcome) -> ExperiencePacket:
    """Derive a compact precedent record from an EvidencePacket plus its
    Outcome. `outcome` is a separate argument (not just `packet.observed`)
    because an outcome routinely arrives after the EvidencePacket was first
    built; if the packet already carries one, it must agree with this one.

    Refuses to build from a packet whose chain integrity did not verify --
    an untrusted precedent is exactly the kind of unsafe shortcut
    blueprint/01-north-star-and-boundaries.md forbids for a hash chain that
    is "tamper-evident, not immutable and not a compliance certificate."
    """
    if not packet.integrity_verified:
        raise ValueError(
            "refusing to build an ExperiencePacket from an EvidencePacket whose "
            "chain integrity did not verify -- see packet.chain_violations"
        )
    if packet.observed is not None and packet.observed != outcome:
        raise ValueError("outcome does not match the Outcome already recorded on this EvidencePacket")
    if packet.executed is None:
        raise ValueError(
            "cannot build an ExperiencePacket: no recommendation or override was ever recorded"
        )

    situation_features = packet.known_inputs[-1].payload if packet.known_inputs else {}

    policy_version = _extract_policy_version(packet.executed.payload)
    if policy_version is None and packet.known_inputs:
        policy_version = _extract_policy_version(packet.known_inputs[-1].payload)

    return ExperiencePacket(
        tenant_id=packet.tenant_id,
        aggregate_id=packet.aggregate_id,
        situation_features=situation_features,
        decision_event_id=packet.executed.event_id,
        decision_type=packet.executed.event_type,
        decision_actor_type=packet.executed.actor_type,
        decision_actor_id=packet.executed.actor_id,
        decision_payload=packet.executed.payload,
        reason_codes=packet.executed.reason_codes,
        outcome=outcome,
        policy_version=policy_version,
    )
