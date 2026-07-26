"""`DecisionSnapshot`: the point-in-time INFORMATION SET behind one decision.

WHAT THIS IS, IN ONE SENTENCE THAT IS EASY TO GET WRONG.
A `DecisionSnapshot` holds what could reasonably have been KNOWN at the decision
instant -- not what turned out to be true. An ordinary warehouse preserves
historical outcomes; if you ask it "what did the vehicle's capacity say in
March?" it answers with March's value, corrected by everything learned since.
That answer is more accurate and completely useless for learning: a model
trained on it has seen the future, and the model will look excellent right up
until it is deployed against a present that has not been corrected yet.

THE BOUNDARY, AND THE FOUR LAYERS THAT ENFORCE IT.

  Layer 1 -- SQL. `packages/ontology/store.OntologyStore.snapshot_at` selects
  with `receipt_time < ?` as a WHERE-clause predicate over fixed-width ISO-8601
  UTC text (`packages/ontology/receipt.iso_receipt`, imported from
  `packages/core/feature_store.py` so there is one such convention in the
  repository, not two). A later row is never fetched and then filtered in
  Python -- it is never fetched at all. This is the same strict `<` ADR-0034
  established for the feature store, in the same spelling, for the same reason.

  Layer 2 -- CONSTRUCTION. This class re-checks every admitted item against
  `as_of` in a model validator and raises `SnapshotLeakageError`. The check is
  redundant with layer 1 by design: it means an in-memory snapshot assembled
  without a database obeys the identical rule, and it means the boundary is
  asserted by two independent implementations rather than one.

  Layer 3 -- STRUCTURE. A `DecisionSnapshot` holds NO REFERENCE TO A STORE. It
  is a frozen value with tuple-valued collections, and there is no method on it
  that can issue a query. This is what closes the read path that a
  boundary-checked-on-construction object would otherwise leave wide open: a
  `snapshot.refresh()` or a lazily-loaded attribute would satisfy every
  construction-time check and then read the present. A conformance test walks
  this module's AST and asserts it imports nothing from `store`, holds no
  callable field, and contains no clock read.

  Layer 4 -- CONTENT HASH. `content_hash` is a computed property over the
  admitted content INCLUDING `as_of`, and `packages/ontology/store.py` compares
  it against the value persisted when the snapshot was taken. This exists
  because pydantic's `model_copy(update=...)` deliberately skips validators: a
  forged snapshot with extra facts, or with a later `as_of`, is constructible in
  one line and passes layer 2 because layer 2 never runs. It does not pass layer
  4, and an action citing it is refused.

WHAT A SNAPSHOT DOES **NOT** DO.
It does not decide what should have been known -- only what WAS known, by
receipt time. If an operator's system knew a vehicle was unavailable at 10:30
and did not export it until 11:00, a 10:45 decision snapshot correctly does not
contain it, and a replay scoring that decision must not penalise it. Recovering
the operator-internal knowledge time (as distinct from Milexium's receipt time)
requires a field their export does not currently carry; that is named in the
packet as the single most valuable thing to ask a first operator for.

STATUS: Demonstrated. Every fixture is synthetic; there is no consented operator
data in this repository, so nothing here is Validated.
"""

from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.canonical.events import canonical_json
from packages.canonical.time import UtcDateTime
from packages.ontology.events import OntologyEvent
from packages.ontology.graph import Relationship
from packages.ontology.ids import ObjectId, SnapshotId, TenantId
from packages.ontology.provenance import FactValue, IdentityResolution, SnapshotFact
from packages.ontology.receipt import ReceiptStamp
from packages.ontology.vocab import (
    EventKind,
    MissingnessReason,
    RelationshipKind,
    SensitivityClass,
)

__all__ = [
    "SnapshotPurpose",
    "SnapshotScope",
    "DecisionSnapshot",
    "SnapshotLeakageError",
    "ConflictedValueError",
    "SNAPSHOT_CONTENT_HASH_VERSION",
]

SNAPSHOT_CONTENT_HASH_VERSION = "mx-ont-snapshot-1"
"""Version tag mixed into every content hash.

Present so that a future change to what the hash covers cannot silently make old
and new hashes comparable. A stored hash from an earlier version will simply not
match a recomputation under a later one, which is a loud failure rather than a
quiet false equality."""


