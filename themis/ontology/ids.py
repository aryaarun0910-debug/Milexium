"""Typed identifiers for Ontology v1.

ONE VALIDATION RULE, NOT TWO. Every id here subclasses
`themis.canonical.ids._TypedId`, so a Milexium identifier means the same thing
(a lowercase canonical UUIDv7 string, RFC 9562) in this package as it does in the
canonical one, and `new_id(...)` is the single minting function. Importing a
private name across a package boundary is deliberate and is the lesser evil: the
alternative is a second copy of `_validate_uuid_string`, and two copies of a
validation rule is exactly the drift `themis/canonical/vocab.py`'s docstring
warns about. A conformance test pins the inheritance so a future refactor cannot
quietly fork it.

WHICH IDS ARE **NOT** HERE, AND WHY. `TenantId`, `RequestId`, `VehicleId`,
`DriverId`, `PolicyId`, `BlockId`, `ScheduleRunId`, `ModelVersionId` and
`DecisionEventId` already exist in `themis/canonical/ids.py` and are re-exported
from here unchanged. Minting parallel ontology copies would create two ids for one
thing and guarantee that a join between the ontology and the canonical store
eventually compares the wrong pair.

WHY EACH NEW KIND IS ITS OWN TYPE rather than a shared "some ontology id". The
ontology graph REFERENCES ITSELF: an `ActionRecord` names a `SnapshotId`, a
`SnapshotFact` names a `FactId` it repairs, a `Relationship` names two object
ids. With one opaque type, passing a snapshot id where a fact id belongs would
type-check and store a dangling reference -- the same reasoning
`themis/canonical/ids.DeadheadSegmentId` records for the scheduling family.
"""

from __future__ import annotations

# `_TypedId` is private to themis/canonical by name but public by intent: it is
# the repository's one definition of "a validated Milexium identifier". See the
# module docstring for why this import is preferred over a second copy.
from themis.canonical.ids import (  # noqa: PLC2701
    PLATFORM_TENANT_ID,
    BlockId,
    DecisionEventId,
    DriverId,
    ModelVersionId,
    PolicyId,
    RequestId,
    ScheduleRunId,
    TenantId,
    VehicleId,
    _TypedId,
    new_id,
)

__all__ = [
    # re-exported from themis/canonical, never re-declared
    "PLATFORM_TENANT_ID",
    "BlockId",
    "DecisionEventId",
    "DriverId",
    "ModelVersionId",
    "PolicyId",
    "RequestId",
    "ScheduleRunId",
    "TenantId",
    "VehicleId",
    "new_id",
    # new to the ontology
    "ObjectId",
    "RelationshipId",
    "OntologyEventId",
    "FactId",
    "SnapshotId",
    "ActionId",
    "OutcomeId",
    "CandidateSetId",
]


class ObjectId(_TypedId):
    """Identifies one `OntologyObject` -- any of the 28 `ObjectKind`s.

    ONE ID TYPE ACROSS ALL OBJECT KINDS, deliberately, and this is the one place
    the package does NOT split by kind. An object's kind is carried as a field
    beside its id and is validated against the relationship legality table on
    every edge, so the protection a per-kind id type would give (you cannot pass
    a vehicle where a driver belongs) is already provided -- by a check that also
    works for the ontology's actual traversal pattern, which is polymorphic. A
    28-way split would additionally make `Relationship` ungeneric: its endpoints
    can each be one of several kinds, so its fields would have to be typed as a
    28-member union that no validator could usefully narrow.
    """


class RelationshipId(_TypedId):
    """Identifies one asserted `Relationship` edge."""


class OntologyEventId(_TypedId):
    """Identifies one `OntologyEvent`.

    Distinct from `themis.canonical.ids.DecisionEventId`, which identifies a
    row of the canonical decision ledger. The two logs record different things
    (this one records what the WORLD did; that one records what the SCHEDULER
    decided) and are chained separately, so one id kind for both would let a row
    of one be cited as evidence from the other.
    """


class FactId(_TypedId):
    """Identifies one `SnapshotFact` -- a single field-level claim with its full
    provenance envelope. Also the target of `repairs_fact_id`."""


class SnapshotId(_TypedId):
    """Identifies one `DecisionSnapshot`: a point-in-time information set.

    The id an `ActionRecord` cites to say "this is what I could see". It is the
    join key between a decision and its inputs, so it is the one id whose
    absence would make an action unauditable -- `ActionRecord.input_snapshot_id`
    is therefore required, with no default.
    """


class ActionId(_TypedId):
    """Identifies one `ActionRecord` -- one typed, permissioned operation."""


class OutcomeId(_TypedId):
    """Identifies one `ActionOutcome` -- what eventually happened after an action.

    Its own key rather than reusing the action's, because an action may have
    several outcomes measured at different horizons (the pickup was 14 minutes
    late; the rider complained three days later; the trip was re-billed a month
    later), and each is a separate record with its own receipt time.
    """


class CandidateSetId(_TypedId):
    """Identifies one `IdentityResolution` -- a set of match candidates for one
    uncertain identity, retained WITH their probabilities rather than collapsed
    into a single record."""
