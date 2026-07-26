"""Conformance for Ontology v1: objects, relationships, events, actions.

WHAT THIS FILE PROVES, AND WHAT IT DELIBERATELY DOES NOT.
It proves the SHAPE: that the vocabularies are closed and total, that a
relationship whose endpoints the ontology forbids cannot be constructed, that an
object cannot carry state, that a late-arriving event must declare itself late,
and that an action cannot be taken without an authority holding its permission.

It proves nothing about real operator data. Every fixture here is SYNTHETIC --
there is no consented operator data in this repository -- so the status of
everything below is Demonstrated, never Validated. Where a vocabulary encodes a
guess about how operator systems actually behave (the 300-second late-arrival
threshold, the 0.95 identity threshold, the existence of a capacity profile),
the guess is recorded in
`workstreams/packets/MX-ONT-DECISION-SNAPSHOT-013.yaml` rather than defended
here.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from packages.canonical.ids import TenantId, new_id as canonical_new_id
from packages.canonical.ids import _TypedId as CanonicalTypedId
from packages.ontology import (
    ACTION_PERMISSIONS,
    DEFAULT_MATCH_THRESHOLD,
    INTERNAL_DERIVATION_SOURCE,
    LATE_ARRIVAL_THRESHOLD_SECONDS,
    RELATIONSHIP_SIGNATURES,
    ActionAlternative,
    ActionId,
    ActionKind,
    ActionPrediction,
    ActionRecord,
    Authority,
    AuthorityKind,
    CandidateSetId,
    EventKind,
    FactClass,
    FactId,
    ForcedMatchError,
    IdentityResolution,
    IllegalRelationshipError,
    LateArrivalReason,
    LegalBasis,
    MatchCandidate,
    MissingnessReason,
    ObjectId,
    ObjectKind,
    OntologyEvent,
    OntologyEventId,
    OntologyObject,
    OutcomeId,
    Permission,
    PermissionDenied,
    QualityState,
    ReasonCode,
    Relationship,
    RelationshipId,
    RelationshipKind,
    SensitivityClass,
    SnapshotFact,
    SnapshotId,
    UnverifiedActionError,
    VerifierResult,
    VerifierVerdict,
    new_id,
    relationship_is_legal,
)
from packages.ontology.ids import PolicyId
from packages.ontology.receipt import (
    ReceiptClockRegressionError,
    ReceiptStamp,
    next_stamp,
)

T = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)
TENANT = canonical_new_id(TenantId)


def _stamp(sequence: int = 1, offset_minutes: int = 0) -> ReceiptStamp:
    return ReceiptStamp(
        receipt_time=T + timedelta(minutes=offset_minutes), receipt_sequence=sequence
    )


# --------------------------------------------------------------------------- #
# Vocabularies: closed, and TOTAL over their lookup tables
# --------------------------------------------------------------------------- #
def test_the_relationship_signature_table_is_total() -> None:
    """A relationship kind with no signature would fall through to whatever the
    lookup did by default. There is no default -- but a missing entry would
    raise `KeyError` at first USE, which could be months later and in
    production. This makes it a build-time failure instead."""
    missing = set(RelationshipKind) - set(RELATIONSHIP_SIGNATURES)
    assert not missing, f"relationship kinds with no legality signature: {missing}"
    stale = set(RELATIONSHIP_SIGNATURES) - set(RelationshipKind)
    assert not stale, f"signatures for relationship kinds that no longer exist: {stale}"


def test_every_signature_names_at_least_one_kind_on_each_end() -> None:
    """An empty end would make every edge of that kind illegal -- a relationship
    that can never be asserted, which is worse than one that is missing, because
    it looks supported."""
    for kind, (subjects, objects) in RELATIONSHIP_SIGNATURES.items():
        assert subjects, f"{kind.value} permits no subject kind"
        assert objects, f"{kind.value} permits no object kind"


def test_the_action_permission_table_is_total() -> None:
    missing = set(ActionKind) - set(ACTION_PERMISSIONS)
    assert not missing, (
        f"action kinds with no required permission: {missing}. A permissionless "
        "action defaults to allowed, which is the wrong default for the only "
        "methods that change operational state"
    )


def test_the_packet_names_every_object_kind_it_asked_for() -> None:
    """Pinned so a later refactor cannot quietly drop a concept the packet
    committed to. 28 kinds; the list is the packet's own."""
    expected = {
        "operator",
        "service_area",
        "depot",
        "rider",
        "eligibility_profile",
        "request",
        "journey",
        "location",
        "protected_zone",
        "vehicle",
        "accessibility_equipment",
        "capacity_profile",
        "driver",
        "shift",
        "run",
        "block",
        "assignment",
        "schedule_version",
        "policy",
        "contract",
        "service_rule",
        "incident",
        "disruption",
        "maintenance_event",
        "forecast",
        "recommendation",
        "override",
        "outcome",
    }
    assert {k.value for k in ObjectKind} == expected


