"""Ontology v1 and the `DecisionSnapshot` (MX-ONT-DECISION-SNAPSHOT-013).

WHAT WAS MISSING, IN ONE SENTENCE. Milexium could forecast in one place, solve in
another and export evidence in a third, but nothing in the repository could hold
a complete DECISION EPISODE --

    this request arrived at 10:02; this wheelchair-accessible vehicle was
    expected free at 10:41; these three trips were mutually compatible; this
    assignment consumed two likely future pooling opportunities; the dispatcher
    overrode it; the resulting pickup was 14 minutes late

-- and that episode is the unit intelligence learns from.

THE FIVE PIECES, AND WHICH MODULE EACH LIVES IN.

  `vocab.py`       The closed vocabularies: 28 object kinds, 23 relationship
                   kinds with a legality table, 16 event kinds, 11 action kinds,
                   8 permissions, and the provenance vocabularies (fact class,
                   quality, missingness, legal basis, repair kind).
  `graph.py`       Objects (identity ONLY -- no attribute may live on one) and
                   relationships as first-class records with a time extent and an
                   optional probability.
  `provenance.py`  `SnapshotFact`: one field-level claim with source system,
                   source record id, event time, receipt time, quality,
                   confidence, repair lineage, privacy class, legal basis and
                   missingness reason. Plus `IdentityResolution`, which retains
                   uncertain match candidates instead of forcing a merge.
  `snapshot.py`    `DecisionSnapshot`: the point-in-time information set.
  `actions.py`     Typed, permissioned operations with their input snapshot,
                   policy version, alternatives, prediction, verifier result,
                   human authority and eventual outcome.
  `receipt.py`     The one clock the caller does not own.
  `store.py`       Durable storage on SQLite and PostgreSQL 17, where the
                   boundary is a WHERE clause.

THE ONE PROPERTY THE PACKET RESTS ON, AND WHERE IT IS ENFORCED.
A snapshot at time T cannot see a fact that became known at T+1, through ANY
read path. Four layers, in `snapshot.py`'s docstring in full: a SQL predicate
(`receipt_time < ?`), a construction-time validator, structural absence of any
store reference on the snapshot object, and a content hash the store compares
before an action may cite the snapshot.

WHAT IS **NOT** CLAIMED.
Nothing here is Validated. There is no consented operator data in this
repository; every fixture is synthetic, and the shapes several of these
vocabularies assume about real operator systems are recorded as explicit guesses
in `forge/knowledge/workstreams/packets/MX-ONT-DECISION-SNAPSHOT-013.yaml`. Status: Demonstrated.
"""

from themis.ontology.actions import (
    ActionAlternative,
    ActionOutcome,
    ActionPrediction,
    ActionRecord,
    Authority,
    PermissionDenied,
    UnverifiedActionError,
    VerifierResult,
)
from themis.ontology.events import (
    LATE_ARRIVAL_THRESHOLD_SECONDS,
    LateArrivalReason,
    OntologyEvent,
)
from themis.ontology.graph import (
    IllegalRelationshipError,
    OntologyObject,
    Relationship,
    relationship_is_legal,
)
from themis.ontology.ids import (
    ActionId,
    CandidateSetId,
    FactId,
    ObjectId,
    OntologyEventId,
    OutcomeId,
    RelationshipId,
    SnapshotId,
    new_id,
)
from themis.ontology.provenance import (
    DEFAULT_MATCH_THRESHOLD,
    INTERNAL_DERIVATION_SOURCE,
    ForcedMatchError,
    IdentityResolution,
    MatchCandidate,
    SnapshotFact,
)
from themis.ontology.receipt import (
    ReceiptClockRegressionError,
    ReceiptStamp,
    iso_receipt,
    next_stamp,
    system_utc_clock,
)
from themis.ontology.snapshot import (
    ConflictedValueError,
    DecisionSnapshot,
    SnapshotLeakageError,
    SnapshotPurpose,
    SnapshotScope,
)
from themis.ontology.store import (
    ONTOLOGY_TABLES,
    ForgedSnapshotError,
    IntegrityReport,
    OntologyDatabase,
    OntologyStore,
    SnapshotDriftError,
    UnknownSnapshotError,
)
from themis.ontology.vocab import (
    ACTION_PERMISSIONS,
    RELATIONSHIP_SIGNATURES,
    ActionKind,
    AuthorityKind,
    EventKind,
    FactClass,
    LegalBasis,
    MissingnessReason,
    ObjectKind,
    Permission,
    QualityState,
    ReasonCode,
    RelationshipKind,
    RepairKind,
    SensitivityClass,
    VerifierVerdict,
)

__all__ = [
    # vocabularies
    "ObjectKind",
    "RelationshipKind",
    "RELATIONSHIP_SIGNATURES",
    "EventKind",
    "ActionKind",
    "Permission",
    "ACTION_PERMISSIONS",
    "AuthorityKind",
    "VerifierVerdict",
    "FactClass",
    "QualityState",
    "MissingnessReason",
    "LegalBasis",
    "RepairKind",
    "SensitivityClass",
    "ReasonCode",
    # ids
    "ObjectId",
    "RelationshipId",
    "OntologyEventId",
    "FactId",
    "SnapshotId",
    "ActionId",
    "OutcomeId",
    "CandidateSetId",
    "new_id",
    # receipt
    "ReceiptStamp",
    "ReceiptClockRegressionError",
    "iso_receipt",
    "next_stamp",
    "system_utc_clock",
    # graph
    "OntologyObject",
    "Relationship",
    "IllegalRelationshipError",
    "relationship_is_legal",
    # provenance
    "SnapshotFact",
    "MatchCandidate",
    "IdentityResolution",
    "ForcedMatchError",
    "INTERNAL_DERIVATION_SOURCE",
    "DEFAULT_MATCH_THRESHOLD",
    # events
    "OntologyEvent",
    "LateArrivalReason",
    "LATE_ARRIVAL_THRESHOLD_SECONDS",
    # snapshot
    "DecisionSnapshot",
    "SnapshotScope",
    "SnapshotPurpose",
    "SnapshotLeakageError",
    "ConflictedValueError",
    # actions
    "Authority",
    "ActionAlternative",
    "ActionPrediction",
    "VerifierResult",
    "ActionRecord",
    "ActionOutcome",
    "PermissionDenied",
    "UnverifiedActionError",
    # store
    "OntologyDatabase",
    "OntologyStore",
    "ONTOLOGY_TABLES",
    "SnapshotDriftError",
    "UnknownSnapshotError",
    "ForgedSnapshotError",
    "IntegrityReport",
]
