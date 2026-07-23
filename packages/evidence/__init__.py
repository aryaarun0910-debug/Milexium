"""Program I (partial): Evidence IR + Experience IR -- v0.1 slice.

Builds a faithful, reviewable narrative for one aggregate's DecisionEvent
history (blueprint/07-explain-replay-and-evidence.md,
blueprint/14-execution-roadmap.md Program I) strictly from already-recorded
events, raw storage rows, and outcomes -- never from a live store connection,
so the same builder works for any backend implementing the canonical
event-log contract. Calls packages.verify.verify_chain for the actual
integrity check rather than re-implementing a weaker one, per the
generator/verifier separation established by ADR-0003.

Not centrally wired into any existing __init__.py -- see the orchestrator's
integration review for whether/where this package should be re-exported.
"""

from packages.evidence.builder import build_evidence_packet, build_experience_packet
from packages.evidence.models import EvidencePacket, ExperiencePacket, KnownInput
from packages.evidence.export import (
    EvidencePack,
    PackManifest,
    PackVerification,
    build_evidence_pack,
    redact_pack,
    verify_evidence_pack,
)

__all__ = [
    "EvidencePacket",
    "ExperiencePacket",
    "KnownInput",
    "build_evidence_packet",
    "build_experience_packet",
    "EvidencePack",
    "PackManifest",
    "PackVerification",
    "build_evidence_pack",
    "redact_pack",
    "verify_evidence_pack",
]

CONTRACT_VERSION = "0.1.0"