class SnapshotLeakageError(Exception):
    """An item was admitted to a snapshot that was not knowable at its `as_of`.

    Its own exception type, and the most important one in this package: every
    leakage probe in `conformance/property-tests/test_decision_snapshot.py`
    asserts on THIS type, so a probe cannot pass by catching an incidental
    error from somewhere else and calling it a refusal.

    IT DELIBERATELY DOES **NOT** INHERIT FROM `ValueError`, and that is not
    stylistic. Pydantic v2 catches `ValueError` (and `AssertionError`) raised
    inside a validator and re-raises it as a `ValidationError`. A leakage error
    that inherited from `ValueError` would therefore reach the caller wearing the
    same type as a mistyped field -- and a test asserting `pytest.raises(
    ValidationError)` would pass for ANY validation failure, including one that
    fired before the boundary check ever ran. That is precisely the vacuous test
    this repository keeps finding. Inheriting from `Exception` makes pydantic
    propagate it unwrapped, so "the boundary refused this" is distinguishable
    from "the input was malformed" at every call site.
    """


class ConflictedValueError(ValueError):
    """Two sources disagree about a value and neither was chosen.

    Raised by `value_of` rather than resolved silently. Picking one, or
    averaging, is a decision with consequences (which source do you believe about
    a wheelchair securement position?) and it must be made by a caller who can
    be held to it, not by an accessor. The disagreeing facts are all retained and
    reachable through `facts_for`.
    """


class SnapshotPurpose(str, Enum):
    """What the snapshot is for. Governs which facts may enter it.

    DISPATCH AND TRAINING DO NOT HAVE THE SAME FOOTING, and this enum is where
    that is enforced rather than remembered. A fact whose lawful basis was never
    established can still be acted on operationally -- the operator holds it and
    asked us to dispatch with it. Building a durable statistical asset out of it
    is a different act with different consent. `MODEL_TRAINING` therefore admits
    only facts where `SnapshotFact.trainable` holds, applied at snapshot
    construction so a downstream feature builder cannot forget it.
    """

    OPERATIONAL_DISPATCH = "operational_dispatch"
    MODEL_TRAINING = "model_training"
    EVIDENCE_EXPORT = "evidence_export"
    REPLAY = "replay"