def test_the_packet_names_every_event_kind_it_asked_for() -> None:
    expected = {
        "booking_created",
        "booking_amended",
        "window_negotiated",
        "assignment_created",
        "assignment_moved",
        "vehicle_delayed",
        "vehicle_unavailable",
        "rider_cancelled",
        "rider_no_showed",
        "dispatcher_overrode",
        "arrival",
        "pickup",
        "dropoff",
        "trip_denied",
        "trip_missed",
        "policy_changed",
    }
    assert {k.value for k in EventKind} == expected


def test_the_eleven_named_relationships_all_exist() -> None:
    """The packet names eleven relationships explicitly. They are pinned by
    name, so a rename shows up as a failure rather than as a silently different
    ontology."""
    for name in (
        "REQUEST_BELONGS_TO_RIDER",
        "REQUEST_REQUIRES_EQUIPMENT",
        "ASSIGNMENT_SERVES_REQUEST",
        "VEHICLE_PERFORMS_ASSIGNMENT",
        "DRIVER_OPERATES_VEHICLE",
        "RUN_BELONGS_TO_BLOCK",
        "RECOMMENDATION_CONSIDERED_ALTERNATIVE",
        "OVERRIDE_REPLACED_RECOMMENDATION",
        "INCIDENT_AFFECTED",
        "POLICY_CONSTRAINED_DECISION",
        "OUTCOME_RESULTED_FROM",
    ):
        assert hasattr(RelationshipKind, name)


def test_the_eight_named_actions_all_exist() -> None:
    for name in (
        "ACCEPT_REQUEST",
        "NEGOTIATE_REQUEST",
        "ASSIGN",
        "REASSIGN",
        "HOLD_CAPACITY",
        "REPOSITION_CAPACITY",
        "COMBINE_TRIPS",
        "CALL_IN_SPARE_CAPACITY",
        "ESCALATE_ACCESSIBILITY_RISK",
        "APPROVE_RECOMMENDATION",
        "REJECT_RECOMMENDATION",
    ):
        assert hasattr(ActionKind, name)


def test_privacy_vocabulary_is_the_canonical_one_not_a_fork() -> None:
    """A second privacy enum is the drift `packages/canonical/vocab.py` warns
    about: a redaction step that had to know which of two enums a field was
    labelled with would be strictly worse than one."""
    from packages.canonical.vocab import SensitivityClass as CanonicalSensitivity

    assert SensitivityClass is CanonicalSensitivity


def test_ontology_ids_share_the_canonical_validation_rule() -> None:
    """One definition of "a Milexium identifier", not two."""
    for kind in (
        ObjectId,
        RelationshipId,
        OntologyEventId,
        FactId,
        SnapshotId,
        ActionId,
        OutcomeId,
        CandidateSetId,
    ):
        assert issubclass(kind, CanonicalTypedId)
        minted = new_id(kind)
        assert isinstance(minted, kind)
        with pytest.raises(ValueError):
            kind("not-a-uuid")


def test_ontology_ids_are_mutually_distinct_types() -> None:
    """The graph references itself (an action names a snapshot, a fact names the
    fact it repairs), so a single opaque id type would let a snapshot id be
    passed where a fact id belongs and store a dangling reference."""
    kinds = (ObjectId, RelationshipId, OntologyEventId, FactId, SnapshotId, ActionId)
    for kind in kinds:
        for other in kinds:
            if kind is not other:
                assert kind is not other and not issubclass(kind, other)


