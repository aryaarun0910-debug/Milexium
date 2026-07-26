"""THE LOAD-BEARING TEST: a `DecisionSnapshot` at T cannot see T+1.

WHY THIS FILE IS SHAPED THE WAY IT IS.
A leakage test that checks the obvious accessor and stops is worthless, because
leakage does not arrive through the obvious accessor. It arrives through the
serialiser somebody added for an export, the "convenience" method that reloads
from the store, the projection that a feature builder calls, or the pydantic
escape hatch that skips the validator which was doing all the work. So this
module does three things a single happy-path assertion does not:

  1. IT ENUMERATES THE PUBLIC SURFACE BY REFLECTION. Every public member of
     `DecisionSnapshot` -- its own methods, its fields, and the pydantic
     machinery it inherits -- must appear in either `_PROBES` (and is then
     actually exercised against a poisoned store) or `_NOT_A_READ_PATH` (a short,
     justified list). Adding a read path without a probe FAILS the suite. That is
     the anti-vacuity device: the test cannot silently stop covering the class.

  2. IT USES A SENTINEL, NOT AN EQUALITY. Post-boundary writes carry a unique
     string and a unique number, and every probe's output is searched for both.
     A probe therefore cannot pass by returning something structurally different
     from what the author imagined; it passes only if the poison is genuinely
     absent from what it rendered.

  3. IT RUNS A POSITIVE CONTROL. `OntologyStore.fact_history` -- the audit view,
     which deliberately applies no time filter -- MUST contain the sentinel. If
     it did not, the corruption would be inert and every "no leak" assertion
     above would be passing for the wrong reason. This is the control the
     feature-store conformance suite established (`test_real_panel_corruption_
     would_change_a_future_read`) applied to the ontology.

DATA PROVENANCE: every fixture in this file is SYNTHETIC. There is no consented
operator data in this repository. Status of everything proven here:
Demonstrated -- never Validated.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from packages.canonical.ids import PolicyId, TenantId, new_id as canonical_new_id
from packages.ontology import (
    ActionAlternative,
    FactId,
    LateArrivalReason,
    SnapshotId,
    ActionKind,
    ActionPrediction,
    Authority,
    AuthorityKind,
    ConflictedValueError,
    DecisionSnapshot,
    EventKind,
    FactClass,
    ForgedSnapshotError,
    LegalBasis,
    MatchCandidate,
    MissingnessReason,
    ObjectKind,
    Permission,
    QualityState,
    ReasonCode,
    RelationshipKind,
    SensitivityClass,
    SnapshotLeakageError,
    SnapshotPurpose,
    SnapshotScope,
    VerifierResult,
    VerifierVerdict,
)
from packages.ontology.receipt import ReceiptStamp
from packages.ontology.store import OntologyDatabase, OntologyStore

# --------------------------------------------------------------------------- #
# Fixtures. SYNTHETIC.
# --------------------------------------------------------------------------- #
T_START = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)

LEAK_TEXT = "LEAK-SENTINEL-9f3a2b"
LEAK_NUMBER = 987654.5
LEAK_ATTRIBUTE_PREFIX = "leaked_"


class ScriptedClock:
    """A deterministic receipt clock.

    THE SEAM, USED HONESTLY. `OntologyStore` takes its clock as a CONSTRUCTOR
    argument, which is what makes receipt times drivable here. It is a real trust
    boundary and `packages/ontology/receipt.py` says so; what it is NOT is the
    defect the 2026-07-26 audit found, where every individual write could assert
    its own `recorded_at`. `test_no_store_method_accepts_a_receipt_time` below
    reads the signatures back to prove that difference rather than assert it.
    """

    def __init__(self, start: datetime = T_START, step: timedelta = timedelta(minutes=1)):
        self.now = start
        self.step = step

    def __call__(self) -> datetime:
        value = self.now
        self.now = self.now + self.step
        return value

    def advance(self, **delta) -> None:
        """Jump the clock forward. Only ever FORWARD -- a test that could wind
        the clock back would be exercising a condition
        `ReceiptClockRegressionError` exists to make impossible, and would
        quietly stop testing the real one."""
        self.now = self.now + timedelta(**delta)


@pytest.fixture()
def store():
    database = OntologyDatabase.sqlite()
    clock = ScriptedClock()
    store = OntologyStore(database, canonical_new_id(TenantId), clock=clock)
    # Attached for the tests' convenience only. The store itself reads its clock
    # through the constructor argument; nothing in packages/ontology looks at
    # this attribute.
    store.test_clock = clock
    yield store
    database.close()


def _episode(store: OntologyStore):
    """Build the packet's own vignette: a request, a wheelchair-accessible
    vehicle, an assignment, and the pooling opportunities it foreclosed."""
    rider = store.register_object(
        object_kind=ObjectKind.RIDER, external_ref="rider-token-1", source_system="ops"
    )
    request = store.register_object(
        object_kind=ObjectKind.REQUEST, external_ref="R-1002", source_system="ops"
    )
    vehicle = store.register_object(
        object_kind=ObjectKind.VEHICLE, external_ref="B-101", source_system="ops"
    )
    assignment = store.register_object(
        object_kind=ObjectKind.ASSIGNMENT, source_system="milexium"
    )
    other_request = store.register_object(
        object_kind=ObjectKind.REQUEST, external_ref="R-1003", source_system="ops"
    )

    store.record_fact(
        subject_kind=ObjectKind.REQUEST,
        subject_id=request.object_id,
        attribute="requested_pickup_minute_of_day",
        fact_class=FactClass.OBSERVATION,
        quality=QualityState.TRUSTED,
        sensitivity=SensitivityClass.OPERATIONAL,
        legal_basis=LegalBasis.CONTRACT_PERFORMANCE,
        source_system="ops",
        source_record_id="R-1002",
        value=602.0,
        event_time=T_START,
    )
    store.record_fact(
        subject_kind=ObjectKind.VEHICLE,
        subject_id=vehicle.object_id,
        attribute="expected_free_minute_of_day",
        fact_class=FactClass.PREDICTION,
        quality=QualityState.PROVISIONAL,
        confidence=0.72,
        sensitivity=SensitivityClass.OPERATIONAL,
        legal_basis=LegalBasis.CONTRACT_PERFORMANCE,
        source_system="milexium.derivation",
        value=641.0,
        event_time=T_START + timedelta(hours=1),
    )
    store.record_fact(
        subject_kind=ObjectKind.REQUEST,
        subject_id=request.object_id,
        attribute="actual_pickup_delay_minutes",
        fact_class=FactClass.OBSERVATION,
        quality=QualityState.TRUSTED,
        sensitivity=SensitivityClass.OPERATIONAL,
        legal_basis=LegalBasis.CONTRACT_PERFORMANCE,
        source_system="ops",
        source_record_id="R-1002",
        missing_reason=MissingnessReason.NOT_YET_KNOWN,
        event_time=None,
    )
    store.assert_relationship(
        relationship_kind=RelationshipKind.REQUEST_BELONGS_TO_RIDER,
        subject_kind=ObjectKind.REQUEST,
        subject_id=request.object_id,
        object_kind=ObjectKind.RIDER,
        object_id=rider.object_id,
        asserted_by="intake",
    )
    store.assert_relationship(
        relationship_kind=RelationshipKind.ASSIGNMENT_FORECLOSED_POOLING_WITH,
        subject_kind=ObjectKind.ASSIGNMENT,
        subject_id=assignment.object_id,
        object_kind=ObjectKind.REQUEST,
        object_id=other_request.object_id,
        asserted_by="solver",
        weight=0.62,
    )
    store.record_event(
        event_kind=EventKind.BOOKING_CREATED,
        subject_kind=ObjectKind.REQUEST,
        subject_id=request.object_id,
        occurred_at=T_START,
        actor_kind=AuthorityKind.HUMAN,
        actor_ref="dispatcher-token-7",
        late_arrival_reason=LateArrivalReason.BATCH_EXPORT,
    )
    store.record_identity_resolution(
        subject_kind=ObjectKind.RIDER,
        source_system="ops",
        source_record_id="booking-88",
        candidates=(
            MatchCandidate(
                candidate_object_id=rider.object_id,
                candidate_kind=ObjectKind.RIDER,
                probability=0.61,
                method="name_dob_fuzzy",
                evidence=("surname_exact", "dob_within_1d"),
            ),
        ),
    )
    scope = SnapshotScope(
        subject_ids=(
            rider.object_id,
            request.object_id,
            vehicle.object_id,
            assignment.object_id,
            other_request.object_id,
        )
    )
    return {
        "rider": rider,
        "request": request,
        "vehicle": vehicle,
        "assignment": assignment,
        "other_request": other_request,
        "scope": scope,
    }


def _poison_after(store: OntologyStore, episode: dict) -> None:
    """Write facts that became known at T+1. Every one of them carries a
    sentinel, so a probe cannot pass by rendering something the author did not
    anticipate -- only by genuinely not containing the poison."""
    store.record_fact(
        subject_kind=ObjectKind.REQUEST,
        subject_id=episode["request"].object_id,
        attribute=f"{LEAK_ATTRIBUTE_PREFIX}numeric",
        fact_class=FactClass.OBSERVATION,
        quality=QualityState.TRUSTED,
        sensitivity=SensitivityClass.OPERATIONAL,
        legal_basis=LegalBasis.CONTRACT_PERFORMANCE,
        source_system="ops",
        source_record_id="after-1",
        value=LEAK_NUMBER,
        event_time=T_START,
    )
    store.record_fact(
        subject_kind=ObjectKind.REQUEST,
        subject_id=episode["request"].object_id,
        attribute=f"{LEAK_ATTRIBUTE_PREFIX}text",
        fact_class=FactClass.OBSERVATION,
        quality=QualityState.TRUSTED,
        sensitivity=SensitivityClass.OPERATIONAL,
        legal_basis=LegalBasis.CONTRACT_PERFORMANCE,
        source_system="ops",
        source_record_id="after-2",
        value=LEAK_TEXT,
        event_time=T_START,
    )
    # The label: the outcome the decision was scored against. THE fact that must
    # never be visible to a snapshot taken before it -- this is the shape of
    # every label-leakage bug there is.
    store.record_fact(
        subject_kind=ObjectKind.REQUEST,
        subject_id=episode["request"].object_id,
        attribute="actual_pickup_delay_minutes",
        fact_class=FactClass.OBSERVATION,
        quality=QualityState.TRUSTED,
        sensitivity=SensitivityClass.OPERATIONAL,
        legal_basis=LegalBasis.CONTRACT_PERFORMANCE,
        source_system="ops",
        source_record_id="after-3",
        value=14.0,
        event_time=T_START,
    )
    store.assert_relationship(
        relationship_kind=RelationshipKind.VEHICLE_PERFORMS_ASSIGNMENT,
        subject_kind=ObjectKind.VEHICLE,
        subject_id=episode["vehicle"].object_id,
        object_kind=ObjectKind.ASSIGNMENT,
        object_id=episode["assignment"].object_id,
        asserted_by=LEAK_TEXT,
    )
    store.record_event(
        event_kind=EventKind.PICKUP,
        subject_kind=ObjectKind.REQUEST,
        subject_id=episode["request"].object_id,
        occurred_at=T_START,
        actor_kind=AuthorityKind.SYSTEM,
        actor_ref="avl",
        payload={"sentinel": LEAK_TEXT},
        late_arrival_reason=LateArrivalReason.BATCH_EXPORT,
    )
    store.record_identity_resolution(
        subject_kind=ObjectKind.RIDER,
        source_system="ops",
        source_record_id=LEAK_TEXT,
        candidates=(
            MatchCandidate(
                candidate_object_id=episode["rider"].object_id,
                candidate_kind=ObjectKind.RIDER,
                probability=0.99,
                method=LEAK_TEXT,
            ),
        ),
        resolved_object_id=episode["rider"].object_id,
        resolution_rule="unique-argmax>=0.95",
    )


def _contains_poison(rendered: object) -> bool:
    text = repr(rendered)
    return (
        LEAK_TEXT in text
        or LEAK_ATTRIBUTE_PREFIX in text
        or repr(LEAK_NUMBER) in text
        or "14.0" in _numeric_values(rendered)
    )


def _numeric_values(rendered: object) -> str:
    """Only the numbers, so the label value 14.0 is searched for without a
    false positive from an unrelated `14.0` inside a hash or an id string."""
    if isinstance(rendered, dict):
        return " ".join(_numeric_values(v) for v in rendered.values())
    if isinstance(rendered, (list, tuple, set, frozenset)):
        return " ".join(_numeric_values(v) for v in rendered)
    if isinstance(rendered, bool):
        return ""
    if isinstance(rendered, (int, float)):
        return repr(float(rendered))
    return ""


# --------------------------------------------------------------------------- #
# 1. THE READ-PATH REGISTRY. Adding a member without a probe fails the suite.
# --------------------------------------------------------------------------- #
def _probes(snapshot: DecisionSnapshot, episode: dict) -> dict[str, object]:
    """Every read path, exercised. The value is what the path rendered; the
    caller searches it for the poison."""
    request = episode["request"].object_id
    rider = episode["rider"].object_id
    assignment = episode["assignment"].object_id
    return {
        # -- fields (attribute access is a read path) ----------------------- #
        "facts": snapshot.facts,
        "relationships": snapshot.relationships,
        "events": snapshot.events,
        "identity_resolutions": snapshot.identity_resolutions,
        "snapshot_id": snapshot.snapshot_id,
        "tenant_id": snapshot.tenant_id,
        "as_of": snapshot.as_of,
        "taken_receipt": snapshot.taken_receipt,
        "purpose": snapshot.purpose,
        "scope": snapshot.scope,
        "derived_from": snapshot.derived_from,
        # -- our own projections ------------------------------------------- #
        "subjects": snapshot.subjects(),
        "attributes_of": snapshot.attributes_of(request),
        "facts_for": snapshot.facts_for(request),
        "value_of": snapshot.value_of(request, "requested_pickup_minute_of_day"),
        "missing": snapshot.missing(),
        "conflicts": snapshot.conflicts(),
        "relationships_of": snapshot.relationships_of(),
        "related": snapshot.related(request, RelationshipKind.REQUEST_BELONGS_TO_RIDER),
        "events_of": snapshot.events_of(),
        "unresolved_identities": snapshot.unresolved_identities(),
        "feature_vector": snapshot.feature_vector(),
        "provenance_manifest": snapshot.provenance_manifest(),
        "latest_receipt": snapshot.latest_receipt(),
        "content_hash": snapshot.content_hash,
        "redacted": snapshot.redacted(),
        "for_training": snapshot.for_training(),
        # -- serialisation, including the deprecated v1 shims --------------- #
        "model_dump": snapshot.model_dump(),
        "model_dump_json": snapshot.model_dump_json(),
        "model_copy": snapshot.model_copy(),
        "model_fields_set": snapshot.model_fields_set,
        "model_extra": snapshot.model_extra,
        "dict": _deprecated(lambda: snapshot.dict()),
        "json": _deprecated(lambda: snapshot.json()),
        "copy": _deprecated(lambda: snapshot.copy()),
        # -- the checker itself (it reads the admitted set) ----------------- #
        "verify": snapshot.verify(),
        # -- unused args, still enumerated so the surface is total ---------- #
        "_unused_rider": rider,
        "_unused_assignment": assignment,
    }


def _deprecated(call):
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return call()


_NOT_A_READ_PATH = frozenset(
    {
        # Class-level configuration and schema. None of these can render an
        # admitted fact: they describe the MODEL, not an instance's content.
        "model_config",
        "model_fields",
        "model_computed_fields",
        "model_json_schema",
        "model_parametrized_name",
        "model_rebuild",
        "model_post_init",
        "schema",
        "schema_json",
        "update_forward_refs",
        # CONSTRUCTORS, not readers. They build a snapshot from input the caller
        # already has, so they cannot surface a store row the caller does not.
        # Two of them (`construct` / `model_construct`) skip validation, which
        # makes them a FORGERY path rather than a read path -- covered by
        # `test_model_construct_forgery_is_caught_by_verify`.
        "construct",
        "model_construct",
        "model_validate",
        "model_validate_json",
        "model_validate_strings",
        "validate",
        "from_orm",
        "parse_obj",
        "parse_raw",
        "parse_file",
    }
)


def test_every_public_member_is_probed_or_justified(store) -> None:
    """THE ANTI-VACUITY CHECK. If someone adds a read path to
    `DecisionSnapshot` without probing it here, this fails -- so the leakage
    proof below cannot silently stop covering the class."""
    episode = _episode(store)
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    surface = {n for n in dir(DecisionSnapshot) if not n.startswith("_")}
    surface |= set(DecisionSnapshot.model_fields)
    probed = {k for k in _probes(snapshot, episode) if not k.startswith("_unused")}
    uncovered = surface - probed - _NOT_A_READ_PATH
    assert not uncovered, (
        f"public member(s) of DecisionSnapshot are neither probed for leakage nor "
        f"listed as non-read paths: {sorted(uncovered)}. Add a probe to _probes() "
        "or justify the member in _NOT_A_READ_PATH -- an unprobed read path is how "
        "leakage gets in."
    )
    stale = probed - surface
    assert not stale, f"_probes() names members that no longer exist: {sorted(stale)}"


def _after(store: OntologyStore) -> datetime:
    """A decision instant strictly after everything written so far and strictly
    before anything written next."""
    watermark = store.receipt_watermark()
    assert watermark is not None
    return watermark.receipt_time + timedelta(seconds=1)


# --------------------------------------------------------------------------- #
# 2. THE PROOF: a snapshot at T sees nothing written at T+1, on ANY read path.
# --------------------------------------------------------------------------- #
def test_no_read_path_sees_a_fact_that_became_known_after_the_boundary(store) -> None:
    episode = _episode(store)
    as_of = _after(store)
    snapshot = store.take_snapshot(as_of=as_of, scope=episode["scope"])
    _poison_after(store, episode)

    failures = []
    for name, rendered in _probes(snapshot, episode).items():
        if name.startswith("_unused"):
            continue
        if _contains_poison(rendered):
            failures.append(name)
    assert not failures, (
        f"read path(s) leaked post-boundary information: {sorted(failures)}"
    )


def test_the_corruption_is_real_the_audit_view_does_see_it(store) -> None:
    """POSITIVE CONTROL. Without this, every assertion above could be passing
    because the poison was never written. `fact_history` is the STORE's audit
    view and deliberately applies no time filter, so it must contain the label
    the snapshot could not see."""
    episode = _episode(store)
    as_of = _after(store)
    snapshot = store.take_snapshot(as_of=as_of, scope=episode["scope"])
    _poison_after(store, episode)

    history = store.fact_history(
        episode["request"].object_id, "actual_pickup_delay_minutes"
    )
    assert [f.value for f in history] == [None, 14.0], (
        "the audit view must show both the decision-time absence and the later "
        "actual; if it does not, the corruption is inert and the leakage proof is "
        "vacuous"
    )
    assert (
        snapshot.value_of(episode["request"].object_id, "actual_pickup_delay_minutes")
        is None
    )


def test_the_label_reads_as_not_yet_known_not_as_an_unexplained_null(store) -> None:
    """The missingness reason is what makes the absence analysable rather than
    merely absent -- and NOT_YET_KNOWN is the specific case that later becomes
    known, so it is the one a careless rebuild would leak."""
    episode = _episode(store)
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    missing = dict(((str(s), a), r) for s, a, r in snapshot.missing())
    assert (
        missing[(str(episode["request"].object_id), "actual_pickup_delay_minutes")]
        is MissingnessReason.NOT_YET_KNOWN
    )


def test_a_fact_stamped_exactly_at_the_boundary_is_excluded(store) -> None:
    """The strict `<`, at the object layer. A fact that arrived in the same
    instant the decision was taken cannot be shown to have informed it."""
    episode = _episode(store)
    fact = store.record_fact(
        subject_kind=ObjectKind.REQUEST,
        subject_id=episode["request"].object_id,
        attribute="boundary_case",
        fact_class=FactClass.OBSERVATION,
        quality=QualityState.TRUSTED,
        sensitivity=SensitivityClass.OPERATIONAL,
        legal_basis=LegalBasis.CONTRACT_PERFORMANCE,
        source_system="ops",
        source_record_id="b-1",
        value=1.0,
        event_time=T_START,
    )
    exactly_at = fact.receipt.receipt_time
    snapshot = store.take_snapshot(as_of=exactly_at, scope=episode["scope"])
    assert snapshot.value_of(episode["request"].object_id, "boundary_case") is None

    one_microsecond_later = exactly_at + timedelta(microseconds=1)
    later = store.take_snapshot(
        as_of=one_microsecond_later, scope=episode["scope"]
    )
    assert later.value_of(episode["request"].object_id, "boundary_case") == 1.0


def test_the_boundary_is_a_sql_predicate_not_a_python_filter() -> None:
    """READ THE QUERY. The strict `<` must appear in the SQL `WHERE` clause, so
    a post-boundary row is never fetched -- not fetched and then discarded. A
    Python-side filter would satisfy every behavioural test above and would be
    one refactor away from being skipped."""
    source = Path("packages/ontology/store.py").read_text(encoding="utf-8")
    assert "receipt_time < ?" in source, (
        "the point-in-time boundary is no longer a SQL predicate. If it moved into "
        "Python, a future row is being fetched and then filtered, and the guarantee "
        "now depends on that filter never being bypassed"
    )
    tree = ast.parse(source)
    select_content = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_select_content"
    )
    literals = [
        n.value
        for n in ast.walk(select_content)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    predicates = [s for s in literals if "receipt_time <" in s]
    assert len(predicates) >= 4, (
        "every stream a snapshot admits must carry the boundary predicate; found "
        f"{len(predicates)}"
    )
    assert not any("receipt_time <=" in s for s in literals), (
        "a non-strict boundary would admit a row stamped exactly at the decision "
        "instant"
    )


# --------------------------------------------------------------------------- #
# 3. STRUCTURAL: the snapshot cannot reach a store, a clock, or the present.
# --------------------------------------------------------------------------- #
def test_snapshot_module_imports_nothing_from_the_store() -> None:
    """LAYER 3. A `refresh()` or a lazily-loaded attribute would satisfy every
    construction-time check and then read the present. It is structurally
    impossible only if the module cannot reach the store at all."""
    tree = ast.parse(Path("packages/ontology/snapshot.py").read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    assert not [m for m in imported if "store" in m], (
        f"snapshot.py imports a store module ({imported}); a snapshot that can "
        "reach a database can read the present"
    )


def test_snapshot_module_reads_no_clock() -> None:
    """A snapshot that could ask what time it is now could compare itself to the
    present, and the first optimisation someone writes on top of that is a
    freshness check that admits a newer fact."""
    tree = ast.parse(Path("packages/ontology/snapshot.py").read_text(encoding="utf-8"))
    banned = {"now", "utcnow", "today", "time", "monotonic"}
    found = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in banned
    ]
    assert not found, f"snapshot.py reads a clock: {found}"


def test_snapshot_holds_no_callable_field() -> None:
    """A callable field would be a store handle wearing a different hat."""
    for name, field in DecisionSnapshot.model_fields.items():
        assert not callable(getattr(field.default, "__call__", None)) or field.default is None, name
        annotation = str(field.annotation)
        assert "Callable" not in annotation, (
            f"field {name!r} is callable-typed; a snapshot may not carry a way to "
            "fetch anything"
        )


def test_snapshot_collections_are_immutable(store) -> None:
    """`frozen=True` prevents rebinding an attribute; it does NOT deep-freeze a
    mutable container. With `facts: list[...]` a caller could append a future
    fact into an already-validated snapshot and every check would have passed
    before the append."""
    episode = _episode(store)
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    assert isinstance(snapshot.facts, tuple)
    assert isinstance(snapshot.relationships, tuple)
    assert isinstance(snapshot.events, tuple)
    assert isinstance(snapshot.identity_resolutions, tuple)
    with pytest.raises(AttributeError):
        snapshot.facts.append(snapshot.facts[0])  # type: ignore[attr-defined]


def test_mutating_a_returned_mapping_cannot_reach_back_into_the_snapshot(store) -> None:
    episode = _episode(store)
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    vector = snapshot.feature_vector()
    vector["injected"] = LEAK_NUMBER
    assert "injected" not in snapshot.feature_vector()


# --------------------------------------------------------------------------- #
# 4. FORGERY: the pydantic escape hatches that skip validators.
# --------------------------------------------------------------------------- #
def _future_fact(snapshot: DecisionSnapshot):
    template = snapshot.facts[0]
    return template.model_copy(
        update={
            "receipt": ReceiptStamp(
                receipt_time=snapshot.as_of + timedelta(minutes=5),
                receipt_sequence=999,
            )
        }
    )


def test_constructing_a_snapshot_with_a_future_item_is_refused(store) -> None:
    """LAYER 2, the construction-time check, exercised directly."""
    episode = _episode(store)
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    with pytest.raises(SnapshotLeakageError):
        DecisionSnapshot(
            snapshot_id=snapshot.snapshot_id,
            tenant_id=snapshot.tenant_id,
            as_of=snapshot.as_of,
            taken_receipt=snapshot.taken_receipt,
            purpose=snapshot.purpose,
            scope=snapshot.scope,
            facts=(*snapshot.facts, _future_fact(snapshot)),
        )


def test_model_copy_forgery_is_caught_by_verify_and_by_the_store(store) -> None:
    """`model_copy(update=...)` deliberately skips validators, so layer 2 never
    runs on a forged snapshot. Layers 4 (`content_hash`) and `verify()` are what
    remain, and both must catch it."""
    episode = _episode(store)
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    forged = snapshot.model_copy(
        update={"facts": (*snapshot.facts, _future_fact(snapshot))}
    )
    assert forged.content_hash != snapshot.content_hash
    with pytest.raises(SnapshotLeakageError):
        forged.verify()
    with pytest.raises(ForgedSnapshotError):
        store.record_action(
            action_kind=ActionKind.ASSIGN,
            subject_kind=ObjectKind.ASSIGNMENT,
            subject_id=episode["assignment"].object_id,
            input_snapshot=forged,
            policy_id=canonical_new_id(PolicyId),
            policy_version=1,
            authority=_system_authority(),
            decided_at=snapshot.as_of + timedelta(seconds=1),
            alternatives=(),
            verifier=_passing_verifier(),
        )


def test_moving_as_of_forward_changes_the_content_hash(store) -> None:
    """`as_of` is inside the hash. Without it, a forgery could relabel an old
    information set as a later decision instant and keep a matching hash -- and
    an action citing it would look like it was taken on fresher information than
    it was."""
    episode = _episode(store)
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    relabelled = snapshot.model_copy(
        update={"as_of": snapshot.as_of + timedelta(hours=1)}
    )
    assert relabelled.content_hash != snapshot.content_hash


def test_model_construct_forgery_is_caught_by_verify(store) -> None:
    """`model_construct` builds without running ANY validator. It is a forgery
    path, not a read path, which is why it sits in `_NOT_A_READ_PATH` -- and it
    is covered here rather than being left out."""
    episode = _episode(store)
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    forged = DecisionSnapshot.model_construct(
        snapshot_id=snapshot.snapshot_id,
        tenant_id=snapshot.tenant_id,
        as_of=snapshot.as_of,
        taken_receipt=snapshot.taken_receipt,
        purpose=snapshot.purpose,
        scope=snapshot.scope,
        facts=(*snapshot.facts, _future_fact(snapshot)),
        relationships=(),
        events=(),
        identity_resolutions=(),
        derived_from=None,
    )
    with pytest.raises(SnapshotLeakageError):
        forged.verify()


def test_an_action_cannot_cite_a_snapshot_this_store_never_took(store) -> None:
    from packages.ontology.store import UnknownSnapshotError

    episode = _episode(store)
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    orphan = snapshot.model_copy(
        update={"snapshot_id": canonical_new_id(SnapshotId)}
    )
    with pytest.raises(UnknownSnapshotError):
        store.record_action(
            action_kind=ActionKind.ASSIGN,
            subject_kind=ObjectKind.ASSIGNMENT,
            subject_id=episode["assignment"].object_id,
            input_snapshot=orphan,
            policy_id=canonical_new_id(PolicyId),
            policy_version=1,
            authority=_system_authority(),
            decided_at=snapshot.as_of + timedelta(seconds=1),
            alternatives=(),
            verifier=_passing_verifier(),
        )


# --------------------------------------------------------------------------- #
# 5. REPRODUCIBILITY: the reload path is a leak detector, not a cache read.
# --------------------------------------------------------------------------- #
def test_a_snapshot_rebuilt_after_the_future_arrives_is_byte_identical(store) -> None:
    """The property that makes an information set FINAL. The snapshot's content
    was never stored -- only its boundary, scope and hash -- so this reload
    re-runs the query against a store that now contains the future, and must
    reproduce exactly what it produced before."""
    episode = _episode(store)
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    before = snapshot.model_dump_json()
    _poison_after(store, episode)
    reloaded = store.load_snapshot(snapshot.snapshot_id)
    assert reloaded.content_hash == snapshot.content_hash
    assert reloaded.model_dump_json() == before


def test_reload_detects_a_row_written_behind_the_boundary(store) -> None:
    """SnapshotDriftError should be unreachable -- receipt monotonicity forbids
    the condition. Prove the detector works anyway, by forcing the condition
    with a raw INSERT after dropping the guard, exactly as an external audit
    would."""
    from packages.ontology.store import SnapshotDriftError

    episode = _episode(store)
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    database = store.database
    database.execute_ddl("DROP TRIGGER ontology_receipt_monotonic")
    database.execute(
        "INSERT INTO ontology_facts (fact_id, tenant_id, subject_kind, subject_id, "
        "attribute, fact_class, value_kind, value_number, value_text, value_bool, "
        "missing_reason, event_time, quality, confidence, repair_kind, repairs_fact_id, "
        "repair_note, sensitivity, special_category, legal_basis, source_system, "
        "source_record_id, receipt_time, receipt_sequence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(canonical_new_id(FactId)),
            str(store.tenant_id),
            ObjectKind.REQUEST.value,
            str(episode["request"].object_id),
            "smuggled_into_the_past",
            FactClass.OBSERVATION.value,
            "number",
            1.0,
            None,
            None,
            None,
            "2026-03-02T09:00:00.000000+00:00",
            QualityState.TRUSTED.value,
            None,
            "none",
            None,
            None,
            SensitivityClass.OPERATIONAL.value,
            0,
            LegalBasis.CONTRACT_PERFORMANCE.value,
            "attacker",
            "x",
            "2026-03-02T09:00:30.000000+00:00",  # BEFORE the snapshot boundary
            1,
        ),
    )
    database.commit()
    with pytest.raises(SnapshotDriftError):
        store.load_snapshot(snapshot.snapshot_id)


# --------------------------------------------------------------------------- #
# 6. PURPOSE, PRIVACY AND CONFLICT: the other things the snapshot must not do.
# --------------------------------------------------------------------------- #
def test_a_training_snapshot_excludes_facts_with_no_lawful_basis(store) -> None:
    episode = _episode(store)
    store.record_fact(
        subject_kind=ObjectKind.RIDER,
        subject_id=episode["rider"].object_id,
        attribute="home_ward",
        fact_class=FactClass.DECLARATION,
        quality=QualityState.PROVISIONAL,
        sensitivity=SensitivityClass.IDENTITY,
        legal_basis=LegalBasis.NOT_ESTABLISHED,
        source_system="legacy-crm",
        source_record_id="c-1",
        value="ward-4",
    )
    as_of = _after(store)
    dispatch = store.take_snapshot(
        as_of=as_of, scope=episode["scope"], purpose=SnapshotPurpose.OPERATIONAL_DISPATCH
    )
    training = store.take_snapshot(
        as_of=as_of, scope=episode["scope"], purpose=SnapshotPurpose.MODEL_TRAINING
    )
    assert dispatch.value_of(episode["rider"].object_id, "home_ward") == "ward-4"
    assert training.value_of(episode["rider"].object_id, "home_ward") is None
    assert all(f.trainable for f in training.facts)


def test_for_training_drops_a_fact_with_no_lawful_basis(store) -> None:
    """FOUND BY MUTATION M20. Removing the `if f.trainable` filter from
    `for_training()` left the whole suite GREEN: `_probes` only ever called it on
    an episode whose facts were all trainable, and the purpose-based test above
    goes through `take_snapshot`, not through this projection. Two independent
    paths reach a training snapshot and only one of them was covered.

    The projection is the more dangerous of the two, because it is the one a
    feature builder calls on a snapshot it was handed."""
    episode = _episode(store)
    store.record_fact(
        subject_kind=ObjectKind.RIDER,
        subject_id=episode["rider"].object_id,
        attribute="legacy_notes_flag",
        fact_class=FactClass.DECLARATION,
        quality=QualityState.PROVISIONAL,
        sensitivity=SensitivityClass.OPERATIONAL,
        legal_basis=LegalBasis.NOT_ESTABLISHED,
        source_system="legacy-crm",
        source_record_id="n-1",
        value=1.0,
    )
    dispatch = store.take_snapshot(
        as_of=_after(store),
        scope=episode["scope"],
        purpose=SnapshotPurpose.OPERATIONAL_DISPATCH,
    )
    assert dispatch.value_of(episode["rider"].object_id, "legacy_notes_flag") == 1.0
    training = dispatch.for_training()
    assert training.value_of(episode["rider"].object_id, "legacy_notes_flag") is None
    assert all(f.trainable for f in training.facts)
    assert training.purpose is SnapshotPurpose.MODEL_TRAINING
    assert training.as_of == dispatch.as_of, "a projection must not widen the boundary"
    assert not any("legacy_notes_flag" in key for key in training.feature_vector())


def test_a_snapshot_cannot_admit_another_tenants_item(store) -> None:
    """FOUND BY MUTATION M22. The cross-tenant check in the snapshot's validator
    was untested: the store's own `tenant_id = ?` conjunct means it never
    produces such an item, so the object-layer defence had nothing exercising
    it and could have been deleted silently.

    It is defence in depth and it matters: a snapshot can be constructed by
    something other than this store -- an evidence-pack reader, a replay
    importer, a future adapter -- and those have no SQL predicate protecting
    them."""
    episode = _episode(store)
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    foreign = snapshot.facts[0].model_copy(
        update={"tenant_id": canonical_new_id(TenantId)}
    )
    with pytest.raises(SnapshotLeakageError, match="another tenant|belonging"):
        DecisionSnapshot(
            snapshot_id=snapshot.snapshot_id,
            tenant_id=snapshot.tenant_id,
            as_of=snapshot.as_of,
            taken_receipt=snapshot.taken_receipt,
            purpose=snapshot.purpose,
            scope=snapshot.scope,
            facts=(foreign,),
        )
    # ...and `verify()` catches it too, for a snapshot that skipped validation.
    forged = snapshot.model_copy(update={"facts": (foreign,)})
    with pytest.raises(SnapshotLeakageError):
        forged.verify()


def test_special_category_data_cannot_be_held_with_no_stated_basis(store) -> None:
    episode = _episode(store)
    with pytest.raises(ValueError, match="not_established"):
        store.record_fact(
            subject_kind=ObjectKind.RIDER,
            subject_id=episode["rider"].object_id,
            attribute="mobility_device",
            fact_class=FactClass.DECLARATION,
            quality=QualityState.TRUSTED,
            sensitivity=SensitivityClass.IDENTITY,
            special_category=True,
            legal_basis=LegalBasis.NOT_ESTABLISHED,
            source_system="ops",
            source_record_id="e-1",
            value="wheelchair",
        )


def test_redaction_says_a_value_existed_rather_than_pretending_it_did_not(store) -> None:
    episode = _episode(store)
    store.record_fact(
        subject_kind=ObjectKind.RIDER,
        subject_id=episode["rider"].object_id,
        attribute="pickup_latitude",
        fact_class=FactClass.OBSERVATION,
        quality=QualityState.TRUSTED,
        sensitivity=SensitivityClass.PRECISE_LOCATION,
        legal_basis=LegalBasis.CONTRACT_PERFORMANCE,
        source_system="ops",
        source_record_id="g-1",
        value=51.5074,
        event_time=T_START,
    )
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    redacted = snapshot.redacted()
    assert snapshot.value_of(episode["rider"].object_id, "pickup_latitude") == 51.5074
    assert redacted.value_of(episode["rider"].object_id, "pickup_latitude") is None
    reasons = {a: r for _s, a, r in redacted.missing()}
    assert reasons["pickup_latitude"] is MissingnessReason.SUPPRESSED_PRIVACY, (
        "a redacted field must be distinguishable from one the operator never "
        "collected -- anyone computing coverage over the export depends on it"
    )
    assert redacted.derived_from == snapshot.snapshot_id
    assert redacted.as_of == snapshot.as_of, "redaction must not widen the boundary"


def test_redaction_is_deterministic(store) -> None:
    episode = _episode(store)
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    assert snapshot.redacted().snapshot_id == snapshot.redacted().snapshot_id


def test_disagreeing_sources_are_retained_and_value_of_refuses_to_guess(store) -> None:
    episode = _episode(store)
    for source, value in (("avl", 12.0), ("dispatcher_console", 19.0)):
        store.record_fact(
            subject_kind=ObjectKind.VEHICLE,
            subject_id=episode["vehicle"].object_id,
            attribute="securement_positions_free",
            fact_class=FactClass.OBSERVATION,
            quality=QualityState.CONFLICTED,
            sensitivity=SensitivityClass.OPERATIONAL,
            legal_basis=LegalBasis.CONTRACT_PERFORMANCE,
            source_system=source,
            source_record_id=f"{source}-1",
            value=value,
            event_time=T_START,
        )
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    assert len(snapshot.facts_for(episode["vehicle"].object_id, "securement_positions_free")) == 2
    with pytest.raises(ConflictedValueError):
        snapshot.value_of(episode["vehicle"].object_id, "securement_positions_free")
    assert (
        str(episode["vehicle"].object_id),
        "securement_positions_free",
    ) in {(str(s), a) for s, a in snapshot.conflicts()}
    assert not any(
        "securement_positions_free" in key for key in snapshot.feature_vector()
    ), "a conflicted attribute must be omitted from the feature vector, not averaged"


def test_an_unresolved_identity_keeps_every_candidate(store) -> None:
    episode = _episode(store)
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    unresolved = snapshot.unresolved_identities()
    assert len(unresolved) == 1
    assert unresolved[0].candidates[0].probability == 0.61
    assert unresolved[0].resolved_object_id is None
    assert unresolved[0].would_resolve() is None


def test_a_later_identity_resolution_is_invisible_to_the_earlier_snapshot(store) -> None:
    """The identity story and the leakage story are the same story: a match
    resolved tomorrow must not retroactively attribute today's trip."""
    episode = _episode(store)
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    store.record_identity_resolution(
        subject_kind=ObjectKind.RIDER,
        source_system="ops",
        source_record_id="booking-88",
        candidates=(
            MatchCandidate(
                candidate_object_id=episode["rider"].object_id,
                candidate_kind=ObjectKind.RIDER,
                probability=0.99,
                method="manual_review",
            ),
        ),
        resolved_object_id=episode["rider"].object_id,
        resolution_rule="unique-argmax>=0.95",
    )
    assert snapshot.unresolved_identities()[0].resolved_object_id is None
    later = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    assert any(r.is_resolved for r in later.identity_resolutions)


