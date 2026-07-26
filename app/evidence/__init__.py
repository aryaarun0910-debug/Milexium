"""Program I (partial): Evidence IR + Experience IR -- v0.1 slice.

Builds a faithful, reviewable narrative for one aggregate's DecisionEvent
history (blueprint/07-explain-replay-and-evidence.md,
blueprint/14-execution-roadmap.md Program I) strictly from already-recorded
events, raw storage rows, and outcomes -- never from a live store connection,
so the same builder works for any backend implementing the canonical
event-log contract. Calls app.verify.verify_chain for the actual
integrity check rather than re-implementing a weaker one, per the
generator/verifier separation established by ADR-0003.

Not centrally wired into any existing __init__.py -- see the orchestrator's
integration review for whether/where this package should be re-exported.
"""

from app.evidence.builder import build_evidence_packet, build_experience_packet
from app.evidence.models import EvidencePacket, ExperiencePacket, KnownInput
from app.evidence.export import (
    EvidencePack,
    PackManifest,
    PackVerification,
    build_evidence_pack,
    redact_pack,
    verify_evidence_pack,
)
from app.evidence.teardown_capture import TeardownCaptureError, capture_teardown
from app.evidence.teardown_evidence import (
    TeardownBucketRow,
    TeardownEvidence,
    TeardownFigures,
    TeardownRederivation,
    TeardownRunRow,
    TeardownSegmentRow,
    rederive_teardown,
)
from app.evidence.pack_file import (
    ALGORITHM,
    ATTESTS,
    DOES_NOT_ATTEST,
    PACK_FILE_VERSION,
    AlgorithmRule,
    AttestationScope,
    EmbeddedVerifier,
    VerifiablePackFile,
    build_pack_file,
    verifier_source,
    verify_pack_file_document,
    write_verifier_script,
)
from app.evidence.packs import (
    AggregateHistory,
    IncidentEvidencePack,
    IncidentManifest,
    IncidentVerification,
    PeriodEvidencePack,
    PeriodManifest,
    PeriodRollup,
    PeriodVerification,
    ProcurementBundle,
    ProcurementItem,
    build_incident_pack,
    build_period_pack,
    build_procurement_bundle,
    verify_incident_pack,
    verify_period_pack,
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
    "TeardownBucketRow",
    "TeardownCaptureError",
    "TeardownEvidence",
    "TeardownFigures",
    "TeardownRederivation",
    "TeardownRunRow",
    "TeardownSegmentRow",
    "capture_teardown",
    "rederive_teardown",
    "AggregateHistory",
    "PeriodEvidencePack",
    "PeriodManifest",
    "PeriodRollup",
    "PeriodVerification",
    "build_period_pack",
    "verify_period_pack",
    "IncidentEvidencePack",
    "IncidentManifest",
    "IncidentVerification",
    "build_incident_pack",
    "verify_incident_pack",
    "ProcurementBundle",
    "ProcurementItem",
    "build_procurement_bundle",
    "ALGORITHM",
    "ATTESTS",
    "DOES_NOT_ATTEST",
    "PACK_FILE_VERSION",
    "AlgorithmRule",
    "AttestationScope",
    "EmbeddedVerifier",
    "VerifiablePackFile",
    "build_pack_file",
    "verifier_source",
    "verify_pack_file_document",
    "write_verifier_script",
]

CONTRACT_VERSION = "0.1.0"