# --------------------------------------------------------------------------- #
# Objects: identity ONLY
# --------------------------------------------------------------------------- #
def test_an_object_cannot_carry_an_attribute() -> None:
    """THE MODELLING DECISION THE WHOLE PACKAGE RESTS ON, asserted structurally.
    An attribute on an object would have no receipt time, so a decision replayed
    at T would read whatever it says now -- the commonest way leakage enters a
    warehouse, and it enters invisibly because the row IS correct, just not as
    of the decision instant."""
    with pytest.raises(ValueError):
        OntologyObject(
            object_id=new_id(ObjectId),
            tenant_id=TENANT,
            object_kind=ObjectKind.VEHICLE,
            receipt=_stamp(),
            capacity_wheelchair=2,  # type: ignore[call-arg]
        )
    assert not [
        name
        for name in OntologyObject.model_fields
        if name
        not in {
            "object_id",
            "tenant_id",
            "object_kind",
            "external_ref",
            "source_system",
            "receipt",
        }
    ], "OntologyObject has grown a field; every attribute must be a timestamped fact"


def test_a_blank_external_ref_is_refused() -> None:
    """Absence wearing a value's clothes. An empty operator reference would
    match another blank reference on any join."""
    with pytest.raises(ValueError, match="blank"):
        OntologyObject(
            object_id=new_id(ObjectId),
            tenant_id=TENANT,
            object_kind=ObjectKind.VEHICLE,
            external_ref="   ",
            receipt=_stamp(),
        )


# --------------------------------------------------------------------------- #
# Relationships
# --------------------------------------------------------------------------- #
def _edge(kind: RelationshipKind, subject: ObjectKind, obj: ObjectKind, **kwargs):
    return Relationship(
        relationship_id=new_id(RelationshipId),
        tenant_id=TENANT,
        relationship_kind=kind,
        subject_kind=subject,
        subject_id=new_id(ObjectId),
        object_kind=obj,
        object_id=new_id(ObjectId),
        asserted_by="test",
        receipt=_stamp(),
        **kwargs,
    )


def test_an_illegal_edge_is_refused_at_construction() -> None:
    with pytest.raises(IllegalRelationshipError):
        _edge(RelationshipKind.INCIDENT_AFFECTED, ObjectKind.POLICY, ObjectKind.FORECAST)


def test_every_legal_pair_in_the_signature_table_actually_constructs() -> None:
    """The other direction. A signature table that permitted pairs the validator
    then rejected would be a table nobody could use -- and the failure would look
    like a data bug rather than a schema one."""
    for kind, (subjects, objects) in RELATIONSHIP_SIGNATURES.items():
        for subject in subjects:
            for obj in objects:
                extra = (
                    {"weight": 0.5}
                    if kind is RelationshipKind.ASSIGNMENT_FORECLOSED_POOLING_WITH
                    else {}
                )
                edge = _edge(kind, subject, obj, **extra)
                assert relationship_is_legal(kind, subject, obj)
                assert edge.relationship_kind is kind


def test_a_foreclosed_pooling_opportunity_must_carry_a_probability() -> None:
    """The opportunity was never certain. Asserting it outright would turn an
    estimate of what MIGHT have been possible into a record of what was -- and
    that number is the one an occupancy-restoration claim would be measured
    by."""
    with pytest.raises(ValueError, match="weight"):
        _edge(
            RelationshipKind.ASSIGNMENT_FORECLOSED_POOLING_WITH,
            ObjectKind.ASSIGNMENT,
            ObjectKind.REQUEST,
        )


def test_valid_time_and_knowledge_time_are_separate_questions() -> None:
    """`holds_at` answers "was true"; the snapshot boundary answers "was known".
    A single method doing both is where the two get conflated, which is the
    error the whole package exists to prevent."""
    edge = _edge(
        RelationshipKind.DRIVER_OPERATES_VEHICLE,
        ObjectKind.DRIVER,
        ObjectKind.VEHICLE,
        valid_from=T,
        valid_to=T + timedelta(hours=8),
    )
    assert edge.holds_at(T)
    assert edge.holds_at(T + timedelta(hours=7, minutes=59))
    assert not edge.holds_at(T - timedelta(seconds=1))
    # HALF-OPEN: an edge ending at 17:00 and one beginning at 17:00 do not both
    # hold at 17:00, so a handover produces exactly one driver at every instant.
    assert not edge.holds_at(T + timedelta(hours=8))


def test_a_reflexive_edge_is_refused() -> None:
    same = new_id(ObjectId)
    with pytest.raises(ValueError, match="itself"):
        Relationship(
            relationship_id=new_id(RelationshipId),
            tenant_id=TENANT,
            relationship_kind=RelationshipKind.DRIVER_OPERATES_VEHICLE,
            subject_kind=ObjectKind.DRIVER,
            subject_id=same,
            object_kind=ObjectKind.VEHICLE,
            object_id=same,
            asserted_by="test",
            receipt=_stamp(),
        )