def test_a_snapshot_cannot_be_taken_as_of_the_future(store) -> None:
    episode = _episode(store)
    watermark = store.receipt_watermark()
    with pytest.raises(SnapshotLeakageError):
        DecisionSnapshot(
            snapshot_id=canonical_new_id(SnapshotId),
            tenant_id=store.tenant_id,
            as_of=watermark.receipt_time + timedelta(hours=1),
            taken_receipt=watermark,
            purpose=SnapshotPurpose.OPERATIONAL_DISPATCH,
            scope=episode["scope"],
        )


def test_a_relationship_retracted_after_the_boundary_still_holds_in_the_snapshot(
    store,
) -> None:
    """"Who did the dispatcher believe was driving?" -- not "who do we now think
    was driving?". A retraction is a later record, so an earlier snapshot must
    still show the edge."""
    episode = _episode(store)
    edge = store.assert_relationship(
        relationship_kind=RelationshipKind.DRIVER_OPERATES_VEHICLE,
        subject_kind=ObjectKind.DRIVER,
        subject_id=(
            driver := store.register_object(
                object_kind=ObjectKind.DRIVER, external_ref="d-1", source_system="ops"
            )
        ).object_id,
        object_kind=ObjectKind.VEHICLE,
        object_id=episode["vehicle"].object_id,
        asserted_by="roster",
    )
    scope = SnapshotScope(
        subject_ids=(*episode["scope"].subject_ids, driver.object_id)
    )
    snapshot = store.take_snapshot(as_of=_after(store), scope=scope)
    assert edge.relationship_id in {
        r.relationship_id for r in snapshot.relationships
    }
    store.assert_relationship(
        relationship_kind=RelationshipKind.DRIVER_OPERATES_VEHICLE,
        subject_kind=ObjectKind.DRIVER,
        subject_id=driver.object_id,
        object_kind=ObjectKind.VEHICLE,
        object_id=episode["vehicle"].object_id,
        asserted_by="roster",
        retracts_relationship_id=edge.relationship_id,
    )
    assert edge.relationship_id in {
        r.relationship_id for r in store.load_snapshot(snapshot.snapshot_id).relationships
    }
    after = store.take_snapshot(as_of=_after(store), scope=scope)
    assert edge.relationship_id not in {r.relationship_id for r in after.relationships}


