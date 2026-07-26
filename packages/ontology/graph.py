"""The ontology graph: stateless objects, first-class relationships.

OBJECTS CARRY IDENTITY, NOT STATE. There is no attribute on `OntologyObject`
beyond its kind, its tenant and the external reference it was recognised by.
Everything time-varying -- a vehicle's capacity, a rider's eligibility, a
request's negotiated window -- is a `SnapshotFact` with a receipt time, readable
only through a point-in-time snapshot.

This is the decision the rest of the package rests on, so it is worth stating
what it buys and what it costs.

  It buys: there is nowhere to put an untimestamped attribute. A "dimension
  table" holding today's value of a field a model was trained against as of last
  March is the most common way leakage enters a warehouse, and it enters
  invisibly, because the row looks correct -- it IS correct, just not as of the
  decision instant. Statelessness makes that row unrepresentable.

  It costs: reading "the vehicle's capacity" is a snapshot query rather than an
  attribute access, and a caller who wants the current value must say what
  instant they mean. That is a real ergonomic cost and it is charged
  deliberately, because "what instant do you mean?" is the question the product
  exists to keep asking.

RELATIONSHIPS ARE RECORDS, NOT FOREIGN KEYS. See `RelationshipKind` in
`vocab.py` for the four properties a foreign-key column cannot have (one value,
no time extent, no probability, destructive contradiction) and why the packet's
own vignette needs all four.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.canonical.time import UtcDateTime
from packages.ontology.ids import ObjectId, RelationshipId, TenantId
from packages.ontology.receipt import ReceiptStamp
from packages.ontology.vocab import (
    RELATIONSHIP_SIGNATURES,
    ObjectKind,
    RelationshipKind,
)

__all__ = [
    "OntologyObject",
    "Relationship",
    "IllegalRelationshipError",
    "relationship_is_legal",
]


class IllegalRelationshipError(Exception):
    """An edge whose endpoint kinds the ontology does not permit.

    Its own type because it is a SCHEMA violation, not a data error: the graph's
    shape said this edge cannot exist, and the caller has either mixed up two
    object ids or is modelling something the ontology has no relationship kind
    for yet. Both need a human; neither is retryable.

    NOT a `ValueError`, for the reason `SnapshotLeakageError` records in full:
    pydantic re-raises a `ValueError` from a validator as a `ValidationError`,
    which would make a conformance test asserting on this indistinguishable from
    one that fired on a mistyped field.
    """


def relationship_is_legal(
    kind: RelationshipKind, subject_kind: ObjectKind, object_kind: ObjectKind
) -> bool:
    """Whether `subject_kind --kind--> object_kind` is a permitted edge.

    Looks the signature up rather than defaulting: a relationship kind absent
    from `RELATIONSHIP_SIGNATURES` raises `KeyError` here, so a new kind added
    without a signature fails loudly at first use instead of silently permitting
    every pair. A conformance test also asserts the table is total, so the
    KeyError is a second net rather than the only one.
    """
    subjects, objects = RELATIONSHIP_SIGNATURES[kind]
    return subject_kind in subjects and object_kind in objects


class OntologyObject(BaseModel):
    """One identified thing: a kind, a tenant, an id, and nothing else that can
    go stale.

    `external_ref` is the operator's OWN identifier for the thing, as they write
    it -- a vehicle number like `B-101`, a run signup code, a booking reference.
    It is a plain string and never a typed Milexium id, for the reason
    `packages/canonical/entities.py` records for `vehicle_ref`: it names an
    external system's entity, and typing it as a `VehicleId` would both assert a
    canonical aggregate no operator export creates and force `B-101` through
    UUIDv7 validation it cannot satisfy.

    It is OPTIONAL, and that matters for the identity story: an object minted to
    hold an unresolved match candidate has no external reference of its own yet.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    object_id: ObjectId
    tenant_id: TenantId
    object_kind: ObjectKind
    external_ref: str | None = Field(
        default=None,
        description="The operator's own identifier for this thing. Never a Milexium typed id.",
    )
    source_system: str | None = Field(
        default=None,
        description="Which system this object was first recognised from. None for an object minted internally (e.g. a placeholder for an unresolved identity).",
    )
    receipt: ReceiptStamp = Field(
        description="When Milexium first recognised this object. Writer-assigned."
    )

    @model_validator(mode="after")
    def _validate(self) -> "OntologyObject":
        if self.external_ref is not None and not self.external_ref.strip():
            raise ValueError(
                "external_ref is present but blank: an empty operator reference is "
                "absence wearing a value's clothes, and would match another blank "
                "reference on any join. Omit it instead"
            )
        return self