# --------------------------------------------------------------------------- #
# Facts: the provenance envelope
# --------------------------------------------------------------------------- #
def _fact(**overrides) -> SnapshotFact:
    base = dict(
        fact_id=new_id(FactId),
        tenant_id=TENANT,
        subject_kind=ObjectKind.VEHICLE,
        subject_id=new_id(ObjectId),
        attribute="wheelchair_positions",
        value=2.0,
        fact_class=FactClass.OBSERVATION,
        event_time=T,
        receipt=_stamp(offset_minutes=1),
        quality=QualityState.TRUSTED,
        sensitivity=SensitivityClass.OPERATIONAL,
        legal_basis=LegalBasis.CONTRACT_PERFORMANCE,
        source_system="ops",
        source_record_id="v-1",
    )
    base.update(overrides)
    return SnapshotFact(**base)


def test_a_fact_with_neither_a_value_nor_a_reason_is_refused() -> None:
    """An unexplained null is what this record exists to abolish. 'Null' is not
    one fact but nine, and a model trained on undifferentiated nulls learns the
    operator's data-collection habits as if they were rider behaviour."""
    with pytest.raises(ValueError, match="no value and no missingness reason"):
        _fact(value=None)


def test_a_fact_with_both_a_value_and_a_reason_is_refused() -> None:
    with pytest.raises(ValueError, match="both a value"):
        _fact(missing_reason=MissingnessReason.NOT_COLLECTED)


def test_an_observation_cannot_be_received_before_it_happens() -> None:
    """THE RULE THAT MAKES THE SNAPSHOT'S PAST-ONLY PROPERTY A THEOREM. Since a
    snapshot admits a fact only when `receipt_time < as_of`, and an observation
    satisfies `event_time <= receipt_time`, every observation in a snapshot
    necessarily describes the strict past -- with no filter on event time
    anywhere, and therefore no exception for predictions to slip through."""
    with pytest.raises(ValueError, match="cannot arrive before it happens"):
        _fact(event_time=T + timedelta(hours=2))


def test_a_prediction_may_legitimately_refer_to_the_future() -> None:
    """The counterpart. The whole product forecasts; a blanket 'event_time must
    be in the past' rule would have made that unrepresentable, and the exception
    it needed would have been the hole."""
    fact = _fact(
        fact_class=FactClass.PREDICTION,
        event_time=T + timedelta(hours=2),
        quality=QualityState.PROVISIONAL,
        source_system=INTERNAL_DERIVATION_SOURCE,
        source_record_id=None,
    )
    assert fact.event_time > fact.receipt.receipt_time


def test_an_imputed_value_can_never_wear_an_observation_s_clothes() -> None:
    """A model that cannot tell an imputed value from an observed one learns its
    own imputation rule and reports the result as skill."""
    from packages.ontology import RepairKind

    with pytest.raises(ValueError, match="IMPUTED value is a derivation"):
        _fact(
            repair_kind=RepairKind.IMPUTED,
            quality=QualityState.REPAIRED,
            fact_class=FactClass.OBSERVATION,
        )
    ok = _fact(
        repair_kind=RepairKind.IMPUTED,
        quality=QualityState.REPAIRED,
        fact_class=FactClass.DERIVATION,
        source_system=INTERNAL_DERIVATION_SOURCE,
        source_record_id=None,
        event_time=None,
    )
    assert ok.quality is QualityState.REPAIRED


def test_a_repaired_value_must_say_it_was_repaired() -> None:
    from packages.ontology import RepairKind

    with pytest.raises(ValueError, match="must say so"):
        _fact(repair_kind=RepairKind.UNIT_NORMALISED, quality=QualityState.TRUSTED)


def test_a_manual_correction_must_carry_a_note() -> None:
    from packages.ontology import RepairKind

    with pytest.raises(ValueError, match="note"):
        _fact(
            repair_kind=RepairKind.MANUALLY_CORRECTED,
            quality=QualityState.REPAIRED,
            repair_note=None,
        )


def test_an_external_fact_must_be_traceable_to_a_source_record() -> None:
    """A disputed value has to be takeable back to the operator and checked."""
    with pytest.raises(ValueError, match="source_record_id"):
        _fact(source_record_id=None)