def test_no_store_method_accepts_a_receipt_time(store) -> None:
    """THE 2026-07-26 AUDIT FINDING, CLOSED STRUCTURALLY. The defect was a
    caller-supplied transaction-time parameter. The repair is not that callers
    are asked not to pass one -- it is that no such parameter exists, read back
    from the signatures rather than from a docstring."""
    import inspect

    banned = {"receipt", "receipt_time", "recorded_at", "receipt_sequence", "ingested_at"}
    offenders = []
    for name, member in inspect.getmembers(OntologyStore, inspect.isfunction):
        if name.startswith("_"):
            continue
        for parameter in inspect.signature(member).parameters:
            if parameter in banned:
                offenders.append(f"{name}({parameter})")
    assert not offenders, (
        f"store method(s) accept a caller-supplied receipt time: {offenders}. That is "
        "the exact defect the external audit found in the lifecycle record"
    )


def test_snapshot_json_round_trips_without_admitting_anything_new(store) -> None:
    """A serialisation path is a read path, and a DEserialisation path is a
    construction path -- so the round trip must go back through the validator
    and still refuse a future item."""
    episode = _episode(store)
    snapshot = store.take_snapshot(as_of=_after(store), scope=episode["scope"])
    payload = json.loads(snapshot.model_dump_json())
    restored = DecisionSnapshot.model_validate(payload)
    assert restored.content_hash == snapshot.content_hash
    payload["facts"].append(json.loads(_future_fact(snapshot).model_dump_json()))
    with pytest.raises(SnapshotLeakageError):
        DecisionSnapshot.model_validate(payload)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _system_authority() -> Authority:
    return Authority(
        authority_kind=AuthorityKind.SYSTEM,
        actor_ref="scheduler",
        role="solver",
        permissions=frozenset({Permission.ASSIGNMENT_WRITE}),
    )


