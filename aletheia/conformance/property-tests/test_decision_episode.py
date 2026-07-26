"""THE LOAD-BEARING TEST: one decision episode, end to end, and provably closed.

ADR-0072 built the ontology and recorded its own central limitation -- "not
wired into the solver, forecaster, evidence packs or API". This file is the proof
that it now is: a snapshot is taken at T, a decision is made from it, actions and
denials and foreclosed pooling opportunities are written, an outcome arrives at
its own horizon, and the whole episode is RECONSTRUCTED from the action back to
exactly the information set that produced it.

FOUR THINGS THIS FILE DOES THAT A HAPPY-PATH TEST WOULD NOT.

  1. IT PROVES THE SEAM IS A SEAM. `themis/ontology` must not import `metis`,
     and an AST walk over every module in the package asserts it rather than
     trusting a convention. The seam is exercised against a REAL
     `metis.decide.ir.DecisionSolution` -- constructed here, not mocked -- so
     "the adapter reads a solver's output" is checked against the actual type
     and would fail the day its field names moved.

  2. IT RUNS THE LEAKAGE PROBE WITH TWO POSITIVE CONTROLS. A fact written at T+1
     must be invisible to the decision at T. That assertion is worthless unless
     the write actually landed and unless the boundary -- not the scope, not a
     typo in an attribute name -- is what excluded it. So the probe also asserts
     the poison IS visible through the store's unfiltered audit view, and IS
     admitted by a snapshot taken afterwards over the same scope. Without both,
     the probe would pass on a fact that was never written.

  3. IT DISTINGUISHES THE THREE ALTERNATIVE STATES BY WRITING ALL THREE. An
     empty `alternatives` tuple means "we do not know" by default and "nothing
     was on the table" only when a caller says so. Both are written, read back
     through the database, and checked -- and the database's own CHECK
     constraint is attacked directly with raw SQL, because a rule enforced only
     in pydantic is a rule an importer can walk around.

  4. IT ATTACKS ITS OWN GUARDS. The integrity check that compares the action's
     pinned hash against the re-derived one is exercised by DROPPING the
     append-only trigger and forging the row, the way the 2026-07-26 audit did
     -- because a check no test has ever seen fire is indistinguishable from a
     check that cannot.

DATA PROVENANCE: every fixture here is SYNTHETIC. There is no consented operator
data in this repository. Status of everything proven: Demonstrated -- never
Validated. In particular, nothing here says anything about how any real
scheduler records its rejections, how any real operator names a binding
constraint, or what any real fleet's foreclosure weights look like.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from themis.canonical.ids import PolicyId, RequestId, TenantId, VehicleId, new_id as canonical_new_id
from themis.canonical.vocab import ScheduleRunStatus
from themis.ontology import (
    ActionKind,
    AlternativesProvenance,
    Authority,
    AuthorityKind,
    ConsideredOption,
    DecisionResult,
    DecisionSeamError,
    EpisodeIntegrityError,
    EventKind,
    FactClass,
    ForeclosedOpportunity,
    ForgedSnapshotError,
    LateArrivalReason,
    LegalBasis,
    MissingnessReason,
    ObjectKind,
    Permission,
    ProposedAssignment,
    ProposedDenial,
    QualityState,
    ReasonCode,
    RelationshipKind,
    SensitivityClass,
    SnapshotScope,
    UnknownActionError,
    VerifierResult,
    VerifierVerdict,
    decision_result_from_solution,
    foreclosures_from_attribution,
    load_action,
    reconstruct_episode,
    record_decision_episode,
)
from themis.ontology.actions import ActionAlternative, ActionPrediction, ActionRecord
from themis.ontology.store import OntologyDatabase, OntologyStore

# --------------------------------------------------------------------------- #
# Fixtures. SYNTHETIC -- every reference, time and weight below is invented.
# --------------------------------------------------------------------------- #
T_START = datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc)
"""VALID-time origin of the vignette: the world's 10:00."""

CLOCK_START = T_START + timedelta(minutes=10)
"""RECEIPT-time origin. Deliberately LATER than the world's clock, because that
is the ordinary case in an operator's data and the one a fixture starting both at
the same instant would never exercise: the booking that happened at 10:02 reaches
Milexium at 10:10, which makes it a LATE ARRIVAL that has to declare itself."""

LEAK_TEXT = "EPISODE-LEAK-SENTINEL-4c81ea"
LEAK_NUMBER = 424242.5

SOLVER = "milexium.decide.portfolio"
SOLVER_VERSION = "0.6.1"


class ScriptedClock:
    """A deterministic receipt clock, driven only FORWARD.

    One-SECOND steps rather than the one-minute steps the snapshot suite uses,
    because an episode writes some thirty rows and a minute apiece would push
    every `TRIP_DENIED` event past `LATE_ARRIVAL_THRESHOLD_SECONDS` -- which
    would make this file's fixtures fail for a reason that has nothing to do with
    what it is testing.
    """

    def __init__(self, start: datetime = CLOCK_START, step: timedelta = timedelta(seconds=1)):
        self.now = start
        self.step = step

    def __call__(self) -> datetime:
        value = self.now
        self.now = self.now + self.step
        return value

    def advance(self, **delta) -> None:
        self.now = self.now + timedelta(**delta)


@pytest.fixture()
def store():
    database = OntologyDatabase.sqlite()
    clock = ScriptedClock()
    store = OntologyStore(database, canonical_new_id(TenantId), clock=clock)
    store.test_clock = clock
    yield store
    database.close()


def _authority(*, kind: AuthorityKind = AuthorityKind.SYSTEM, ref: str = "milexium.decide") -> Authority:
    return Authority(
        authority_kind=kind,
        actor_ref=ref,
        role="scheduler" if kind is AuthorityKind.SYSTEM else "dispatcher",
        permissions=frozenset(
            {Permission.ASSIGNMENT_WRITE, Permission.RECOMMENDATION_DECIDE}
        ),
    )


def _verifier(verdict: VerifierVerdict = VerifierVerdict.PASS) -> VerifierResult:
    return VerifierResult(
        verdict=verdict,
        verifier_name="metis.decide.feasibility",
        verifier_version="0.3.0",
        violated_rules=() if verdict is not VerifierVerdict.FAIL else ("max_ride_time",),
    )