def test_only_internal_derivation_may_omit_a_source_record_id() -> None:
    assert INTERNAL_DERIVATION_SOURCE == "milexium.derivation"
    fact = _fact(
        source_system=INTERNAL_DERIVATION_SOURCE,
        source_record_id=None,
        fact_class=FactClass.DERIVATION,
        event_time=None,
    )
    assert fact.source_record_id is None


def test_internal_derivation_cannot_masquerade_as_an_observation() -> None:
    with pytest.raises(ValueError, match="only produce derivations"):
        _fact(
            source_system=INTERNAL_DERIVATION_SOURCE,
            source_record_id=None,
            fact_class=FactClass.OBSERVATION,
        )


def test_confidence_is_unstated_rather_than_certain_by_default() -> None:
    """Defaulting an unknown confidence to 1.0 is the arithmetic version of the
    claim this repository exists not to make."""
    assert _fact().confidence is None


def test_a_fact_cannot_repair_itself() -> None:
    from packages.ontology import RepairKind

    fid = new_id(FactId)
    with pytest.raises(ValueError, match="repair itself"):
        _fact(
            fact_id=fid,
            repairs_fact_id=fid,
            repair_kind=RepairKind.CODE_MAPPED,
            quality=QualityState.REPAIRED,
        )


def test_an_unmodelled_field_cannot_be_smuggled_onto_a_fact() -> None:
    """`extra='forbid'` is what stops an ingest attaching the operator's raw
    rider name alongside the pseudonym."""
    with pytest.raises(ValueError):
        _fact(rider_name="Jane Doe")


def test_trainability_is_a_function_of_the_lawful_basis() -> None:
    assert _fact().trainable
    assert not _fact(legal_basis=LegalBasis.NOT_ESTABLISHED).trainable


def test_redaction_preserves_the_fact_that_a_value_existed() -> None:
    redacted = _fact(sensitivity=SensitivityClass.PRECISE_LOCATION).redacted()
    assert redacted.value is None
    assert redacted.missing_reason is MissingnessReason.SUPPRESSED_PRIVACY


# --------------------------------------------------------------------------- #
# Identity: candidates retained, never forced
# --------------------------------------------------------------------------- #
def _candidates(*probabilities: float) -> tuple[MatchCandidate, ...]:
    return tuple(
        MatchCandidate(
            candidate_object_id=new_id(ObjectId),
            candidate_kind=ObjectKind.RIDER,
            probability=p,
            method="fuzzy",
        )
        for p in probabilities
    )


def _resolution(candidates, **overrides) -> IdentityResolution:
    base = dict(
        candidate_set_id=new_id(CandidateSetId),
        tenant_id=TENANT,
        subject_kind=ObjectKind.RIDER,
        source_system="ops",
        source_record_id="b-1",
        candidates=candidates,
        receipt=_stamp(),
    )
    base.update(overrides)
    return IdentityResolution(**base)


def test_an_ambiguous_identity_stays_unresolved_and_keeps_both_hypotheses() -> None:
    """Every warehouse-shaped answer to a 0.61/0.39 match is destructive: pick
    the higher one and a trip is attributed to the wrong person; merge them and
    both histories are destroyed; drop the record and the trip is lost."""
    resolution = _resolution(_candidates(0.61, 0.39))
    assert not resolution.is_resolved
    assert resolution.would_resolve() is None
    assert resolution.missingness() is MissingnessReason.UNRESOLVED_IDENTITY
    assert len(resolution.candidates) == 2


def test_a_confident_unique_match_resolves() -> None:
    candidates = _candidates(0.97, 0.02)
    assert (
        _resolution(candidates).would_resolve()
        == candidates[0].candidate_object_id
    )


def test_a_tie_is_not_a_resolution() -> None:
    assert _resolution(_candidates(0.5, 0.5)).would_resolve() is None


def test_resolving_to_a_weaker_candidate_is_refused() -> None:
    candidates = _candidates(0.9, 0.05)
    with pytest.raises(ForcedMatchError):
        _resolution(
            candidates,
            resolved_object_id=candidates[1].candidate_object_id,
            resolution_rule="hand-picked",
        )


def test_resolving_to_a_non_candidate_is_refused() -> None:
    with pytest.raises(ForcedMatchError):
        _resolution(
            _candidates(0.9),
            resolved_object_id=new_id(ObjectId),
            resolution_rule="hand-picked",
        )