def _passing_verifier() -> VerifierResult:
    return VerifierResult(
        verdict=VerifierVerdict.PASS, verifier_name="mx-verify", verifier_version="0.1"
    )


def test_the_packet_vignette_is_representable_end_to_end(store) -> None:
    """The whole point, in one test: the episode from the packet's own
    description, written down and read back.

        this request arrived at 10:02; this wheelchair-accessible vehicle was
        expected free at 10:41; these three trips were mutually compatible; this
        assignment consumed two likely future pooling opportunities; the
        dispatcher overrode it; the resulting pickup was 14 minutes late
    """
    episode = _episode(store)
    third = store.register_object(
        object_kind=ObjectKind.REQUEST, external_ref="R-1004", source_system="ops"
    )
    store.assert_relationship(
        relationship_kind=RelationshipKind.ASSIGNMENT_FORECLOSED_POOLING_WITH,
        subject_kind=ObjectKind.ASSIGNMENT,
        subject_id=episode["assignment"].object_id,
        object_kind=ObjectKind.REQUEST,
        object_id=third.object_id,
        asserted_by="solver",
        weight=0.41,
    )
    scope = SnapshotScope(subject_ids=(*episode["scope"].subject_ids, third.object_id))
    as_of = _after(store)
    snapshot = store.take_snapshot(as_of=as_of, scope=scope)

    # ... the request arrived, and the vehicle was expected free at 10:41 ...
    assert snapshot.value_of(
        episode["request"].object_id, "requested_pickup_minute_of_day"
    ) == 602.0
    assert snapshot.value_of(
        episode["vehicle"].object_id, "expected_free_minute_of_day"
    ) == 641.0

    # ... the assignment consumed two likely future pooling opportunities ...
    foreclosed = snapshot.relationships_of(
        episode["assignment"].object_id,
        RelationshipKind.ASSIGNMENT_FORECLOSED_POOLING_WITH,
    )
    assert sorted(r.weight for r in foreclosed) == [0.41, 0.62]

    # ... the system recommended, the dispatcher overrode ...
    recommendation = store.record_action(
        action_kind=ActionKind.ASSIGN,
        subject_kind=ObjectKind.ASSIGNMENT,
        subject_id=episode["assignment"].object_id,
        input_snapshot=snapshot,
        policy_id=canonical_new_id(PolicyId),
        policy_version=4,
        authority=_system_authority(),
        decided_at=as_of + timedelta(seconds=2),
        alternatives=(
            ActionAlternative(
                rank=1,
                candidate_kind=ObjectKind.VEHICLE,
                candidate_id=episode["vehicle"].object_id,
                feasible=True,
                objective_delta=0.0,
            ),
            ActionAlternative(
                rank=2,
                candidate_kind=ObjectKind.VEHICLE,
                feasible=False,
                failed_constraints=(ReasonCode.NO_ACCESSIBLE_CAPACITY,),
            ),
        ),
        verifier=_passing_verifier(),
        prediction=ActionPrediction(
            metric="pickup_delay_minutes",
            point_estimate=3.0,
            interval_low=0.0,
            interval_high=11.0,
        ),
        reason_codes=(ReasonCode.PICKUP_WINDOW,),
    )
    override_snapshot = store.take_snapshot(as_of=_after(store), scope=scope)
    override = store.record_action(
        action_kind=ActionKind.REJECT_RECOMMENDATION,
        subject_kind=ObjectKind.ASSIGNMENT,
        subject_id=episode["assignment"].object_id,
        input_snapshot=override_snapshot,
        policy_id=canonical_new_id(PolicyId),
        policy_version=4,
        authority=Authority(
            authority_kind=AuthorityKind.HUMAN,
            actor_ref="dispatcher-token-7",
            role="senior_dispatcher",
            permissions=frozenset({Permission.RECOMMENDATION_DECIDE}),
        ),
        decided_at=override_snapshot.as_of + timedelta(seconds=30),
        alternatives=(),
        verifier=_passing_verifier(),
    )
    assert recommendation.was_automated
    assert not override.was_automated

    # ... and the resulting pickup was 14 minutes late.
    store.test_clock.advance(minutes=30)
    outcome = store.record_outcome(
        action_id=override.action_id,
        metric="pickup_delay_minutes",
        value=14.0,
        observed_at=override.decided_at + timedelta(minutes=20),
        source_system="avl",
        source_record_id="avl-1",
    )
    assert outcome.value == 14.0
    assert outcome.horizon_seconds == 1200.0
    # The outcome was received AFTER both decisions, so neither snapshot can see
    # it. That is the whole guarantee, restated on the concrete episode.
    assert outcome.receipt.receipt_sequence > override.receipt.receipt_sequence
    assert not any(
        f.attribute == "pickup_delay_minutes" for f in override_snapshot.facts
    )
    assert store.verify_integrity().intact