def _world(store: OntologyStore) -> dict:
    """The packet's vignette, as objects and facts, BEFORE any decision.

    A wheelchair rider's request arriving at 10:02, two more trips that might
    pool with it, a wheelchair-accessible vehicle expected free at 10:41, and two
    likely future trips the assignment will be measured against.
    """
    objects = {
        "rider": store.register_object(
            object_kind=ObjectKind.RIDER, external_ref="rider-token-1", source_system="ops"
        ),
        "R-1002": store.register_object(
            object_kind=ObjectKind.REQUEST, external_ref="R-1002", source_system="ops"
        ),
        "R-1003": store.register_object(
            object_kind=ObjectKind.REQUEST, external_ref="R-1003", source_system="ops"
        ),
        "R-1004": store.register_object(
            object_kind=ObjectKind.REQUEST, external_ref="R-1004", source_system="ops"
        ),
        "R-2001": store.register_object(
            object_kind=ObjectKind.REQUEST, external_ref="R-2001", source_system="ops"
        ),
        "R-2002": store.register_object(
            object_kind=ObjectKind.REQUEST, external_ref="R-2002", source_system="ops"
        ),
        "B-101": store.register_object(
            object_kind=ObjectKind.VEHICLE, external_ref="B-101", source_system="ops"
        ),
    }
    store.record_fact(
        subject_kind=ObjectKind.REQUEST,
        subject_id=objects["R-1002"].object_id,
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
        subject_kind=ObjectKind.REQUEST,
        subject_id=objects["R-1002"].object_id,
        attribute="needs_wheelchair",
        fact_class=FactClass.DECLARATION,
        quality=QualityState.TRUSTED,
        sensitivity=SensitivityClass.OPERATIONAL,
        legal_basis=LegalBasis.LEGAL_OBLIGATION,
        special_category=True,
        source_system="ops",
        source_record_id="R-1002",
        value=True,
    )
    store.record_fact(
        subject_kind=ObjectKind.VEHICLE,
        subject_id=objects["B-101"].object_id,
        attribute="expected_free_minute_of_day",
        fact_class=FactClass.PREDICTION,
        quality=QualityState.PROVISIONAL,
        confidence=0.72,
        sensitivity=SensitivityClass.OPERATIONAL,
        legal_basis=LegalBasis.CONTRACT_PERFORMANCE,
        source_system="milexium.derivation",
        value=641.0,
        event_time=T_START + timedelta(minutes=41),
    )
    store.record_event(
        event_kind=EventKind.BOOKING_CREATED,
        subject_kind=ObjectKind.REQUEST,
        subject_id=objects["R-1002"].object_id,
        occurred_at=T_START + timedelta(minutes=2),
        actor_kind=AuthorityKind.HUMAN,
        actor_ref="dispatcher-token-7",
        # 10:02 in the world, ~10:10 in Milexium. Past the five-minute threshold,
        # so it must SAY why it was late rather than look contemporaneous.
        late_arrival_reason=LateArrivalReason.BATCH_EXPORT,
    )
    return objects


def _scope(objects: dict) -> SnapshotScope:
    return SnapshotScope(
        subject_ids=tuple(o.object_id for o in objects.values())
    )


def _subjects(objects: dict) -> dict:
    return {ref: obj.object_id for ref, obj in objects.items()}


def _result(
    *,
    provenance: AlternativesProvenance = AlternativesProvenance.NOT_RECORDED,
    considered: tuple[ConsideredOption, ...] = (),
    status: ScheduleRunStatus = ScheduleRunStatus.OPTIMAL,
    proven_optimal: bool = True,
    bound: float | None = 118.0,
    gap: float | None = 0.0,
) -> DecisionResult:
    """Two trips pooled onto B-101; a third denied for want of accessible capacity."""
    return DecisionResult(
        status=status,
        assignments=(
            ProposedAssignment(
                request_ref="R-1002",
                vehicle_ref="B-101",
                pickup_time=T_START + timedelta(minutes=41),
                dropoff_time=T_START + timedelta(minutes=63),
            ),
            ProposedAssignment(
                request_ref="R-1003",
                vehicle_ref="B-101",
                pickup_time=T_START + timedelta(minutes=45),
                dropoff_time=T_START + timedelta(minutes=70),
            ),
        ),
        denials=(
            ProposedDenial(
                request_ref="R-1004",
                binding_constraints=(ReasonCode.NO_ACCESSIBLE_CAPACITY,),
            ),
        ),
        considered=considered,
        alternatives_provenance=provenance,
        objective_value=118.0,
        bound=bound,
        gap=gap,
        proven_optimal=proven_optimal,
        seed=7,
        solver_name=SOLVER,
        solver_version=SOLVER_VERSION,
    )


FORECLOSURES = (
    ForeclosedOpportunity(
        by_request_ref="R-1002",
        foreclosed_request_ref="R-2001",
        weight=0.62,
        basis="metis.decide.exposure/0.4.0/exhaustive",
    ),
    ForeclosedOpportunity(
        by_request_ref="R-1002",
        foreclosed_request_ref="R-2002",
        weight=0.31,
        basis="metis.decide.exposure/0.4.0/exhaustive",
    ),
)


def _decide(
    store: OntologyStore,
    objects: dict,
    *,
    result: DecisionResult | None = None,
    foreclosures=FORECLOSURES,
    prediction: ActionPrediction | None = None,
    authority: Authority | None = None,
    verifier: VerifierResult | None = None,
    override_justification: str | None = None,
):
    """Take a snapshot, decide from it, and write the episode."""
    as_of = store.receipt_watermark().receipt_time + timedelta(seconds=1)
    snapshot = store.take_snapshot(as_of=as_of, scope=_scope(objects))
    recorded = record_decision_episode(
        store,
        snapshot=snapshot,
        result=result if result is not None else _result(),
        subjects=_subjects(objects),
        authority=authority or _authority(),
        policy_id=canonical_new_id(PolicyId),
        policy_version=3,
        decided_at=as_of + timedelta(seconds=1),
        verifier=verifier or _verifier(),
        foreclosures=foreclosures,
        predictions={"R-1002": prediction} if prediction is not None else None,
        override_justification=override_justification,
    )
    return snapshot, recorded


# =========================================================================== #
# 1. The seam between metis and themis
# =========================================================================== #
_ONTOLOGY_DIR = Path(__file__).resolve().parents[3] / "themis" / "ontology"