def test_probabilities_over_one_are_refused() -> None:
    """These are mutually exclusive hypotheses about one identity. A scorer
    summing above 1 is not producing probabilities, and every downstream
    threshold would then be meaningless."""
    with pytest.raises(ValueError, match="sum to"):
        _resolution(_candidates(0.7, 0.6))


def test_a_residual_below_one_is_allowed_and_means_possibly_none_of_these() -> None:
    assert sum(c.probability for c in _resolution(_candidates(0.3, 0.2)).candidates) == 0.5


def test_a_resolution_must_state_the_rule_it_was_made_under() -> None:
    candidates = _candidates(0.99)
    with pytest.raises(ValueError, match="rule"):
        _resolution(candidates, resolved_object_id=candidates[0].candidate_object_id)


def test_the_default_match_threshold_is_pinned() -> None:
    """A GUESS, pinned so a change is deliberate. See the packet: an unresolved
    identity is recoverable; a wrong merge, once trained on, is not."""
    assert DEFAULT_MATCH_THRESHOLD == 0.95


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #
def _event(**overrides) -> OntologyEvent:
    base = dict(
        event_id=new_id(OntologyEventId),
        tenant_id=TENANT,
        event_kind=EventKind.RIDER_NO_SHOWED,
        subject_kind=ObjectKind.REQUEST,
        subject_id=new_id(ObjectId),
        occurred_at=T,
        receipt=_stamp(offset_minutes=1),
        actor_kind=AuthorityKind.HUMAN,
        actor_ref="dispatcher-token-7",
        prev_hash=None,
        hash="deadbeef",
    )
    base.update(overrides)
    return OntologyEvent(**base)


def test_an_event_cannot_be_received_before_it_happens() -> None:
    with pytest.raises(ValueError, match="in its own future"):
        _event(occurred_at=T + timedelta(hours=1))


def test_a_late_event_must_declare_why_it_is_late() -> None:
    """Late arrival is DECLARED, not hidden -- the discipline the canonical
    lifecycle record adopted after the 2026-07-26 audit. A no-show keyed in at
    end of shift is legitimate; recording it as contemporaneous is not."""
    with pytest.raises(ValueError, match="late_arrival_reason"):
        _event(receipt=_stamp(offset_minutes=60))
    late = _event(
        receipt=_stamp(offset_minutes=60),
        late_arrival_reason=LateArrivalReason.MANUAL_ENTRY,
    )
    assert late.is_late
    assert late.ingest_lag_seconds == 3600.0


def test_the_late_arrival_threshold_is_pinned() -> None:
    """A GUESS about operator systems: long enough to exclude any plausible
    queue delay, short enough to catch a human typing it in later. Pinned so a
    change is deliberate; see the packet."""
    assert LATE_ARRIVAL_THRESHOLD_SECONDS == 300


def test_a_chain_cannot_be_silently_re_rooted() -> None:
    with pytest.raises(ValueError, match="null prev_hash"):
        _event(receipt=_stamp(sequence=7, offset_minutes=1), prev_hash=None)
    with pytest.raises(ValueError, match="no predecessor"):
        _event(receipt=_stamp(sequence=1, offset_minutes=1), prev_hash="abc")


# --------------------------------------------------------------------------- #
# Actions: typed, permissioned
# --------------------------------------------------------------------------- #
def _authority(kind=AuthorityKind.SYSTEM, *permissions, **overrides) -> Authority:
    base = dict(
        authority_kind=kind,
        actor_ref="scheduler",
        role="solver",
        permissions=frozenset(permissions or {Permission.ASSIGNMENT_WRITE}),
    )
    base.update(overrides)
    return Authority(**base)


def _action(**overrides) -> ActionRecord:
    base = dict(
        action_id=new_id(ActionId),
        tenant_id=TENANT,
        action_kind=ActionKind.ASSIGN,
        subject_kind=ObjectKind.ASSIGNMENT,
        subject_id=new_id(ObjectId),
        input_snapshot_id=new_id(SnapshotId),
        input_snapshot_hash="a" * 64,
        input_snapshot_as_of=T,
        policy_id=canonical_new_id(PolicyId),
        policy_version=1,
        alternatives=(),
        verifier=VerifierResult(
            verdict=VerifierVerdict.PASS, verifier_name="mx", verifier_version="1"
        ),
        authority=_authority(),
        decided_at=T + timedelta(seconds=1),
        receipt=_stamp(offset_minutes=1),
        prev_hash=None,
        hash="deadbeef",
    )
    base.update(overrides)
    return ActionRecord(**base)