class Relationship(BaseModel):
    """One asserted edge, with a time extent, an optional probability, and its
    own receipt time.

    ASSERTED, NEVER MUTATED. A relationship that stops holding is not edited: it
    is either bounded by `valid_to` at assertion time, or RETRACTED by a new
    record naming it in `retracts_relationship_id`. Both leave the original
    intact, so a decision taken while the edge held is still explicable -- which
    is the whole reason the episode is the unit of learning.

    TWO TIME AXES, AND THEY DO DIFFERENT WORK.
      * `valid_from` / `valid_to` are VALID time: the period in the operational
        world over which the edge holds. A driver operates a vehicle from 06:00
        to 14:00.
      * `receipt` is TRANSACTION time: when Milexium learned the edge. It is what
        the snapshot boundary is keyed on, and it is routinely LATER than
        `valid_from` -- a shift swap agreed at 05:50 and keyed into the operator's
        system at 09:30 is invisible to a 07:00 decision, correctly, because the
        dispatcher taking that decision did not know about it either.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    relationship_id: RelationshipId
    tenant_id: TenantId
    relationship_kind: RelationshipKind
    subject_kind: ObjectKind
    subject_id: ObjectId
    object_kind: ObjectKind
    object_id: ObjectId
    weight: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "How strongly the edge is asserted, where the assertion is "
            "probabilistic. None means ASSERTED OUTRIGHT, never 1.0 -- the "
            "difference between 'this vehicle performed this assignment' and "
            "'we are certain this vehicle performed this assignment' is the "
            "difference between a record and an estimate."
        ),
    )
    valid_from: UtcDateTime | None = None
    valid_to: UtcDateTime | None = None
    asserted_by: str = Field(
        min_length=1,
        description="Tokenised actor or service that asserted the edge. Never a raw name.",
    )
    retracts_relationship_id: RelationshipId | None = Field(
        default=None,
        description=(
            "The edge this record withdraws. Backward-pointing only, for the "
            "reason RepairKind records: a forward pointer would require mutating "
            "a row an already-taken snapshot has admitted."
        ),
    )
    receipt: ReceiptStamp

    @model_validator(mode="after")
    def _validate(self) -> "Relationship":
        if not relationship_is_legal(
            self.relationship_kind, self.subject_kind, self.object_kind
        ):
            subjects, objects = RELATIONSHIP_SIGNATURES[self.relationship_kind]
            raise IllegalRelationshipError(
                f"{self.relationship_kind.value} may not run from "
                f"{self.subject_kind.value} to {self.object_kind.value}. Permitted: "
                f"{sorted(k.value for k in subjects)} -> "
                f"{sorted(k.value for k in objects)}"
            )
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to < self.valid_from
        ):
            raise ValueError(
                f"relationship valid_to {self.valid_to.isoformat()} precedes valid_from "
                f"{self.valid_from.isoformat()}"
            )
        if (
            self.relationship_kind is RelationshipKind.ASSIGNMENT_FORECLOSED_POOLING_WITH
            and self.weight is None
        ):
            raise ValueError(
                "a foreclosed pooling opportunity must carry a weight: the "
                "opportunity was never certain, and asserting it outright would "
                "turn an estimate of what MIGHT have been possible into a record of "
                "what was"
            )
        if self.subject_id == self.object_id:
            raise ValueError(
                f"{self.relationship_kind.value} from an object to itself; none of the "
                "ontology's relationship kinds is reflexive"
            )
        return self

    def holds_at(self, instant: UtcDateTime) -> bool:
        """Whether the edge holds in VALID time at `instant`.

        Says nothing about whether it was KNOWN at `instant` -- that is the
        receipt boundary's job, applied separately by the snapshot. Keeping the
        two questions in two methods is deliberate: conflating "was true" with
        "was known" is the error the whole package is built to prevent, and a
        single `active_at` doing both would be the place it crept back in.

        Half-open: `valid_from <= instant < valid_to`, so an edge ending at
        14:00 and one beginning at 14:00 do not both hold at 14:00.
        """
        if self.valid_from is not None and instant < self.valid_from:
            return False
        if self.valid_to is not None and instant >= self.valid_to:
            return False
        return True