def test_the_ontology_imports_nothing_from_the_solver() -> None:
    """`metis/` may import TYPES from `themis/`; the reverse edge must not exist
    at all.

    Asserted by walking the AST of every module in the package rather than by
    convention, because the tempting shortcut -- "just import DecisionSolution,
    it is only a data class" -- is one line and would make the ontology
    un-loadable without the solver's dependency tree and un-testable without
    ortools.
    """
    offenders = []
    for path in sorted(_ONTOLOGY_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name == "metis" or name.startswith("metis."):
                    offenders.append(f"{path.name}: {name}")
    assert offenders == [], (
        f"themis/ontology imports metis: {offenders}. The decision seam is plain "
        "data and a structural adapter precisely so this edge does not exist"
    )


def test_the_solver_does_not_reach_into_the_ontology_either() -> None:
    """The other half of the seam, and the half no existing test covers.

    `test_layer_metis.py` derives which Themis modules are "persistence" from the
    WRITER METHOD NAMES they define. `themis/ontology/episode.py` defines none of
    them -- it delegates every write to `OntologyStore` -- so that derivation does
    not classify it, and a `from themis.ontology.episode import
    record_decision_episode` in the solver would pass the layering suite while
    handing Metis a write path to canonical state.

    This closes it from the ontology's side, by name, until the layering packet
    can classify the module properly. Recorded as an open item in
    MX-ONT-DECISION-EPISODE-016.
    """
    metis_dir = Path(__file__).resolve().parents[3] / "metis"
    offenders = []
    for path in sorted(metis_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name == "themis.ontology" or name.startswith("themis.ontology."):
                    offenders.append(f"{path.relative_to(metis_dir)}: {name}")
    assert offenders == [], (
        f"metis imports themis.ontology: {offenders}. An integration layer holding "
        "BOTH calls record_decision_episode; the solver never does, or the ontology "
        "becomes a dependency of the thing it is supposed to observe"
    )


def test_the_seam_reads_a_real_decision_solution_not_a_stand_in() -> None:
    """The adapter is exercised against `metis.decide.ir.DecisionSolution` itself.

    Against a hand-rolled stub it would pass forever, including on the day the
    solver renamed `unserved`. This constructs the real type -- which imports
    pydantic and `themis/canonical` only, so no CP-SAT backend is needed -- and
    reads it through the seam.
    """
    from metis.decide.ir import Assignment, Denial, DecisionSolution

    request, vehicle = canonical_new_id(RequestId), canonical_new_id(VehicleId)
    denied = canonical_new_id(RequestId)
    solution = DecisionSolution(
        status=ScheduleRunStatus.OPTIMAL,
        assignments=(
            Assignment(
                request_id=request,
                vehicle_id=vehicle,
                pickup_time=T_START,
                dropoff_time=T_START + timedelta(minutes=20),
            ),
        ),
        unserved=(
            Denial(request_id=denied, reason_codes=(ReasonCode.NO_ACCESSIBLE_CAPACITY,)),
        ),
        objective_value=42.0,
        bound=42.0,
        gap=0.0,
        seed=1,
        solver_name="cpsat",
        solver_version="9.15",
    )
    result = decision_result_from_solution(solution)

    assert result.status is ScheduleRunStatus.OPTIMAL
    assert result.proven_optimal is True
    assert result.assignments[0].request_ref == str(request)
    assert result.assignments[0].vehicle_ref == str(vehicle)
    assert result.denials[0].request_ref == str(denied)
    assert result.denials[0].binding_constraints == (ReasonCode.NO_ACCESSIBLE_CAPACITY,)
    # THE RULE THIS PACKET EXISTS FOR: a DecisionSolution records what it chose
    # and what it denied, and NOTHING about what it rejected.
    assert result.alternatives_provenance is AlternativesProvenance.NOT_RECORDED


def test_a_producer_that_drifts_from_the_seam_fails_at_the_seam() -> None:
    """A structural adapter must say WHICH attribute is missing, or it is just a
    slower `AttributeError` from somewhere further downstream."""

    class Drifted:
        status = ScheduleRunStatus.FEASIBLE
        assignments = ()
        # `unserved` renamed -- the exact drift an import would have hidden
        denials = ()

    with pytest.raises(DecisionSeamError) as excinfo:
        decision_result_from_solution(Drifted())
    assert "unserved" in str(excinfo.value)


def test_the_episode_reader_adds_no_write_path_and_no_store_method() -> None:
    """The reconstruction lives BESIDE the store, not on it.

    `test_the_store_exposes_no_generic_writer` pins the store's public surface
    and says every addition that reads must be checked for the point-in-time
    boundary. Rather than widen that pin, the reader is a free function that
    (a) is not on the store at all, and (b) contains no write SQL -- checked
    here by AST, so a future `INSERT` smuggled into the reader fails loudly.
    """
    from themis.ontology import episode as episode_module

    assert not hasattr(OntologyStore, "reconstruct_episode")
    assert not hasattr(OntologyStore, "load_action")

    tree = ast.parse(Path(episode_module.__file__).read_text(encoding="utf-8"))
    writes = re.compile(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|DROP|ALTER|CREATE)\b")
    offenders = [
        node.value[:60]
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and writes.search(node.value)
    ]
    assert offenders == [], (
        f"themis/ontology/episode.py contains write SQL: {offenders}. Every write "
        "in this package goes through a typed OntologyStore method"
    )


# =========================================================================== #
# 2. One episode, end to end
# =========================================================================== #
def test_one_decision_episode_flows_from_snapshot_to_outcome(store) -> None:
    """THE PACKET, IN ONE TEST. Snapshot -> decision -> action -> outcome, and
    the reconstruction recovers exactly the information set that produced it."""
    objects = _world(store)
    prediction = ActionPrediction(
        metric="pickup_delay_minutes",
        point_estimate=4.0,
        interval_low=0.0,
        interval_high=9.0,
    )
    snapshot, recorded = _decide(store, objects, prediction=prediction)

    action = recorded.action_for("R-1002")
    assert action.action_kind is ActionKind.ASSIGN
    assert action.input_snapshot_id == snapshot.snapshot_id
    assert action.input_snapshot_hash == snapshot.content_hash
    assert action.policy_version == 3
    assert action.verifier.verdict is VerifierVerdict.PASS
    assert action.was_automated is True

    # The outcome arrives LATER, at its own horizon, as its own row.
    store.test_clock.advance(minutes=20)
    outcome = store.record_outcome(
        action_id=action.action_id,
        metric="pickup_delay_minutes",
        value=14.0,
        observed_at=action.decided_at + timedelta(minutes=14),
        source_system="avl",
        source_record_id="avl-991",
    )
    assert outcome.receipt.receipt_sequence > action.receipt.receipt_sequence

    episode = reconstruct_episode(store, action.action_id)

    # -- the information set is the one the decision cited, re-derived --------- #
    assert episode.information_set.content_hash == action.input_snapshot_hash
    assert episode.information_set.as_of == snapshot.as_of
    assert {str(f.fact_id) for f in episode.information_set.facts} == {
        str(f.fact_id) for f in snapshot.facts
    }
    # "this wheelchair-accessible vehicle was expected free at 10:41"
    assert episode.information_set.value_of(
        objects["B-101"].object_id, "expected_free_minute_of_day"
    ) == 641.0
    # "this request arrived at 10:02"
    booking = episode.information_set.events_of(EventKind.BOOKING_CREATED)
    assert booking[0].occurred_at == T_START + timedelta(minutes=2)

    # -- what else was on the table, and what it means ------------------------ #
    assert episode.action.alternatives == ()
    assert episode.alternatives_are_unknown is True

    # -- the binding constraint where a request was denied -------------------- #
    denied_id = str(objects["R-1004"].object_id)
    assert episode.binding_constraints() == (
        (denied_id, (ReasonCode.NO_ACCESSIBLE_CAPACITY,)),
    )

    # -- "consumed two likely future pooling opportunities" ------------------- #
    assert len(episode.foreclosed) == 2
    assert sorted(e.weight for e in episode.foreclosed) == [0.31, 0.62]
    assert {str(e.object_id) for e in episode.foreclosed} == {
        str(objects["R-2001"].object_id),
        str(objects["R-2002"].object_id),
    }
    assert all("exhaustive" in e.asserted_by for e in episode.foreclosed)

    # -- "the resulting pickup was 14 minutes late" --------------------------- #
    recovered = episode.outcome("pickup_delay_minutes")
    assert recovered is not None and recovered.value == 14.0
    assert recovered.horizon_seconds == 14 * 60.0
    # The prediction said 4 and the outcome said 14. They live in different rows,
    # so the model can still be scored honestly -- which is the entire reason
    # ActionPrediction and ActionOutcome are separate types.
    assert episode.action.prediction.point_estimate == 4.0

    assert store.verify_integrity().intact


def test_the_episode_reconstructs_in_a_fresh_process(tmp_path: Path) -> None:
    """A reconstruction that only works while the writer is still in memory
    proves nothing. This one closes the database, reopens it, and rebuilds the
    episode from the rows alone."""
    path = str(tmp_path / "episode.sqlite3")
    tenant = canonical_new_id(TenantId)
    first = OntologyDatabase.sqlite(path)
    clock = ScriptedClock()
    writer = OntologyStore(first, tenant, clock=clock)
    writer.test_clock = clock
    objects = _world(writer)
    snapshot, recorded = _decide(writer, objects)
    action_id = recorded.action_for("R-1002").action_id
    expected_hash = snapshot.content_hash
    first.close()

    second = OntologyDatabase.sqlite(path)
    try:
        reader = OntologyStore(second, tenant, clock=ScriptedClock())
        episode = reconstruct_episode(reader, action_id)
        assert episode.information_set.content_hash == expected_hash
        assert episode.action.action_id == action_id
        assert len(episode.denials) == 1
        assert len(episode.foreclosed) == 2
    finally:
        second.close()


def test_an_unknown_action_is_a_lookup_failure_not_an_empty_episode(store) -> None:
    """An episode that quietly reconstructs to nothing is worse than one that
    refuses: a caller would export it."""
    from themis.ontology.ids import ActionId, new_id

    with pytest.raises(UnknownActionError):
        reconstruct_episode(store, new_id(ActionId))


def test_the_denials_of_one_decision_are_not_the_denials_of_another(store) -> None:
    """THE ANTI-VACUITY CASE FOR THE EPISODE KEY. With one decision in the
    database, "gather the denials" is right however it is written -- including
    "gather every denial". Two decisions, each denying a DIFFERENT request, is
    the fixture that makes the snapshot-id filter do work."""
    objects = _world(store)
    _first_snapshot, first = _decide(store, objects)

    second_result = DecisionResult(
        status=ScheduleRunStatus.FEASIBLE,
        assignments=(
            ProposedAssignment(
                request_ref="R-1004",
                vehicle_ref="B-101",
                pickup_time=T_START + timedelta(minutes=80),
                dropoff_time=T_START + timedelta(minutes=95),
            ),
        ),
        denials=(
            ProposedDenial(
                request_ref="R-2001",
                binding_constraints=(ReasonCode.SHIFT_END, ReasonCode.PICKUP_WINDOW),
            ),
        ),
        alternatives_provenance=AlternativesProvenance.NOT_RECORDED,
        objective_value=61.0,
        proven_optimal=False,
        seed=8,
        solver_name=SOLVER,
        solver_version=SOLVER_VERSION,
    )
    _second_snapshot, second = _decide(
        store, objects, result=second_result, foreclosures=()
    )

    first_episode = reconstruct_episode(store, first.action_for("R-1002").action_id)
    second_episode = reconstruct_episode(store, second.action_for("R-1004").action_id)

    assert [c for _, c in first_episode.binding_constraints()] == [
        (ReasonCode.NO_ACCESSIBLE_CAPACITY,)
    ]
    assert [c for _, c in second_episode.binding_constraints()] == [
        (ReasonCode.SHIFT_END, ReasonCode.PICKUP_WINDOW)
    ]
    assert first_episode.denials[0].event_id != second_episode.denials[0].event_id


def test_an_outcome_belongs_to_its_own_action_and_no_other(store) -> None:
    """The same anti-vacuity shape for outcomes: two actions, two outcomes, and
    a reconstruction that must not hand one action the other's label."""
    objects = _world(store)
    _snapshot, recorded = _decide(store, objects)
    pooled = recorded.action_for("R-1002")
    other = recorded.action_for("R-1003")

    store.test_clock.advance(minutes=30)
    store.record_outcome(
        action_id=pooled.action_id,
        metric="pickup_delay_minutes",
        value=14.0,
        observed_at=pooled.decided_at + timedelta(minutes=14),
        source_system="avl",
        source_record_id="avl-1",
    )
    store.record_outcome(
        action_id=other.action_id,
        metric="pickup_delay_minutes",
        value=2.0,
        observed_at=other.decided_at + timedelta(minutes=2),
        source_system="avl",
        source_record_id="avl-2",
    )

    assert reconstruct_episode(store, pooled.action_id).outcome(
        "pickup_delay_minutes"
    ).value == 14.0
    assert reconstruct_episode(store, other.action_id).outcome(
        "pickup_delay_minutes"
    ).value == 2.0
    assert len(reconstruct_episode(store, pooled.action_id).outcomes) == 1


def test_the_foreclosed_opportunities_of_one_assignment_are_its_own(store) -> None:
    """Two assignments were written; only one foreclosed anything. An episode
    that reported both assignments' edges against either would be indistinguishable
    from a correct one on a single-assignment fixture."""
    objects = _world(store)
    _snapshot, recorded = _decide(store, objects)
    assert len(reconstruct_episode(store, recorded.action_for("R-1002").action_id).foreclosed) == 2
    assert reconstruct_episode(store, recorded.action_for("R-1003").action_id).foreclosed == ()


# =========================================================================== #
# 3. NO LEAKAGE. The probe, with its controls.
# =========================================================================== #
def _poison(store: OntologyStore, objects: dict) -> None:
    """Facts that became known AFTER the decision, each carrying a sentinel."""
    store.record_fact(
        subject_kind=ObjectKind.REQUEST,
        subject_id=objects["R-1002"].object_id,
        attribute="leaked_numeric",
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
        subject_id=objects["R-1002"].object_id,
        attribute="leaked_text",
        fact_class=FactClass.OBSERVATION,
        quality=QualityState.TRUSTED,
        sensitivity=SensitivityClass.OPERATIONAL,
        legal_basis=LegalBasis.CONTRACT_PERFORMANCE,
        source_system="ops",
        source_record_id="after-2",
        value=LEAK_TEXT,
        event_time=T_START,
    )


def test_a_fact_written_after_the_decision_is_invisible_to_it(store) -> None:
    """THE PROBE. A fact that became known at T+1 cannot appear in a decision
    taken at T, through the reconstruction or through anything it renders.

    TWO POSITIVE CONTROLS, because the assertion above is satisfied by a write
    that never happened and by a fact excluded for the wrong reason:

      * the store's unfiltered audit view MUST contain the poison -- otherwise
        the write silently failed and this test proves nothing;
      * a snapshot taken AFTERWARDS over the SAME SCOPE must admit it -- which
        rules out the scope, the attribute name and the tenant as the thing that
        excluded it, leaving only the receipt boundary.
    """
    objects = _world(store)
    _snapshot, recorded = _decide(store, objects)
    action = recorded.action_for("R-1002")

    _poison(store, objects)

    episode = reconstruct_episode(store, action.action_id)
    rendered = json.dumps(episode.information_set.model_dump(mode="json"), default=str)
    rendered += json.dumps(episode.to_record(), default=str)
    rendered += json.dumps(list(episode.information_set.provenance_manifest()), default=str)
    rendered += json.dumps(episode.information_set.feature_vector(), default=str)

    assert LEAK_TEXT not in rendered
    assert str(LEAK_NUMBER) not in rendered
    assert not any(
        f.attribute.startswith("leaked_") for f in episode.information_set.facts
    )
    # The information set is BYTE-IDENTICAL to the one the action pinned, after
    # two facts were written into the same tenant, same scope, same subject.
    assert episode.information_set.content_hash == action.input_snapshot_hash

    # -- control 1: the poison exists and is reachable ------------------------ #
    history = store.fact_history(objects["R-1002"].object_id, "leaked_text")
    assert [f.value for f in history] == [LEAK_TEXT], (
        "the poisoning write did not land, so every 'no leak' assertion above was "
        "passing for the wrong reason"
    )

    # -- control 2: the BOUNDARY is what excluded it -------------------------- #
    later = store.take_snapshot(
        as_of=store.receipt_watermark().receipt_time + timedelta(seconds=1),
        scope=_scope(objects),
    )
    assert later.value_of(objects["R-1002"].object_id, "leaked_text") == LEAK_TEXT, (
        "a snapshot taken after the poison did not admit it either, so the scope "
        "or the subject -- not the receipt boundary -- is what this test is "
        "measuring"
    )


def test_the_outcome_is_reachable_through_the_action_and_not_the_information_set(store) -> None:
    """The episode's central asymmetry: the information set is cut at `as_of`,
    everything that followed is not, and the two arrive by different routes.

    A label that could be reached from the snapshot would make every model
    trained on these episodes worthless, so this asserts the label is present in
    the episode and absent from the information set at the same instant.
    """
    objects = _world(store)
    _snapshot, recorded = _decide(store, objects)
    action = recorded.action_for("R-1002")
    store.test_clock.advance(minutes=20)
    store.record_outcome(
        action_id=action.action_id,
        metric="pickup_delay_minutes",
        value=14.0,
        observed_at=action.decided_at + timedelta(minutes=14),
        source_system="avl",
        source_record_id="avl-1",
    )

    episode = reconstruct_episode(store, action.action_id)
    assert episode.outcome("pickup_delay_minutes").value == 14.0
    information = json.dumps(
        episode.information_set.model_dump(mode="json"), default=str
    )
    assert "pickup_delay_minutes" not in information
    assert "14.0" not in json.dumps(
        episode.information_set.feature_vector(), default=str
    )


def test_a_forged_information_set_cannot_be_cited_by_an_episode(store) -> None:
    """`model_copy(update=...)` skips pydantic validators by design, so a
    snapshot with an extra fact is one line away. The episode write path inherits
    `record_action`'s hash comparison and refuses it."""
    objects = _world(store)
    as_of = store.receipt_watermark().receipt_time + timedelta(seconds=1)
    snapshot = store.take_snapshot(as_of=as_of, scope=_scope(objects))
    _poison(store, objects)
    later = store.take_snapshot(
        as_of=store.receipt_watermark().receipt_time + timedelta(seconds=1),
        scope=_scope(objects),
    )
    forged = snapshot.model_copy(update={"facts": later.facts})
    assert any(f.attribute == "leaked_text" for f in forged.facts), (
        "the forgery did not actually add a post-boundary fact, so the refusal "
        "below would be proving nothing"
    )

    with pytest.raises(ForgedSnapshotError):
        record_decision_episode(
            store,
            snapshot=forged,
            result=_result(),
            subjects=_subjects(objects),
            authority=_authority(),
            policy_id=canonical_new_id(PolicyId),
            policy_version=1,
            decided_at=as_of + timedelta(seconds=1),
            verifier=_verifier(),
        )


def test_reconstruction_refuses_an_action_whose_information_set_no_longer_matches(
    store,
) -> None:
    """THE GUARD, ATTACKED THE WAY THE 2026-07-26 AUDIT ATTACKED THE LAST ONE.

    The append-only trigger is DROPPED and the action's pinned hash is forged by
    raw SQL, because a check that no test has ever seen fire is
    indistinguishable from a check that cannot. Note what does NOT fire:
    `load_snapshot`'s own drift check passes, because the SNAPSHOT row is
    untouched. Only the action-side comparison sees this, which is why it is a
    separate step.
    """
    objects = _world(store)
    _snapshot, recorded = _decide(store, objects)
    action = recorded.action_for("R-1002")

    store.database.execute_ddl("DROP TRIGGER ontology_actions_no_update")
    store.database.execute(
        "UPDATE ontology_actions SET input_snapshot_hash = ? WHERE action_id = ?",
        ("f" * 64, str(action.action_id)),
    )
    store.database.commit()

    with pytest.raises(EpisodeIntegrityError) as excinfo:
        reconstruct_episode(store, action.action_id)
    assert str(action.input_snapshot_id) in str(excinfo.value)


# =========================================================================== #
# 4. Unknown is not empty: the third alternatives state
# =========================================================================== #
def test_a_producer_that_records_no_rejections_yields_unknown_not_nothing(store) -> None:
    """The rule the packet turns on. An action from a solver that does not export
    what it rejected must read as UNKNOWN, at the object, in the database, and
    after a round trip."""
    objects = _world(store)
    _snapshot, recorded = _decide(store, objects)
    action = recorded.action_for("R-1002")

    assert action.alternatives == ()
    assert action.alternatives_provenance is AlternativesProvenance.NOT_RECORDED
    assert action.alternatives_are_unknown is True
    assert load_action(store, action.action_id).alternatives_are_unknown is True


def test_none_considered_is_reachable_only_by_a_caller_who_says_so(store) -> None:
    """"The choice was forced" is a real and highly informative record. It is
    also an ASSERTION, so it must be made by a caller under their own name and
    never inferred from an empty list."""
    objects = _world(store)
    forced = _result(provenance=AlternativesProvenance.NONE_CONSIDERED)
    _snapshot, recorded = _decide(store, objects, result=forced)
    action = recorded.action_for("R-1002")

    assert action.alternatives == ()
    assert action.alternatives_provenance is AlternativesProvenance.NONE_CONSIDERED
    assert action.alternatives_are_unknown is False
    assert (
        load_action(store, action.action_id).alternatives_provenance
        is AlternativesProvenance.NONE_CONSIDERED
    )


def test_the_solution_adapter_has_no_parameter_that_could_claim_none_considered() -> None:
    """Read back by `inspect.signature` rather than asserted in prose.

    A `DecisionSolution` cannot support the claim, so the adapter must not offer
    a way to make it -- especially during a backfill, where a single default
    would assert "the choice was forced" over an operator's entire history.
    """
    parameters = inspect.signature(decision_result_from_solution).parameters
    assert set(parameters) == {"solution", "considered"}
    assert "provenance" not in parameters


def test_enumerated_and_empty_contradict_each_other_in_both_directions() -> None:
    """All four combinations, because a one-directional check passes on the half
    of the cases it never sees."""
    common = dict(
        status=ScheduleRunStatus.FEASIBLE,
        assignments=(
            ProposedAssignment(
                request_ref="R-1",
                vehicle_ref="B-1",
                pickup_time=T_START,
                dropoff_time=T_START + timedelta(minutes=10),
            ),
        ),
        objective_value=1.0,
        proven_optimal=False,
        seed=1,
        solver_name="s",
        solver_version="v",
    )
    option = ConsideredOption(
        request_ref="R-1",
        rank=2,
        candidate_kind=ObjectKind.VEHICLE,
        feasible=False,
        failed_constraints=(ReasonCode.SHIFT_END,),
    )
    # legal: enumerated WITH options, and each empty state WITHOUT them
    DecisionResult(
        **common,
        considered=(option,),
        alternatives_provenance=AlternativesProvenance.ENUMERATED,
    )
    for empty_state in (
        AlternativesProvenance.NONE_CONSIDERED,
        AlternativesProvenance.NOT_RECORDED,
    ):
        DecisionResult(**common, considered=(), alternatives_provenance=empty_state)
        with pytest.raises(Exception):
            DecisionResult(
                **common, considered=(option,), alternatives_provenance=empty_state
            )
    with pytest.raises(Exception):
        DecisionResult(
            **common,
            considered=(),
            alternatives_provenance=AlternativesProvenance.ENUMERATED,
        )


def test_the_action_record_refuses_the_same_contradiction() -> None:
    """The rule holds on the model too, not only on the seam -- an evidence-pack
    importer constructs `ActionRecord` directly and never sees `DecisionResult`."""
    base = _action_kwargs()
    with pytest.raises(Exception):
        ActionRecord(
            **base,
            alternatives=(),
            alternatives_provenance=AlternativesProvenance.ENUMERATED,
        )
    alternative = ActionAlternative(
        rank=2, candidate_kind=ObjectKind.VEHICLE, feasible=True
    )
    with pytest.raises(Exception):
        ActionRecord(
            **base,
            alternatives=(alternative,),
            alternatives_provenance=AlternativesProvenance.NOT_RECORDED,
        )
    # and omitted, a NON-EMPTY tuple deduces ENUMERATED while an EMPTY one does
    # not deduce NONE_CONSIDERED
    assert (
        ActionRecord(**base, alternatives=(alternative,)).alternatives_provenance
        is AlternativesProvenance.ENUMERATED
    )
    assert (
        ActionRecord(**base, alternatives=()).alternatives_provenance
        is AlternativesProvenance.NOT_RECORDED
    )


def _action_kwargs() -> dict:
    from themis.ontology.ids import ActionId, ObjectId, SnapshotId, new_id
    from themis.ontology.receipt import ReceiptStamp

    return dict(
        action_id=new_id(ActionId),
        tenant_id=canonical_new_id(TenantId),
        action_kind=ActionKind.ASSIGN,
        subject_kind=ObjectKind.ASSIGNMENT,
        subject_id=new_id(ObjectId),
        input_snapshot_id=new_id(SnapshotId),
        input_snapshot_hash="a" * 64,
        input_snapshot_as_of=T_START,
        policy_id=canonical_new_id(PolicyId),
        policy_version=1,
        verifier=_verifier(),
        authority=_authority(),
        decided_at=T_START,
        receipt=ReceiptStamp(receipt_time=T_START, receipt_sequence=1),
        hash="b" * 64,
    )


def test_the_database_refuses_the_contradiction_independently_of_the_model(store) -> None:
    """A rule enforced only in pydantic is a rule a replay importer, an evidence
    pack loader or a psql session walks around. The CHECK constraint is attacked
    directly."""
    objects = _world(store)
    _snapshot, recorded = _decide(store, objects)
    action = recorded.action_for("R-1002")

    store.database.execute_ddl("DROP TRIGGER ontology_actions_no_update")
    with pytest.raises(sqlite3.IntegrityError):
        store.database.execute(
            "UPDATE ontology_actions SET alternatives_provenance = 'enumerated' "
            "WHERE action_id = ?",
            (str(action.action_id),),
        )
    store.database.rollback()


def test_the_three_states_survive_the_round_trip_through_the_database(store) -> None:
    """Written, read back through raw rows, and still three distinct states.

    Without this, a reader that hardcoded one value would pass every test above,
    because every test above reads the object the writer returned.
    """
    objects = _world(store)
    option = ConsideredOption(
        request_ref="R-1002",
        rank=2,
        candidate_kind=ObjectKind.VEHICLE,
        feasible=False,
        failed_constraints=(ReasonCode.NO_ACCESSIBLE_CAPACITY,),
        objective_delta=12.5,
    )
    seen = {}
    for state, considered in (
        (AlternativesProvenance.NOT_RECORDED, ()),
        (AlternativesProvenance.NONE_CONSIDERED, ()),
        (AlternativesProvenance.ENUMERATED, (option,)),
    ):
        _snapshot, recorded = _decide(
            store,
            objects,
            result=_result(provenance=state, considered=considered),
            foreclosures=(),
        )
        seen[state] = {
            ref: load_action(store, recorded.action_for(ref).action_id)
            for ref in ("R-1002", "R-1003")
        }

    assert seen[AlternativesProvenance.NOT_RECORDED][
        "R-1002"
    ].alternatives_provenance is AlternativesProvenance.NOT_RECORDED
    assert seen[AlternativesProvenance.NONE_CONSIDERED][
        "R-1002"
    ].alternatives_provenance is AlternativesProvenance.NONE_CONSIDERED
    # THE DEDUCTION, PINNED. R-1003 had no options listed inside a result whose
    # enumeration is complete, so its placement was FORCED -- not unknown. If
    # this ever reads NOT_RECORDED, an enumerating producer's forced placements
    # are being discarded as missing data.
    assert seen[AlternativesProvenance.ENUMERATED][
        "R-1003"
    ].alternatives_provenance is AlternativesProvenance.NONE_CONSIDERED
    assert seen[AlternativesProvenance.ENUMERATED]["R-1003"].alternatives == ()
    assert (
        seen[AlternativesProvenance.ENUMERATED]["R-1003"].alternatives_are_unknown
        is False
    )
    # ...and the same row under a NOT_RECORDED result IS unknown, which is the
    # comparison that makes the line above mean something.
    assert (
        seen[AlternativesProvenance.NOT_RECORDED]["R-1003"].alternatives_are_unknown
        is True
    )
    enumerated = seen[AlternativesProvenance.ENUMERATED]["R-1002"]
    assert enumerated.alternatives_provenance is AlternativesProvenance.ENUMERATED
    assert enumerated.alternatives[0].rank == 2
    assert enumerated.alternatives[0].failed_constraints == (
        ReasonCode.NO_ACCESSIBLE_CAPACITY,
    )
    assert enumerated.alternatives[0].objective_delta == 12.5
    assert enumerated.alternatives_are_unknown is False


def test_a_considered_option_may_not_take_the_rank_of_the_option_that_was_taken() -> None:
    """Rank 1 is the action itself. An "alternative" at rank 1 would make the
    taken option appear twice and any "how much worse was the runner-up?" query
    silently wrong."""
    with pytest.raises(Exception):
        ConsideredOption(
            request_ref="R-1",
            rank=1,
            candidate_kind=ObjectKind.VEHICLE,
            feasible=True,
        )


# =========================================================================== #
# 5. Nothing is invented: denials, foreclosures, identities
# =========================================================================== #
def test_a_denial_must_name_the_constraint_that_bound() -> None:
    """"No, reason unrecorded" is the answer the episode record exists to make
    impossible -- and the one an operator's appeals process cannot act on."""
    with pytest.raises(Exception):
        ProposedDenial(request_ref="R-1004", binding_constraints=())


def test_a_foreclosed_opportunity_cannot_be_asserted_without_a_weight() -> None:
    """The opportunity was never certain. Asserting it outright would turn an
    estimate of what MIGHT have been possible into a record of what was."""
    with pytest.raises(Exception):
        ForeclosedOpportunity(
            by_request_ref="R-1002", foreclosed_request_ref="R-2001", basis="x"
        )


def test_an_unattributable_denial_produces_no_foreclosure_edges() -> None:
    """`metis.decide.exposure` refuses to attribute a denial that an EMPTY fleet
    could not have served either -- the denial is a structural gap in the
    service, and blaming another rider's trip for it would be false. The seam
    inherits the refusal rather than restating the judgement."""

    class Structural:
        request_id = "R-9"
        servable_in_isolation = False
        enumeration_complete = True
        participation = (("R-1", 1.0),)

    assert foreclosures_from_attribution(Structural()) == ()


def test_a_bounded_enumeration_is_recorded_as_bounded(store) -> None:
    """A partial search makes every weight a LOWER bound and a relationship row
    has nowhere else to say so, so it goes into `asserted_by` and survives the
    round trip."""

    class Bounded:
        request_id = "R-2001"
        servable_in_isolation = True
        enumeration_complete = False
        participation = (("R-1002", 0.5),)

    opportunities = foreclosures_from_attribution(Bounded())
    assert len(opportunities) == 1
    assert opportunities[0].weight == 0.5
    assert "bounded" in opportunities[0].basis

    objects = _world(store)
    _snapshot, recorded = _decide(store, objects, foreclosures=opportunities)
    episode = reconstruct_episode(store, recorded.action_for("R-1002").action_id)
    assert len(episode.foreclosed) == 1
    assert "bounded" in episode.foreclosed[0].asserted_by
    assert episode.foreclosed[0].weight == 0.5


def test_an_attribution_that_names_the_denied_trip_itself_is_dropped() -> None:
    """A reflexive edge is refused by `Relationship`, so it must not reach one:
    an attribution listing the denied request among its own blockers would abort
    the whole episode write."""

    class SelfBlocking:
        request_id = "R-2001"
        servable_in_isolation = True
        enumeration_complete = True
        participation = (("R-2001", 1.0), ("R-1002", 0.5))

    opportunities = foreclosures_from_attribution(SelfBlocking())
    assert [o.by_request_ref for o in opportunities] == ["R-1002"]


def test_the_episode_will_not_mint_an_identity_to_make_a_write_succeed(store) -> None:
    """An object registered to satisfy a reference is how a decision episode
    acquires a subject nobody recognises -- and it would be invisible, because
    the write would succeed."""
    objects = _world(store)
    as_of = store.receipt_watermark().receipt_time + timedelta(seconds=1)
    snapshot = store.take_snapshot(as_of=as_of, scope=_scope(objects))
    subjects = _subjects(objects)
    del subjects["R-1003"]

    before = len(store.database.query("SELECT object_id FROM ontology_objects"))
    with pytest.raises(LookupError) as excinfo:
        record_decision_episode(
            store,
            snapshot=snapshot,
            result=_result(),
            subjects=subjects,
            authority=_authority(),
            policy_id=canonical_new_id(PolicyId),
            policy_version=1,
            decided_at=as_of + timedelta(seconds=1),
            verifier=_verifier(),
        )
    assert "R-1003" in str(excinfo.value)
    after = len(store.database.query("SELECT object_id FROM ontology_objects"))
    assert after == before + 1, (
        "exactly the one ASSIGNMENT object for the placement that DID resolve "
        "should exist; a request object minted to satisfy the missing reference "
        "would push this higher"
    )


def test_a_foreclosure_attributed_to_a_placement_that_was_never_made_is_refused(
    store,
) -> None:
    objects = _world(store)
    with pytest.raises(LookupError):
        _decide(
            store,
            objects,
            foreclosures=(
                ForeclosedOpportunity(
                    by_request_ref="R-1004",  # denied, not assigned
                    foreclosed_request_ref="R-2001",
                    weight=0.5,
                    basis="metis.decide.exposure/0.4.0/exhaustive",
                ),
            ),
        )


def test_a_result_cannot_both_serve_and_deny_the_same_request() -> None:
    with pytest.raises(Exception):
        DecisionResult(
            status=ScheduleRunStatus.FEASIBLE,
            assignments=(
                ProposedAssignment(
                    request_ref="R-1",
                    vehicle_ref="B-1",
                    pickup_time=T_START,
                    dropoff_time=T_START + timedelta(minutes=5),
                ),
            ),
            denials=(
                ProposedDenial(
                    request_ref="R-1", binding_constraints=(ReasonCode.SHIFT_END,)
                ),
            ),
            alternatives_provenance=AlternativesProvenance.NOT_RECORDED,
            proven_optimal=False,
            seed=1,
            solver_name="s",
            solver_version="v",
        )


# =========================================================================== #
# 6. The solver's own optimality claim, carried honestly
# =========================================================================== #
def test_a_proven_optimum_cannot_be_claimed_with_a_gap_that_did_not_close() -> None:
    """ADR-0060's claim is bounded and this is where the bound is checked: an
    incumbent dressed up as a proven optimum is the failure blueprint 15 names by
    name."""
    with pytest.raises(Exception):
        _result(proven_optimal=True, gap=0.4)
    with pytest.raises(Exception):
        _result(proven_optimal=True, status=ScheduleRunStatus.FEASIBLE, gap=0.0)


def test_an_unclaimed_bound_is_stored_as_not_applicable_and_never_as_zero(store) -> None:
    """A zero bound claims the objective cannot go below zero; an absent one
    refuses to claim anything. A learner that cannot tell them apart reads every
    timeout as a proof."""
    objects = _world(store)
    timed_out = _result(
        status=ScheduleRunStatus.TIMEOUT, proven_optimal=False, bound=None, gap=None
    )
    _snapshot, recorded = _decide(store, objects, result=timed_out)
    assignment_id = recorded.assignment_object_for("R-1002")

    bound = store.fact_history(assignment_id, "solver_bound")
    assert len(bound) == 1
    assert bound[0].value is None
    assert bound[0].missing_reason is MissingnessReason.NOT_APPLICABLE

    objective = store.fact_history(assignment_id, "solver_objective_value")
    assert objective[0].value == 118.0
    assert store.fact_history(assignment_id, "solver_proven_optimal")[0].value is False


def test_a_timeout_is_recorded_as_a_reason_code_on_the_action(store) -> None:
    """`SOLVER_TIMEOUT` is already in the closed scheduling vocabulary. An
    honest solver status must reach the action record, not stop at the seam."""
    objects = _world(store)
    timed_out = _result(
        status=ScheduleRunStatus.TIMEOUT, proven_optimal=False, bound=None, gap=None
    )
    _snapshot, recorded = _decide(store, objects, result=timed_out)
    action = recorded.action_for("R-1002")
    assert action.reason_codes == (ReasonCode.SOLVER_TIMEOUT,)
    assert load_action(store, action.action_id).reason_codes == (
        ReasonCode.SOLVER_TIMEOUT,
    )

    proven = reconstruct_episode(
        store, _decide(store, objects, foreclosures=())[1].action_for("R-1002").action_id
    )
    assert proven.action.reason_codes == ()


# =========================================================================== #
# 7. The override: the vignette's last clause but one
# =========================================================================== #
def test_a_dispatcher_override_is_a_further_action_from_its_own_information_set(
    store,
) -> None:
    """"The dispatcher overrode it" is a SECOND action, taken from a SECOND
    snapshot at a later instant, linked by an `OVERRIDE_REPLACED_RECOMMENDATION`
    edge -- never an edit of the first.

    That the first decision was taken, on the information then available, is
    itself the thing worth learning from; an override that edited it would
    destroy exactly the row a learner needs.
    """
    objects = _world(store)
    _snapshot, recorded = _decide(store, objects)
    original = recorded.action_for("R-1002")

    recommendation = store.register_object(
        object_kind=ObjectKind.RECOMMENDATION, source_system="milexium"
    )
    override_object = store.register_object(
        object_kind=ObjectKind.OVERRIDE, source_system="ops"
    )
    store.test_clock.advance(minutes=2)
    store.record_event(
        event_kind=EventKind.DISPATCHER_OVERRODE,
        subject_kind=ObjectKind.ASSIGNMENT,
        subject_id=original.subject_id,
        occurred_at=original.decided_at + timedelta(minutes=1),
        actor_kind=AuthorityKind.HUMAN,
        actor_ref="dispatcher-token-7",
    )
    store.assert_relationship(
        relationship_kind=RelationshipKind.OVERRIDE_REPLACED_RECOMMENDATION,
        subject_kind=ObjectKind.OVERRIDE,
        subject_id=override_object.object_id,
        object_kind=ObjectKind.RECOMMENDATION,
        object_id=recommendation.object_id,
        asserted_by="dispatcher-token-7",
    )

    later_as_of = store.receipt_watermark().receipt_time + timedelta(seconds=1)
    # The override's scope INCLUDES the assignment the first decision created --
    # an object that did not exist at the first decision's boundary and whose
    # solver-claim facts arrived after it. That is what makes the override a
    # decision taken on more information rather than the same one twice.
    override_snapshot = store.take_snapshot(
        as_of=later_as_of,
        scope=SnapshotScope(
            subject_ids=(
                *(o.object_id for o in objects.values()),
                original.subject_id,
            )
        ),
    )
    override = store.record_action(
        action_kind=ActionKind.REASSIGN,
        subject_kind=ObjectKind.ASSIGNMENT,
        subject_id=original.subject_id,
        input_snapshot=override_snapshot,
        policy_id=original.policy_id,
        policy_version=original.policy_version,
        authority=_authority(kind=AuthorityKind.HUMAN, ref="dispatcher-token-7"),
        decided_at=later_as_of + timedelta(seconds=1),
        alternatives=(),
        alternatives_provenance=AlternativesProvenance.NONE_CONSIDERED,
        verifier=_verifier(),
    )

    assert override.was_automated is False
    assert override.input_snapshot_id != original.input_snapshot_id
    assert override.receipt.receipt_sequence > original.receipt.receipt_sequence
    # The original action is untouched and still reconstructs to ITS information
    # set, which the override's snapshot has since grown past.
    first = reconstruct_episode(store, original.action_id)
    assert first.action.input_snapshot_hash == first.information_set.content_hash
    assert len(override_snapshot.facts) > len(first.information_set.facts)


def test_overriding_a_failing_verifier_still_requires_a_justification(store) -> None:
    """The single most consequential thing anyone does in this system. An
    unexplained override is indistinguishable from the checker being ignored as
    a matter of routine -- and the episode path must not be the way round it."""
    objects = _world(store)
    with pytest.raises(Exception):
        _decide(store, objects, verifier=_verifier(VerifierVerdict.FAIL))

    _snapshot, recorded = _decide(
        store,
        objects,
        verifier=_verifier(VerifierVerdict.FAIL),
        override_justification="vehicle visibly on the forecourt; AVL stale",
        foreclosures=(),
    )
    assert recorded.action_for("R-1002").override_justification.startswith("vehicle")


# =========================================================================== #
# 8. Provenance of the claim itself
# =========================================================================== #
def test_a_snapshot_from_another_tenant_cannot_seed_an_episode(store) -> None:
    """Defence in depth against the path `record_action`'s SQL predicate does not
    cover: an evidence-pack reader or replay importer holding a snapshot object
    with no WHERE clause protecting it."""
    objects = _world(store)
    as_of = store.receipt_watermark().receipt_time + timedelta(seconds=1)
    snapshot = store.take_snapshot(as_of=as_of, scope=_scope(objects))
    foreign = snapshot.model_copy(update={"tenant_id": canonical_new_id(TenantId)})
    with pytest.raises(ValueError):
        record_decision_episode(
            store,
            snapshot=foreign,
            result=_result(),
            subjects=_subjects(objects),
            authority=_authority(),
            policy_id=canonical_new_id(PolicyId),
            policy_version=1,
            decided_at=as_of + timedelta(seconds=1),
            verifier=_verifier(),
        )


def test_the_information_set_is_re_derived_and_would_notice_if_the_past_moved(
    store,
) -> None:
    """THE RECONSTRUCTION IS A LEAK DETECTOR, NOT A CACHE READ.

    Nothing stores the snapshot's fact list -- only its boundary, scope, purpose
    and content hash -- so reconstruction re-runs the point-in-time query. That
    claim is only worth making if it can FAIL, so this deletes one of the
    admitted facts (with the append-only trigger dropped, the way the audit did)
    and asserts the reconstruction refuses rather than returning a smaller,
    plausible information set.
    """
    from themis.ontology.store import SnapshotDriftError

    objects = _world(store)
    snapshot, recorded = _decide(store, objects)
    action_id = recorded.action_for("R-1002").action_id
    assert reconstruct_episode(store, action_id).information_set.content_hash == (
        snapshot.content_hash
    )

    victim = next(f for f in snapshot.facts if f.attribute == "needs_wheelchair")
    store.database.execute_ddl("DROP TRIGGER ontology_facts_no_delete")
    store.database.execute(
        "DELETE FROM ontology_facts WHERE fact_id = ?", (str(victim.fact_id),)
    )
    store.database.commit()

    with pytest.raises(SnapshotDriftError):
        reconstruct_episode(store, action_id)


@pytest.fixture(params=["sqlite", "postgres"])
def any_engine(request):
    """One contract, two engines -- ADR-0004. An episode that only reconstructs
    on SQLite is not an episode the product can ship."""
    if request.param == "postgres":
        if not OntologyDatabase.is_postgres_reachable():
            pytest.skip("PostgreSQL 17 dev instance not reachable")
        database = OntologyDatabase.postgres()
        yield database
        database.drop_schema()
        database.close()
    else:
        database = OntologyDatabase.sqlite()
        yield database
        database.close()


def test_the_episode_flows_end_to_end_on_both_engines(any_engine) -> None:
    """The whole chain -- snapshot, decision, actions, denial, foreclosure,
    outcome, reconstruction -- on SQLite and on PostgreSQL 17 with RLS in force.

    The `alternatives_provenance` CHECK and the `receipt_time < ?` boundary are
    both TEXT comparisons, and TEXT comparison is exactly where the two engines
    diverge (collation, not byte order). Running the episode on both is what
    stops that divergence from being discovered in production.
    """
    clock = ScriptedClock()
    store = OntologyStore(any_engine, canonical_new_id(TenantId), clock=clock)
    store.test_clock = clock
    objects = _world(store)
    snapshot, recorded = _decide(store, objects)
    action = recorded.action_for("R-1002")

    store.test_clock.advance(minutes=20)
    store.record_outcome(
        action_id=action.action_id,
        metric="pickup_delay_minutes",
        value=14.0,
        observed_at=action.decided_at + timedelta(minutes=14),
        source_system="avl",
        source_record_id="avl-1",
    )

    episode = reconstruct_episode(store, action.action_id)
    assert episode.information_set.content_hash == snapshot.content_hash
    assert episode.action.alternatives_are_unknown is True
    assert [c for _, c in episode.binding_constraints()] == [
        (ReasonCode.NO_ACCESSIBLE_CAPACITY,)
    ]
    assert sorted(e.weight for e in episode.foreclosed) == [0.31, 0.62]
    assert episode.outcome("pickup_delay_minutes").value == 14.0
    assert store.verify_integrity().intact


def test_the_episode_record_carries_no_fact_values_across_the_boundary(store) -> None:
    """`to_record` is the artefact most likely to leave the tenant. It reports
    how much was known and none of what was known -- the same rule
    `provenance_manifest` keeps, for the same reason."""
    objects = _world(store)
    _snapshot, recorded = _decide(store, objects)
    episode = reconstruct_episode(store, recorded.action_for("R-1002").action_id)
    rendered = json.dumps(episode.to_record())
    assert "641.0" not in rendered  # the vehicle's expected-free value
    assert "rider-token-1" not in rendered
    assert episode.to_record()["information_set"]["facts"] == len(
        episode.information_set.facts
    )