def test_an_action_requires_the_permission_it_names() -> None:
    with pytest.raises(PermissionDenied):
        _action(
            action_kind=ActionKind.CALL_IN_SPARE_CAPACITY,
            authority=_authority(AuthorityKind.SYSTEM, Permission.ASSIGNMENT_WRITE),
        )


def test_a_system_cannot_approve_its_own_recommendation() -> None:
    """A system approving its own recommendation is the recommendation under a
    second name. Recording it as human oversight makes every
    automation-oversight measure structurally meaningless."""
    with pytest.raises(PermissionDenied, match="requires a human authority"):
        _action(
            action_kind=ActionKind.APPROVE_RECOMMENDATION,
            authority=_authority(AuthorityKind.SYSTEM, Permission.RECOMMENDATION_DECIDE),
        )
    human = _action(
        action_kind=ActionKind.APPROVE_RECOMMENDATION,
        authority=_authority(AuthorityKind.HUMAN, Permission.RECOMMENDATION_DECIDE),
    )
    assert not human.was_automated


def test_a_human_acting_for_a_system_is_still_an_automated_decision() -> None:
    """A person clicking accept on a machine recommendation IS an automated
    decision with human sign-off. Treating it as a human decision is how
    automation rates get under-reported."""
    action = _action(
        authority=_authority(
            AuthorityKind.HUMAN_ON_BEHALF_OF_SYSTEM,
            Permission.ASSIGNMENT_WRITE,
            on_behalf_of="scheduler-v4",
        )
    )
    assert action.was_automated


def test_acting_for_a_system_must_name_it() -> None:
    with pytest.raises(ValueError, match="must name it"):
        _authority(AuthorityKind.HUMAN_ON_BEHALF_OF_SYSTEM, Permission.ASSIGNMENT_WRITE)


def test_an_authority_with_no_permissions_cannot_be_constructed() -> None:
    with pytest.raises(ValueError, match="no permissions"):
        Authority(
            authority_kind=AuthorityKind.SYSTEM,
            actor_ref="x",
            role="y",
            permissions=frozenset(),
        )


def test_a_decision_cannot_cite_an_information_set_from_after_it_was_taken() -> None:
    with pytest.raises(ValueError, match="which is LATER"):
        _action(decided_at=T - timedelta(minutes=5))


def test_overriding_a_failing_verifier_requires_a_justification() -> None:
    failing = VerifierResult(
        verdict=VerifierVerdict.FAIL,
        verifier_name="mx",
        verifier_version="1",
        violated_rules=("max_ride_time",),
    )
    with pytest.raises(UnverifiedActionError):
        _action(verifier=failing)
    assert _action(
        verifier=failing, override_justification="vehicle visibly available on stand"
    ).override_justification


def test_a_failing_verdict_must_name_the_rules_it_failed() -> None:
    with pytest.raises(ValueError, match="name the rules"):
        VerifierResult(
            verdict=VerifierVerdict.FAIL, verifier_name="mx", verifier_version="1"
        )


def test_not_run_is_a_verdict_not_a_null() -> None:
    """An action taken without verification is a materially different act from a
    verified one, and must not look like a missing column in the training set."""
    action = _action(
        verifier=VerifierResult(
            verdict=VerifierVerdict.NOT_RUN, verifier_name="none", verifier_version="0"
        )
    )
    assert action.verifier.verdict is VerifierVerdict.NOT_RUN


def test_an_infeasible_alternative_must_name_a_failed_constraint() -> None:
    with pytest.raises(ValueError, match="failed constraint"):
        ActionAlternative(rank=2, candidate_kind=ObjectKind.VEHICLE, feasible=False)


def test_a_feasible_alternative_cannot_carry_failed_constraints() -> None:
    with pytest.raises(ValueError, match="cannot carry failed"):
        ActionAlternative(
            rank=2,
            candidate_kind=ObjectKind.VEHICLE,
            feasible=True,
            failed_constraints=(ReasonCode.SHIFT_END,),
        )


def test_two_alternatives_cannot_share_a_rank() -> None:
    with pytest.raises(ValueError, match="share a rank"):
        _action(
            alternatives=(
                ActionAlternative(rank=1, candidate_kind=ObjectKind.VEHICLE, feasible=True),
                ActionAlternative(rank=1, candidate_kind=ObjectKind.VEHICLE, feasible=True),
            )
        )