class SnapshotScope(BaseModel):
    """Which objects (and optionally which attributes) a snapshot covers.

    PERSISTED WITH THE SNAPSHOT, and that is what makes a snapshot reproducible
    rather than merely recorded. `OntologyStore.load_snapshot` re-derives the
    content from the store using the stored `(as_of, scope, purpose)` and
    compares the recomputed content hash against the one stored at the time. If
    the two ever differ, something has been written into the past -- and since
    receipt monotonicity is supposed to make that impossible, the reload path is
    a leak DETECTOR, not just a read.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_ids: tuple[ObjectId, ...] = Field(
        min_length=1,
        description=(
            "The objects in the episode. Required and non-empty: an unscoped "
            "snapshot would be 'everything the tenant knows', which is neither "
            "reproducible at reasonable cost nor meaningful as an information "
            "set -- a dispatcher deciding one trip did not consider every row."
        ),
    )
    attributes: tuple[str, ...] | None = Field(
        default=None,
        description="Attribute allow-list, or None for every attribute of the scoped objects.",
    )

    @model_validator(mode="after")
    def _validate(self) -> "SnapshotScope":
        if len(set(self.subject_ids)) != len(self.subject_ids):
            raise ValueError("scope names the same object twice")
        if self.attributes is not None:
            if not self.attributes:
                raise ValueError(
                    "an empty attribute allow-list admits nothing. Use None for "
                    "'every attribute' -- an empty tuple is almost always a bug "
                    "that would produce a silently empty snapshot"
                )
            if len(set(self.attributes)) != len(self.attributes):
                raise ValueError("scope names the same attribute twice")
        return self

    def canonical(self) -> dict:
        """Deterministic form for hashing and storage. Sorted, so two scopes
        naming the same things in different orders are the same scope."""
        return {
            "subject_ids": sorted(str(s) for s in self.subject_ids),
            "attributes": (
                None if self.attributes is None else sorted(self.attributes)
            ),
        }


class DecisionSnapshot(BaseModel):
    """The frozen information set behind one decision.

    Every collection is a TUPLE, not a list or a dict. Pydantic's `frozen=True`
    prevents attribute rebinding but does NOT deep-freeze a mutable container:
    with `facts: list[...]` a caller could `snapshot.facts.append(...)` a
    future fact into a validated snapshot and every construction-time check
    would already have passed. Tuples make that a `TypeError`. Every read path
    that returns a mapping builds a FRESH dict, so mutating what a caller was
    handed cannot reach back into the snapshot either.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: SnapshotId
    tenant_id: TenantId
    as_of: UtcDateTime = Field(
        description=(
            "THE DECISION INSTANT. The boundary: an item is admitted only if its "
            "receipt time is STRICTLY earlier. Supplied by the caller, because "
            "only the caller knows when the decision is being taken -- but see "
            "`taken_receipt`, which the writer stamps and which bounds it."
        )
    )
    taken_receipt: ReceiptStamp = Field(
        description=(
            "When the snapshot itself was materialised. Writer-assigned, and "
            "never earlier than `as_of`: a snapshot cannot be taken as of the "
            "future, which would otherwise be a way to pre-commit to an "
            "information set and fill it in afterwards."
        )
    )
    purpose: SnapshotPurpose
    scope: SnapshotScope

    facts: tuple[SnapshotFact, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    events: tuple[OntologyEvent, ...] = ()
    identity_resolutions: tuple[IdentityResolution, ...] = ()

    derived_from: SnapshotId | None = Field(
        default=None,
        description="The snapshot this one was projected from (see `redacted`/`for_training`). A projection is a new snapshot, never an edit of its source.",
    )

    # -- construction-time boundary (layer 2) ------------------------------- #
    @model_validator(mode="after")
    def _validate(self) -> "DecisionSnapshot":
        if self.taken_receipt.receipt_time < self.as_of:
            raise SnapshotLeakageError(
                f"snapshot as_of {self.as_of.isoformat()} is later than the instant it "
                f"was taken ({self.taken_receipt.receipt_time.isoformat()}): a snapshot "
                "cannot be taken as of the future"
            )
        for label, items in (
            ("fact", self.facts),
            ("relationship", self.relationships),
            ("event", self.events),
            ("identity resolution", self.identity_resolutions),
        ):
            for item in items:
                if not item.receipt.precedes(self.as_of):
                    raise SnapshotLeakageError(
                        f"{label} received at "
                        f"{item.receipt.receipt_time.isoformat()} (sequence "
                        f"{item.receipt.receipt_sequence}) is not strictly earlier than "
                        f"the decision instant {self.as_of.isoformat()}: it could not "
                        "have been known when the decision was taken"
                    )
        for item in (
            *self.facts,
            *self.relationships,
            *self.events,
            *self.identity_resolutions,
        ):
            if str(item.tenant_id) != str(self.tenant_id):
                raise SnapshotLeakageError(
                    f"snapshot for tenant {self.tenant_id} admitted an item belonging "
                    f"to tenant {item.tenant_id}"
                )
        scoped = {str(s) for s in self.scope.subject_ids}
        for fact in self.facts:
            if str(fact.subject_id) not in scoped:
                raise ValueError(
                    f"fact about {fact.subject_id} is outside the snapshot's declared "
                    "scope; a snapshot that silently exceeds its scope is not "
                    "reproducible from it"
                )
        if self.purpose is SnapshotPurpose.MODEL_TRAINING:
            offending = [f.attribute for f in self.facts if not f.trainable]
            if offending:
                raise ValueError(
                    "a model-training snapshot may not contain facts with no "
                    f"established lawful basis: {sorted(set(offending))}. Use "
                    "SnapshotPurpose.OPERATIONAL_DISPATCH, or establish the basis"
                )
        return self

    # -- layer 4: content hash ---------------------------------------------- #
    @property
    def content_hash(self) -> str:
        """SHA-256 over the admitted content AND the boundary that admitted it.

        A COMPUTED PROPERTY, NOT A STORED FIELD, and the difference is the whole
        defence. A stored field would be carried along unchanged by
        `model_copy(update={"facts": ...})` -- which skips validators -- and a
        forged snapshot would present a hash that matched the store's. Computing
        it on access means a forgery changes it, and the store's comparison
        catches it.

        `as_of` is inside the hash. Without it, `model_copy(update={"as_of":
        later})` would produce a snapshot claiming a later decision instant with
        an unchanged hash, and an action could then cite an information set from
        before the decision it claims to have informed.
        """
        body = {
            "v": SNAPSHOT_CONTENT_HASH_VERSION,
            "snapshot_id": str(self.snapshot_id),
            "tenant_id": str(self.tenant_id),
            "as_of": self.as_of.isoformat(),
            "purpose": self.purpose.value,
            "scope": self.scope.canonical(),
            "facts": sorted(str(f.fact_id) for f in self.facts),
            "relationships": sorted(str(r.relationship_id) for r in self.relationships),
            "events": sorted(str(e.event_id) for e in self.events),
            "identities": sorted(
                str(i.candidate_set_id) for i in self.identity_resolutions
            ),
            "derived_from": None if self.derived_from is None else str(self.derived_from),
        }
        return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()

    def verify(self) -> None:
        """Re-run the boundary checks on an already-constructed snapshot.

        Exists because layer 2 runs only when a validator runs, and
        `model_copy(update=...)` is a documented pydantic path that skips them.
        This method can be called on any snapshot however it was produced, so a
        caller handed a snapshot from elsewhere is not obliged to trust that it
        was ever validated.

        Deliberately re-implements the check rather than calling `_validate`: a
        validator returns `self` and is easy to accidentally make a no-op, and a
        no-op verifier is worse than none. Raises `SnapshotLeakageError`.
        """
        if self.taken_receipt.receipt_time < self.as_of:
            raise SnapshotLeakageError(
                "snapshot claims to have been taken before its own as_of"
            )
        for item in (
            *self.facts,
            *self.relationships,
            *self.events,
            *self.identity_resolutions,
        ):
            if item.receipt.receipt_time >= self.as_of:
                raise SnapshotLeakageError(
                    f"item received at {item.receipt.receipt_time.isoformat()} is not "
                    f"strictly before the decision instant {self.as_of.isoformat()}"
                )
            if str(item.tenant_id) != str(self.tenant_id):
                raise SnapshotLeakageError(
                    "snapshot contains an item belonging to another tenant"
                )

    # ------------------------------------------------------------------ #
    # READ PATHS
    #
    # Every method below is a pure projection over the tuples above. None of
    # them touches a store, a clock, or any state outside `self` -- which is
    # what makes "the snapshot cannot see the future" a property of the OBJECT
    # rather than of the one query that built it.
    #
    # `conformance/property-tests/test_decision_snapshot.py` enumerates this
    # class's public surface BY REFLECTION and fails if any member is not either
    # probed for leakage or explicitly listed as a non-read path. Adding a read
    # path without a probe breaks the suite; that is the anti-vacuity device for
    # the load-bearing test.
    # ------------------------------------------------------------------ #
    def subjects(self) -> frozenset[ObjectId]:
        """Every object this snapshot holds a fact about."""
        return frozenset(f.subject_id for f in self.facts)

    def attributes_of(self, subject_id: ObjectId) -> frozenset[str]:
        return frozenset(
            f.attribute for f in self.facts if str(f.subject_id) == str(subject_id)
        )

    def facts_for(
        self, subject_id: ObjectId, attribute: str | None = None
    ) -> tuple[SnapshotFact, ...]:
        """Every admitted fact about one object, optionally one attribute.

        Returns ALL of them, one per contributing source system -- not a single
        winner. Two sources disagreeing is a real state of the world and
        collapsing it here would hide it from the only code positioned to handle
        it (see `ConflictedValueError`).
        """
        return tuple(
            f
            for f in self.facts
            if str(f.subject_id) == str(subject_id)
            and (attribute is None or f.attribute == attribute)
        )

    def value_of(self, subject_id: ObjectId, attribute: str) -> FactValue:
        """The single agreed value, or None if it is absent/unknown.

        Raises `ConflictedValueError` when sources disagree. Never averages,
        never picks. Use `facts_for` to see the disagreement and decide.
        """
        candidates = [f for f in self.facts_for(subject_id, attribute) if f.is_known]
        if not candidates:
            return None
        distinct = {f.value for f in candidates}
        if len(distinct) > 1:
            raise ConflictedValueError(
                f"{attribute!r} on {subject_id} has {len(distinct)} distinct values "
                f"from {len({f.source_system for f in candidates})} sources: "
                f"{sorted(map(repr, distinct))}. Choose deliberately -- this accessor "
                "will not choose for you"
            )
        return candidates[0].value

    def missing(self) -> tuple[tuple[ObjectId, str, MissingnessReason], ...]:
        """Every absent field with the reason it is absent.

        The view that makes 'null' analysable. An operator whose
        `NOT_YET_KNOWN` count collapses to zero the moment a trip completes has
        a decision-time export; one whose count is zero from the start does not,
        and is exporting outcomes rather than information sets.
        """
        return tuple(
            (f.subject_id, f.attribute, f.missing_reason)
            for f in self.facts
            if f.missing_reason is not None
        )

    def conflicts(self) -> tuple[tuple[ObjectId, str], ...]:
        """(object, attribute) pairs where admitted sources disagree."""
        seen: dict[tuple[str, str], set[FactValue]] = {}
        for f in self.facts:
            if f.is_known:
                seen.setdefault((str(f.subject_id), f.attribute), set()).add(f.value)
        return tuple(
            (ObjectId(sid), attr)
            for (sid, attr), values in sorted(seen.items())
            if len(values) > 1
        )

    def relationships_of(
        self,
        subject_id: ObjectId | None = None,
        kind: RelationshipKind | None = None,
    ) -> tuple[Relationship, ...]:
        return tuple(
            r
            for r in self.relationships
            if (subject_id is None or str(r.subject_id) == str(subject_id))
            and (kind is None or r.relationship_kind is kind)
        )

    def related(
        self, subject_id: ObjectId, kind: RelationshipKind
    ) -> tuple[ObjectId, ...]:
        """The objects reachable from `subject_id` by `kind`, at `as_of` in BOTH
        time axes: received before the decision instant (guaranteed by
        construction) and holding in valid time at it (checked here).

        A retraction received after `as_of` is correctly still absent, so this
        answers "who did the dispatcher believe was driving?" rather than "who
        do we now think was driving?".
        """
        return tuple(
            r.object_id
            for r in self.relationships_of(subject_id, kind)
            if r.holds_at(self.as_of)
        )

    def events_of(self, kind: EventKind | None = None) -> tuple[OntologyEvent, ...]:
        """Admitted events, in receipt order -- the order Milexium learned them,
        which is the order a dispatcher would have seen them, NOT the order they
        occurred in. A late-arriving no-show sorts where it was learned."""
        selected = [e for e in self.events if kind is None or e.event_kind is kind]
        return tuple(sorted(selected, key=lambda e: e.receipt.receipt_sequence))

    def unresolved_identities(self) -> tuple[IdentityResolution, ...]:
        """Identities that had not been resolved as of the decision instant,
        with every candidate and probability retained."""
        return tuple(r for r in self.identity_resolutions if not r.is_resolved)

    def feature_vector(self) -> dict[str, float]:
        """The numeric projection a model consumes.

        THE MOST DANGEROUS READ PATH IN THE PACKAGE, and the reason it is
        implemented here rather than in a feature-engineering module: this is
        where a future value would be laundered into a float and lose every trace
        of where it came from. It is a projection of the ALREADY-BOUNDED tuples
        and cannot reach anything else.

        Excludes non-trainable facts and free text, so a dispatch snapshot
        cannot be turned into training data by calling this on it. Keys are
        `{object_id}:{attribute}`; conflicted attributes are OMITTED rather than
        averaged, and their omission is visible through `conflicts()`.
        """
        conflicted = {(str(s), a) for s, a in self.conflicts()}
        out: dict[str, float] = {}
        for f in self.facts:
            if not f.is_known or not f.trainable:
                continue
            if f.sensitivity is SensitivityClass.FREE_TEXT:
                continue
            if (str(f.subject_id), f.attribute) in conflicted:
                continue
            if isinstance(f.value, bool):
                out[f"{f.subject_id}:{f.attribute}"] = 1.0 if f.value else 0.0
            elif isinstance(f.value, (int, float)):
                out[f"{f.subject_id}:{f.attribute}"] = float(f.value)
        return out

    def provenance_manifest(self) -> tuple[dict, ...]:
        """One row per admitted fact carrying its full envelope.

        The evidence view: what was known, from where, how good it was, on what
        basis it was held, and when it arrived. Values are deliberately NOT
        included -- a manifest is about the provenance of the information set and
        is the artefact most likely to leave the tenant boundary, so it carries
        no personal data by construction rather than by a redaction step someone
        has to remember to run.
        """
        return tuple(
            {
                "fact_id": str(f.fact_id),
                "subject_kind": f.subject_kind.value,
                "subject_id": str(f.subject_id),
                "attribute": f.attribute,
                "fact_class": f.fact_class.value,
                "known": f.is_known,
                "missing_reason": (
                    None if f.missing_reason is None else f.missing_reason.value
                ),
                "source_system": f.source_system,
                "source_record_id": f.source_record_id,
                "event_time": None if f.event_time is None else f.event_time.isoformat(),
                "receipt_time": f.receipt.receipt_time.isoformat(),
                "receipt_sequence": f.receipt.receipt_sequence,
                "quality": f.quality.value,
                "confidence": f.confidence,
                "repair_kind": f.repair_kind.value,
                "repairs_fact_id": (
                    None if f.repairs_fact_id is None else str(f.repairs_fact_id)
                ),
                "sensitivity": f.sensitivity.value,
                "special_category": f.special_category,
                "legal_basis": f.legal_basis.value,
            }
            for f in sorted(self.facts, key=lambda f: f.receipt.receipt_sequence)
        )

    def latest_receipt(self) -> ReceiptStamp | None:
        """The newest stamp in the snapshot -- necessarily strictly before
        `as_of`. Useful for asserting how stale an information set was, which is
        a real operational quantity: a decision taken on twenty-minute-old
        vehicle positions is a different decision from one taken on live ones."""
        stamps = [
            item.receipt
            for item in (
                *self.facts,
                *self.relationships,
                *self.events,
                *self.identity_resolutions,
            )
        ]
        if not stamps:
            return None
        return max(stamps, key=lambda s: s.receipt_sequence)

    def redacted(self) -> "DecisionSnapshot":
        """A projection with identity, precise-location and free-text values
        suppressed, for export beyond the tenant boundary.

        A NEW snapshot with a new id and `derived_from` set -- never an edit.
        Its `as_of` is unchanged, so the redaction cannot be used to widen the
        information set, and its content hash necessarily differs from its
        source's (different fact ids), so the two can never be confused.
        """
        protected = {
            SensitivityClass.IDENTITY,
            SensitivityClass.PRECISE_LOCATION,
            SensitivityClass.FREE_TEXT,
        }
        return self.model_validate(
            {
                **self.model_dump(),
                "snapshot_id": str(_derived_id(self.snapshot_id, "redacted")),
                "derived_from": str(self.snapshot_id),
                "purpose": SnapshotPurpose.EVIDENCE_EXPORT.value,
                "facts": [
                    (f.redacted() if (f.sensitivity in protected and f.is_known) else f).model_dump()
                    for f in self.facts
                ],
            }
        )

    def for_training(self) -> "DecisionSnapshot":
        """A projection containing only facts with an established lawful basis.

        Again a new snapshot, again with `as_of` unchanged. The filter is applied
        HERE, at the boundary between the operational record and the statistical
        asset, so a feature builder downstream cannot reach a fact this excluded
        -- it is not in the object it was handed.
        """
        return self.model_validate(
            {
                **self.model_dump(),
                "snapshot_id": str(_derived_id(self.snapshot_id, "training")),
                "derived_from": str(self.snapshot_id),
                "purpose": SnapshotPurpose.MODEL_TRAINING.value,
                "facts": [f.model_dump() for f in self.facts if f.trainable],
            }
        )


def _derived_id(source: SnapshotId, label: str) -> SnapshotId:
    """A deterministic child id for a projection.

    DETERMINISTIC rather than freshly minted, so redacting the same snapshot
    twice yields the same id and an evidence export is byte-reproducible. Built
    by hashing the parent id and the label into the UUIDv7 layout (version 7,
    RFC-4122 variant) so it satisfies the same `_TypedId` validation as every
    other id and needs no exemption -- the same trick
    `packages/canonical/ids.PLATFORM_TENANT_ID` uses to be a valid UUIDv7
    without being a minted one.
    """
    digest = hashlib.sha256(f"{source}:{label}".encode("utf-8")).digest()
    b = bytearray(digest[:16])
    b[6] = (b[6] & 0x0F) | 0x70  # version 7
    b[8] = (b[8] & 0x3F) | 0x80  # RFC-4122 variant
    hexed = bytes(b).hex()
    return SnapshotId(
        f"{hexed[0:8]}-{hexed[8:12]}-{hexed[12:16]}-{hexed[16:20]}-{hexed[20:32]}"
    )
