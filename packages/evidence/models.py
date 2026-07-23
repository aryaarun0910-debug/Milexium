"""Evidence IR and Experience IR models (Program I, v0.1 slice).

blueprint/07-explain-replay-and-evidence.md and blueprint/14-execution-
roadmap.md's Program I integration proof require that "an independent
reviewer can reconstruct what was known, proposed, verified, approved,
executed, and observed" from recorded facts alone. These models hold exactly
that reconstruction -- they are populated by packages/evidence/builder.py
from an aggregate's already-recorded DecisionEvent history, never inferred
or fabricated here. Per blueprint/01-north-star-and-boundaries.md ("A
generated natural-language explanation is never the authoritative decision
record"), this structured packet is the record; any prose rendering of it is
strictly secondary and derived, and no such rendering is built in this slice.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from packages.canonical.entities import DecisionAlternative, DecisionEvent, Outcome
from packages.canonical.ids import DecisionEventId, TenantId
from packages.canonical.time import UtcDateTime
from packages.canonical.vocab import DecisionEventType, ReasonCode
from packages.verify.hash_chain_verifier import ChainViolation


class _Evidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class KnownInput(_Evidence):
    """What was known when one RECOMMENDATION event was generated -- that
    event's own payload and reason codes, verbatim. Never supplemented with
    information not actually recorded at that sequence."""

    event_id: DecisionEventId
    occurred_at: UtcDateTime
    reason_codes: tuple[ReasonCode, ...]
    payload: dict


class EvidencePacket(_Evidence):
    """Evidence IR v0.1: the reconstructed narrative for one aggregate's full
    decision history. Built only from an event history, raw storage rows, and
    (if it exists yet) an Outcome -- this packet reorganizes already-recorded
    facts, it never derives a new one about the world.
    """

    tenant_id: TenantId
    aggregate_id: str
    aggregate_type: str

    known_inputs: tuple[KnownInput, ...]
    """What was known: one entry per RECOMMENDATION event, in sequence order."""

    proposed: tuple[DecisionEvent, ...]
    """What was proposed or declined: RECOMMENDATION and REJECTION events, in sequence order."""

    alternatives_considered: tuple[DecisionAlternative, ...]
    """Candidate assignments considered and why each was/wasn't feasible --
    parsed from each RECOMMENDATION event's payload["alternatives"], if the
    producer recorded any (DecisionAlternative has no ledger row of its own,
    see architecture note in the builder module)."""

    approved_or_overridden: tuple[DecisionEvent, ...]
    """OVERRIDE events only, in sequence order: actor and stated reason for superseding a prior recommendation."""

    outcome_events: tuple[DecisionEvent, ...]
    """OUTCOME_RECORDED events found directly in this aggregate's ledger, if
    any -- distinct from `observed` below (the canonical Outcome record,
    which may come from a separate outcomes-table read)."""

    executed: DecisionEvent | None
    """The operative decision that stood at the end of the chain: the last
    OVERRIDE if one exists, else the last RECOMMENDATION. None if the chain
    has neither."""

    observed: Outcome | None
    """The recorded operational outcome, if one exists yet. Never fabricated when absent."""

    integrity_verified: bool
    """True iff packages.verify.verify_chain found zero violations in this
    aggregate's raw rows -- the actual check result, not a claim."""

    chain_violations: tuple[ChainViolation, ...]
    """Every violation packages.verify.verify_chain found for this
    aggregate's raw rows. Empty iff integrity_verified is True."""


class ExperiencePacket(_Evidence):
    """Experience IR v0.1: a compact precedent record -- situation features,
    the decision taken, the observed outcome, and the applicable policy
    version (if the producer recorded one) -- derived from an already-
    verified EvidencePacket plus its Outcome. No retrieval/indexing logic
    here: that is a later Program D/J concern, already stubbed by
    packages.canonical.semantic_index.SemanticIndex and not touched by this
    slice.
    """

    tenant_id: TenantId
    aggregate_id: str

    situation_features: dict
    """The most recent known-input payload before the executed decision; {} if the chain never recorded one."""

    decision_event_id: DecisionEventId
    decision_type: DecisionEventType
    decision_actor_type: str
    decision_actor_id: str
    decision_payload: dict
    reason_codes: tuple[ReasonCode, ...]

    outcome: Outcome

    policy_version: str | None
    """Best-effort: read from the executed event's payload, else the most
    recent known-input payload, under 'policy_version' then 'policy_id'.
    None if the producer never recorded either -- not fabricated."""