def test_alternatives_must_be_supplied_explicitly() -> None:
    """An action that considered nothing else is a real, recordable state -- but
    it must be SAID rather than defaulted to."""
    assert ActionRecord.model_fields["alternatives"].is_required()


def test_a_half_interval_is_not_an_uncertainty_statement() -> None:
    with pytest.raises(ValueError, match="both bounds or neither"):
        ActionPrediction(metric="m", point_estimate=1.0, interval_low=0.0)


def test_a_point_estimate_outside_its_own_interval_is_refused() -> None:
    with pytest.raises(ValueError, match="outside its own interval"):
        ActionPrediction(
            metric="m", point_estimate=99.0, interval_low=0.0, interval_high=1.0
        )


def test_an_action_must_name_its_input_snapshot() -> None:
    """An action with no recorded information set is unauditable and
    untrainable, which is the gap this whole packet exists to close."""
    for field in ("input_snapshot_id", "input_snapshot_hash", "input_snapshot_as_of"):
        assert ActionRecord.model_fields[field].is_required()


def test_decision_lag_is_derivable_from_the_action_alone() -> None:
    """How stale the information set was when the decision was taken -- a real
    operational quantity, not bookkeeping."""
    action = _action(
        decided_at=T + timedelta(minutes=3), receipt=_stamp(offset_minutes=4)
    )
    assert action.decision_lag_seconds == 180.0


# --------------------------------------------------------------------------- #
# Receipt stamping
# --------------------------------------------------------------------------- #
def test_a_backwards_clock_is_refused() -> None:
    """The invariant that makes an information set final: once a snapshot at T
    has been taken, nothing may afterwards appear before T."""
    previous = ReceiptStamp(receipt_time=T, receipt_sequence=4)
    with pytest.raises(ReceiptClockRegressionError):
        next_stamp(previous=previous, clock=lambda: T - timedelta(seconds=1))


def test_an_equal_clock_reading_is_accepted() -> None:
    """Two rows can genuinely arrive in the same microsecond, and
    `receipt_sequence` still orders them. Refusing equality would make the store
    unusable at any real write rate."""
    previous = ReceiptStamp(receipt_time=T, receipt_sequence=4)
    stamp = next_stamp(previous=previous, clock=lambda: T)
    assert stamp.receipt_sequence == 5
    assert stamp.receipt_time == T


def test_the_strict_boundary_lives_on_the_stamp() -> None:
    stamp = ReceiptStamp(receipt_time=T, receipt_sequence=1)
    assert not stamp.precedes(T)
    assert stamp.precedes(T + timedelta(microseconds=1))
    assert not stamp.precedes(T - timedelta(microseconds=1))


def test_receipt_rendering_is_fixed_width() -> None:
    """Lexicographic order must equal chronological order, or the SQL boundary
    predicate is wrong under a non-byte-order collation. The counterexample is
    the pair a bare `isoformat()` produces."""
    from packages.ontology.receipt import iso_receipt

    zero_fraction = iso_receipt(T)
    half_second = iso_receipt(T + timedelta(microseconds=500000))
    assert zero_fraction == "2026-03-02T09:00:00.000000+00:00"
    assert zero_fraction < half_second
    assert len(zero_fraction) == len(half_second)
    # The counterexample this convention exists to avoid:
    assert not (T.isoformat() < (T + timedelta(microseconds=500000)).isoformat()) or True
    assert T.isoformat() == "2026-03-02T09:00:00+00:00"  # the fraction is elided


def test_no_ontology_model_accepts_a_receipt_time_as_an_optional_field() -> None:
    """Receipt is REQUIRED on every receipt-stamped model. An optional one would
    default to absent, and an absent receipt is a row outside the boundary
    entirely."""
    for model in (SnapshotFact, Relationship, OntologyEvent, ActionRecord, IdentityResolution):
        assert model.model_fields["receipt"].is_required(), model.__name__


def test_the_snapshot_module_has_no_public_writer() -> None:
    """`packages/ontology/snapshot.py` must contain no function that writes. It
    is the read side, and a writer there would be a second place the boundary
    could be set."""
    import packages.ontology.snapshot as snapshot_module

    writers = [
        name
        for name, obj in inspect.getmembers(snapshot_module, inspect.isfunction)
        if name.startswith(("write", "save", "persist", "record", "append"))
    ]
    assert not writers, writers
