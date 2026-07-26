"""The DECISION EPISODE: one solver run, written down and read back whole.

WHAT ADR-0072 BUILT AND WHAT IT ADMITTED. That packet built 28 object kinds, 23
relationship kinds, a five-layer point-in-time boundary and 147 tests, and closed
by recording that none of it was "wired into the solver, forecaster, evidence
packs or API". It was a representation with no traffic through it. This module is
the traffic: one complete episode --

    this request arrived at 10:02; this wheelchair-accessible vehicle was
    expected free at 10:41; these three trips were mutually compatible; this
    assignment consumed two likely future pooling opportunities; the dispatcher
    overrode it; the resulting pickup was 14 minutes late

-- taken from a `DecisionSnapshot`, decided, written as `ActionRecord`s, followed
by an `ActionOutcome` at its own horizon, and RECONSTRUCTED from the action back
to exactly the information set that produced it.

THE ARCHITECTURAL CONSTRAINT THAT DECIDED THIS DESIGN.
`metis/` may import TYPES from `themis/` and must never import a store or a
writer. So the coupling cannot run the other way either: this module imports
NOTHING from `metis`, holds no reference to a solver, and knows nothing about
CP-SAT. What crosses the seam is PLAIN DATA -- `DecisionResult` and its parts --
and the two adapters below read a solver's output STRUCTURALLY, by attribute
name, so that:

  * `themis/ontology` has no import edge to `metis` (grep the imports; a
    conformance test asserts it by AST); and
  * `metis/decide` needs no import edge to `themis/ontology` either, because it
    never calls this module -- an integration layer does, holding both.

The two sides DO share `themis/canonical.vocab.ReasonCode` and
`ScheduleRunStatus`, which both already depended on before this packet existed.
That is the seam: a vocabulary in the layer beneath both, not a type owned by one
of them.

WHY A STRUCTURAL ADAPTER RATHER THAN A `Protocol`. A `typing.Protocol` would
document the shape and check nothing at runtime; the failure mode of a silently
mismatched field is a decision episode that records the wrong vehicle. The
adapters here read each attribute by name and raise `DecisionSeamError` naming
the missing one, so a producer that drifts from the contract fails at the seam
instead of downstream.

WHAT AN EMPTY `alternatives` MEANS, WHICH THIS MODULE IS CAREFUL ABOUT.
`metis.decide.ir.DecisionSolution` records what it CHOSE and what it DENIED. It
does not record what it REJECTED -- there is no rejected-candidate field on it.
So `decision_result_from_solution` produces
`AlternativesProvenance.NOT_RECORDED`, never `NONE_CONSIDERED`, and it will not
accept an argument that says otherwise. A caller who genuinely knows the choice
was forced constructs a `DecisionResult` directly and says so under their own
name. See `AlternativesProvenance` for why the third state had to exist before
any operator backfill rather than after it.

STATUS: Demonstrated. Every episode this module has ever carried is synthetic.
Nothing here is Validated, and the shapes it assumes about a real operator's
scheduler -- that it can name a denial's binding constraint, that it can say
whether it considered anything else -- are guesses recorded in
`forge/knowledge/workstreams/packets/MX-ONT-DECISION-EPISODE-016.yaml`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from themis.canonical.time import UtcDateTime
from themis.canonical.vocab import ScheduleRunStatus
from themis.ontology.actions import (
    ActionAlternative,
    ActionOutcome,
    ActionPrediction,
    ActionRecord,
    Authority,
    VerifierResult,
)
from themis.ontology.events import LateArrivalReason, OntologyEvent
from themis.ontology.graph import Relationship
from themis.ontology.ids import (
    ActionId,
    ObjectId,
    OutcomeId,
    PolicyId,
    SnapshotId,
    TenantId,
)
from themis.ontology.provenance import INTERNAL_DERIVATION_SOURCE
from themis.ontology.receipt import ReceiptStamp
from themis.ontology.snapshot import DecisionSnapshot
from themis.ontology.store import OntologyStore
from themis.ontology.vocab import (
    ActionKind,
    AlternativesProvenance,
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
    SensitivityClass,
    VerifierVerdict,
)

__all__ = [
    "DecisionSeamError",
    "EpisodeIntegrityError",
    "UnknownActionError",
    "ProposedAssignment",
    "ProposedDenial",
    "ConsideredOption",
    "ForeclosedOpportunity",
    "DecisionResult",
    "decision_result_from_solution",
    "foreclosures_from_attribution",
    "RecordedEpisode",
    "DecisionEpisode",
    "record_decision_episode",
    "reconstruct_episode",
    "load_action",
    "EPISODE_SEAM_VERSION",
]

EPISODE_SEAM_VERSION = "mx-ont-episode-1"
"""A LABEL, carried into the denial events this module writes and into
`DecisionEpisode.to_record`, so a later reader can tell which version of the seam
produced a row.

Deliberately NOT a hash input and never compared: an episode's identity is its
snapshot's content hash, and a second identity would be a second answer to "is
this the same decision?"."""


class DecisionSeamError(TypeError):
    """An object offered as a decision result does not have the seam's shape.

    A `TypeError` because it is a wiring fault, not bad data: whoever passed it
    has connected a producer this module cannot read, and no retry or repair
    helps. It names the missing attribute so the fix is mechanical.
    """


class EpisodeIntegrityError(RuntimeError):
    """A reconstructed episode could not be proven to be the one that was taken.

    Its own type, and NOT a `ValueError`, for the reason `SnapshotLeakageError`
    records: it must be distinguishable at the call site from a malformed
    argument. Raised when the information set re-derived from the store does not
    hash to the value the action pinned -- which means either the action or the
    history behind it has moved, and every artefact built from the episode is
    suspect.
    """


class UnknownActionError(LookupError):
    """No such action for this tenant."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- #
# The seam: plain data crossing from a decision producer to the ontology.
# --------------------------------------------------------------------------- #
class ProposedAssignment(_Frozen):
    """One request placed on one vehicle, named by the OPERATOR's own references.

    `request_ref` and `vehicle_ref` are external references (`R-1002`, `B-101`),
    not `ObjectId`s, and that is the seam working as intended: a solver reasons
    over an operator's identifiers and has no business minting or knowing
    Milexium object ids. `record_decision_episode` resolves them, and refuses an
    unresolvable one rather than registering an object to make the write succeed.
    """

    request_ref: str = Field(min_length=1)
    vehicle_ref: str = Field(min_length=1)
    pickup_time: UtcDateTime
    dropoff_time: UtcDateTime

    @model_validator(mode="after")
    def _validate(self) -> "ProposedAssignment":
        if self.dropoff_time < self.pickup_time:
            raise ValueError(
                f"assignment for {self.request_ref} drops off at "
                f"{self.dropoff_time.isoformat()}, before its pickup at "
                f"{self.pickup_time.isoformat()}"
            )
        return self


class ProposedDenial(_Frozen):
    """A request the decision left unserved, with the constraint that bound.

    `binding_constraints` is non-empty by construction. A denial whose reason is
    unrecorded is the answer the whole episode record exists to make impossible,
    and it is also the one an operator's appeals process cannot act on: "no" with
    no reason is not a decision anyone can contest.
    """

    request_ref: str = Field(min_length=1)
    binding_constraints: tuple[ReasonCode, ...] = Field(min_length=1)


class ConsideredOption(_Frozen):
    """One option a producer says it evaluated and did not take.

    Supplied only by a producer that actually records its rejections. Nothing in
    this module manufactures one: an option that no producer reported is absent
    from the episode and `alternatives_provenance` says so.
    """

    request_ref: str = Field(min_length=1)
    rank: int = Field(ge=2, description="1 is reserved for the option that WAS taken, which is the action itself and is never repeated here.")
    candidate_kind: ObjectKind
    candidate_ref: str | None = Field(
        default=None,
        description="The operator reference of the object this option would have used. None where the option was 'deny' or 'do nothing'.",
    )
    feasible: bool
    failed_constraints: tuple[ReasonCode, ...] = ()
    objective_delta: float | None = Field(
        default=None,
        description="How much worse (positive) than the taken option. None means NOT EVALUATED, never 0.0.",
    )


class ForeclosedOpportunity(_Frozen):
    """A likely future trip this assignment consumed the capacity for.

    THE CLAUSE OF THE VIGNETTE A FOREIGN KEY CANNOT CARRY, and the reason
    `RelationshipKind.ASSIGNMENT_FORECLOSED_POOLING_WITH` exists: the cardinality
    is greater than one, the assertion is probabilistic, and a later contradiction
    must not destroy the earlier claim.

    `weight` is REQUIRED and is not a probability of anything happening. Wired
    from `metis.decide.exposure.CapacityAttribution.participation`, it is the
    fraction of MINIMAL BLOCKING SETS this commitment appears in -- a descriptive
    share of the routes by which capacity could have been freed. 1.0 means every
    such route ran through this commitment; 0.5 means half did. Read
    `metis/decide/exposure.py`'s own warning before quoting one: it is a capacity
    attribution and not a causal proof.

    `basis` is carried into `Relationship.asserted_by` and must name the
    producing procedure AND whether its search was exhaustive, because a bounded
    enumeration makes every weight a lower bound and there is nowhere else on a
    relationship row to say so.
    """

    by_request_ref: str = Field(
        min_length=1,
        description="The request whose assignment consumed the capacity.",
    )
    foreclosed_request_ref: str = Field(
        min_length=1,
        description="The trip that became infeasible as a result.",
    )
    weight: float = Field(ge=0.0, le=1.0)
    basis: str = Field(
        min_length=1,
        description="Producing procedure and version, plus whether its enumeration was exhaustive, e.g. 'metis.decide.exposure/0.4.0/exhaustive'.",
    )

    @model_validator(mode="after")
    def _validate(self) -> "ForeclosedOpportunity":
        if self.by_request_ref == self.foreclosed_request_ref:
            raise ValueError(
                f"request {self.by_request_ref} cannot foreclose its own trip"
            )
        return self


class DecisionResult(_Frozen):
    """What a decision producer decided, as plain data.

    Mirrors `metis.decide.ir.DecisionSolution` field for field where the two
    overlap, and DELIBERATELY does not import it. Two consequences worth stating:
    a producer that is not the CP-SAT portfolio (a greedy fallback, a replayed
    historical schedule, a dispatcher's manual plan) can populate this without
    pretending to be a solver; and the ontology's test suite constructs one
    without `ortools` installed.
    """

    status: ScheduleRunStatus
    assignments: tuple[ProposedAssignment, ...] = ()
    denials: tuple[ProposedDenial, ...] = ()
    considered: tuple[ConsideredOption, ...] = ()
    alternatives_provenance: AlternativesProvenance = Field(
        description=(
            "What this result says about what it REJECTED, for the result as a "
            "whole. ENUMERATED asserts the enumeration is complete for every "
            "request here, which is what lets `provenance_for` read a request "
            "with no listed options as a forced placement rather than as an "
            "unknown. A producer that enumerates only some of its decisions must "
            "split them into two results."
        )
    )
    objective_value: float | None = None
    bound: float | None = Field(
        default=None,
        description="The producer's own lower bound on the objective. None means it could not claim one -- never 0.0.",
    )
    gap: float | None = None
    proven_optimal: bool = Field(
        description="The producer's optimality CLAIM, carried rather than re-derived. Checked for internal consistency below; nothing here can establish it independently."
    )
    seed: int
    solver_name: str = Field(min_length=1)
    solver_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate(self) -> "DecisionResult":
        if self.proven_optimal:
            if self.status is not ScheduleRunStatus.OPTIMAL:
                raise ValueError(
                    f"proven_optimal is claimed with status {self.status.value}. An "
                    "incumbent dressed up as a proven optimum is the failure this "
                    "field exists to make loud"
                )
            if self.gap != 0.0:
                raise ValueError(
                    f"proven_optimal is claimed with gap {self.gap!r}. Optimality "
                    "proven means the gap CLOSED; a non-zero (or absent) gap is the "
                    "evidence that it did not"
                )
        enumerated = self.alternatives_provenance is AlternativesProvenance.ENUMERATED
        if enumerated and not self.considered:
            raise ValueError(
                "alternatives_provenance is ENUMERATED but no options were "
                "considered. 'We enumerated them and there were none' is not a claim"
            )
        if self.considered and not enumerated:
            raise ValueError(
                f"{len(self.considered)} considered option(s) were supplied but "
                f"alternatives_provenance is {self.alternatives_provenance.value}: a "
                "list of what was considered contradicts both 'nothing was' and 'we "
                "do not know'"
            )
        served = {a.request_ref for a in self.assignments}
        denied = {d.request_ref for d in self.denials}
        both = served & denied
        if both:
            raise ValueError(
                f"request(s) {sorted(both)} are both assigned and denied by the same "
                "result"
            )
        if len(served) != len(self.assignments):
            raise ValueError(
                "the same request is assigned twice; this seam carries one placement "
                "per request"
            )
        known = served | denied
        stray = {o.request_ref for o in self.considered} - known
        if stray:
            raise ValueError(
                f"considered option(s) name request(s) {sorted(stray)} that the "
                "result neither served nor denied"
            )
        return self

    def provenance_for(self, request_ref: str) -> AlternativesProvenance:
        """What an empty `alternatives_for(request_ref)` means for ONE action.

        `alternatives_provenance` is a claim about the RESULT; an `ActionRecord`
        needs the claim about its own row, and for one of the three states they
        are not the same value.

          NOT_RECORDED  -> NOT_RECORDED for every action. The producer reports no
                           rejections at all, so it reports none here either.
          NONE_CONSIDERED -> NONE_CONSIDERED for every action.
          ENUMERATED    -> ENUMERATED where options were listed, and
                           NONE_CONSIDERED where none were.

        THE LAST LINE IS A DEDUCTION AND IT RESTS ON WHAT `ENUMERATED` MEANS,
        which is stated on the field and enforced by this method being the only
        way an episode reads it: `ENUMERATED` asserts the enumeration is complete
        FOR THE WHOLE RESULT. A producer that enumerates would have listed
        R-1003's options if it had any, so their absence is evidence and the
        placement was forced. Reading it as NOT_RECORDED instead would throw away
        a real observation on every forced placement in an enumerating result --
        which, in a fleet where most trips have exactly one feasible accessible
        vehicle, is most of them.

        A producer that enumerates only SOME of its decisions must therefore send
        two results, or send NOT_RECORDED for the batch. That is a real
        constraint on the seam and it is the honest one: the alternative is a
        per-request provenance the producer would have to populate correctly, and
        a field nobody populates correctly is worse than a claim nobody may make
        loosely.
        """
        if self.alternatives_provenance is not AlternativesProvenance.ENUMERATED:
            return self.alternatives_provenance
        return (
            AlternativesProvenance.ENUMERATED
            if any(o.request_ref == request_ref for o in self.considered)
            else AlternativesProvenance.NONE_CONSIDERED
        )

    def alternatives_for(self, request_ref: str) -> tuple[ActionAlternative, ...]:
        """The ontology-shaped alternatives for one request's action.

        Returns `()` when nothing was reported for this request, which is the
        ambiguous case `provenance_for` disambiguates. `record_decision_episode`
        always passes the two together, so an action can never carry one without
        the other.
        """
        return tuple(
            ActionAlternative(
                rank=o.rank,
                candidate_kind=o.candidate_kind,
                candidate_id=None,
                feasible=o.feasible,
                failed_constraints=o.failed_constraints,
                objective_delta=o.objective_delta,
            )
            for o in sorted(
                (o for o in self.considered if o.request_ref == request_ref),
                key=lambda o: o.rank,
            )
        )


# --------------------------------------------------------------------------- #
# Structural adapters. No `metis` import -- see the module docstring.
# --------------------------------------------------------------------------- #
def _require(obj: Any, name: str, what: str) -> Any:
    try:
        return getattr(obj, name)
    except AttributeError as exc:
        raise DecisionSeamError(
            f"{what} of type {type(obj).__name__!r} has no {name!r}. The decision "
            "seam reads a producer's output by attribute name and does not import "
            "it; a producer that has drifted from the contract must be adapted at "
            "the call site rather than special-cased here"
        ) from exc


def decision_result_from_solution(
    solution: Any,
    *,
    considered: Sequence[ConsideredOption] = (),
) -> DecisionResult:
    """Read a `metis.decide.ir.DecisionSolution`-shaped object into the seam.

    STRUCTURAL, BY ATTRIBUTE NAME. This function is the only place the ontology
    knows anything about a solver's output shape, and it knows it as nine
    attribute names rather than as an import.

    THE ALTERNATIVES RULE, ENFORCED HERE AND NOT LEFT TO A CALLER. A
    `DecisionSolution` carries assignments and denials and nothing about what it
    rejected. So this function produces `NOT_RECORDED` whenever `considered` is
    empty and there is NO PARAMETER through which a caller could turn that into
    `NONE_CONSIDERED`. The distinction matters most exactly when it is least
    convenient -- during a historical backfill, where "nothing was considered"
    would be inferred over thousands of rows from a field the operator's
    scheduler never exported.
    """
    status = _require(solution, "status", "decision solution")
    raw_assignments = _require(solution, "assignments", "decision solution")
    raw_denials = _require(solution, "unserved", "decision solution")
    assignments = tuple(
        ProposedAssignment(
            request_ref=str(_require(a, "request_id", "assignment")),
            vehicle_ref=str(_require(a, "vehicle_id", "assignment")),
            pickup_time=_require(a, "pickup_time", "assignment"),
            dropoff_time=_require(a, "dropoff_time", "assignment"),
        )
        for a in raw_assignments
    )
    denials = tuple(
        ProposedDenial(
            request_ref=str(_require(d, "request_id", "denial")),
            binding_constraints=tuple(_require(d, "reason_codes", "denial")),
        )
        for d in raw_denials
    )
    return DecisionResult(
        status=ScheduleRunStatus(status),
        assignments=assignments,
        denials=denials,
        considered=tuple(considered),
        alternatives_provenance=(
            AlternativesProvenance.ENUMERATED
            if considered
            else AlternativesProvenance.NOT_RECORDED
        ),
        objective_value=_require(solution, "objective_value", "decision solution"),
        bound=_require(solution, "bound", "decision solution"),
        gap=_require(solution, "gap", "decision solution"),
        proven_optimal=bool(_require(solution, "proven_optimal", "decision solution")),
        seed=int(_require(solution, "seed", "decision solution")),
        solver_name=str(_require(solution, "solver_name", "decision solution")),
        solver_version=str(_require(solution, "solver_version", "decision solution")),
    )


def foreclosures_from_attribution(
    attribution: Any, *, producer: str = "metis.decide.exposure"
) -> tuple[ForeclosedOpportunity, ...]:
    """Read a `metis.decide.exposure.CapacityAttribution`-shaped object.

    The vignette's "consumed two likely future pooling opportunities" is already
    computed by ADR-0065's minimal-blocking-set search; this reads its answer
    rather than writing a second one. Direction: the attribution names, for a
    trip that was DENIED, which earlier commitments were sitting in the capacity
    it needed -- so each row becomes an edge from the earlier commitment's
    assignment TO the denied request, which is exactly the direction
    `ASSIGNMENT_FORECLOSED_POOLING_WITH` runs.

    Returns `()` -- not an error -- when `servable_in_isolation` is False. That
    denial is a structural gap in the service (no accessible vehicle on shift,
    or a window nothing could reach), and attributing it to another rider's trip
    would be false. `metis.decide.exposure` refuses to attribute it and so does
    this.

    `enumeration_complete` is carried into the `basis` string because a bounded
    search makes every weight a LOWER BOUND, and a relationship row has nowhere
    else to record that.
    """
    if not _require(attribution, "servable_in_isolation", "capacity attribution"):
        return ()
    complete = bool(_require(attribution, "enumeration_complete", "capacity attribution"))
    denied = str(_require(attribution, "request_id", "capacity attribution"))
    basis = f"{producer}/{'exhaustive' if complete else 'bounded'}"
    return tuple(
        ForeclosedOpportunity(
            by_request_ref=str(commitment),
            foreclosed_request_ref=denied,
            weight=float(share),
            basis=basis,
        )
        for commitment, share in _require(
            attribution, "participation", "capacity attribution"
        )
        if str(commitment) != denied
    )


# --------------------------------------------------------------------------- #
# Writing an episode.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RecordedEpisode:
    """What one `record_decision_episode` call wrote.

    Returned rather than discarded so a caller can record outcomes against the
    actions without querying for them, and so a test can assert on the exact rows
    rather than on a count.
    """

    snapshot_id: SnapshotId
    actions: tuple[ActionRecord, ...]
    assignment_objects: tuple[tuple[str, ObjectId], ...]
    denial_events: tuple[OntologyEvent, ...]
    foreclosure_edges: tuple[Relationship, ...]

    def action_for(self, request_ref: str) -> ActionRecord:
        for ref, object_id in self.assignment_objects:
            if ref == request_ref:
                for action in self.actions:
                    if str(action.subject_id) == str(object_id):
                        return action
        raise KeyError(f"no assignment action for request {request_ref!r}")

    def assignment_object_for(self, request_ref: str) -> ObjectId:
        for ref, object_id in self.assignment_objects:
            if ref == request_ref:
                return object_id
        raise KeyError(f"no assignment object for request {request_ref!r}")


def record_decision_episode(
    store: OntologyStore,
    *,
    snapshot: DecisionSnapshot,
    result: DecisionResult,
    subjects: Mapping[str, ObjectId],
    authority: Authority,
    policy_id: PolicyId,
    policy_version: int,
    decided_at: datetime,
    verifier: VerifierResult,
    foreclosures: Sequence[ForeclosedOpportunity] = (),
    predictions: Mapping[str, ActionPrediction] | None = None,
    override_justification: str | None = None,
    late_arrival_reason: LateArrivalReason | None = None,
) -> RecordedEpisode:
    """Write one decision, taken from `snapshot`, as typed actions.

    THE DECISION IS MADE FROM THE SNAPSHOT ONLY, and this function cannot check
    that -- it did not make the decision. What it CAN do, and does, is make the
    claim falsifiable: every action it writes cites `snapshot.snapshot_id` AND
    `snapshot.content_hash`, `OntologyStore.record_action` refuses an action
    whose snapshot the store never took or whose hash has moved, and
    `reconstruct_episode` re-derives the information set and re-checks the hash.
    A decision that used a fact outside the snapshot leaves a record that says
    what it used, and the gap becomes an auditable question rather than an
    invisible one.

    WHAT IT WRITES, IN THIS ORDER, AND WHY THE ORDER IS THE EPISODE'S ORDER:

      1. one `ASSIGNMENT` object per placement -- the thing the decision brought
         into existence, which by construction did not exist at `as_of`;
      2. `ASSIGNMENT_SERVES_REQUEST` and `VEHICLE_PERFORMS_ASSIGNMENT` edges;
      3. one `ASSIGN` `ActionRecord` per placement, carrying the alternatives
         AND what their emptiness means, the verifier verdict, the policy
         version and the authority;
      4. the solver's own optimality claim as DERIVED facts on each assignment,
         so a bound that was never claimed is stored as
         `MissingnessReason.NOT_APPLICABLE` rather than as a zero;
      5. one `TRIP_DENIED` event per denial, carrying the binding constraints;
      6. one `ASSIGNMENT_FORECLOSED_POOLING_WITH` edge per foreclosed
         opportunity, carrying its weight.

    Every one of those receipts is LATER than the snapshot's boundary, which is
    the mechanism -- not a rule this function enforces -- by which the decision's
    own consequences are invisible to the information set that produced it.

    WHY DENIALS ARE EVENTS AND NOT ACTIONS. `ActionKind` has eleven members and
    none of them is "deny". That is a real gap in ADR-0072's vocabulary and this
    module does not paper over it by borrowing a near-miss kind; `TRIP_DENIED` is
    the vocabulary's own home for a denial, it carries `reason_codes`, and its
    payload cites the snapshot so the episode reads back complete. Whether a
    denial should be a permissioned ACTION -- it is a decision with a subject, an
    authority and an appeal -- is recorded as an open question in the packet.
    """
    predictions = dict(predictions or {})
    if str(snapshot.tenant_id) != str(store.tenant_id):
        raise ValueError(
            f"snapshot belongs to tenant {snapshot.tenant_id} but the store writes "
            f"for {store.tenant_id}"
        )

    def resolve(ref: str, role: str) -> ObjectId:
        try:
            return subjects[ref]
        except KeyError:
            raise LookupError(
                f"the decision names {role} {ref!r}, which is not in `subjects`. "
                "This function will not register an object to make a write succeed: "
                "an identity minted to satisfy a foreign key is how a decision "
                "episode acquires a subject nobody recognises"
            ) from None

    unknown_predictions = set(predictions) - {a.request_ref for a in result.assignments}
    if unknown_predictions:
        raise LookupError(
            f"prediction(s) supplied for request(s) {sorted(unknown_predictions)} "
            "that this result did not assign"
        )

    actions: list[ActionRecord] = []
    assignment_objects: list[tuple[str, ObjectId]] = []
    for placement in result.assignments:
        request_id = resolve(placement.request_ref, "request")
        vehicle_id = resolve(placement.vehicle_ref, "vehicle")
        assignment = store.register_object(
            object_kind=ObjectKind.ASSIGNMENT,
            external_ref=f"{placement.vehicle_ref}:{placement.request_ref}",
            source_system=result.solver_name,
        )
        assignment_objects.append((placement.request_ref, assignment.object_id))
        store.assert_relationship(
            relationship_kind=RelationshipKind.ASSIGNMENT_SERVES_REQUEST,
            subject_kind=ObjectKind.ASSIGNMENT,
            subject_id=assignment.object_id,
            object_kind=ObjectKind.REQUEST,
            object_id=request_id,
            asserted_by=result.solver_name,
            valid_from=placement.pickup_time,
            valid_to=placement.dropoff_time,
        )
        store.assert_relationship(
            relationship_kind=RelationshipKind.VEHICLE_PERFORMS_ASSIGNMENT,
            subject_kind=ObjectKind.VEHICLE,
            subject_id=vehicle_id,
            object_kind=ObjectKind.ASSIGNMENT,
            object_id=assignment.object_id,
            asserted_by=result.solver_name,
            valid_from=placement.pickup_time,
            valid_to=placement.dropoff_time,
        )
        actions.append(
            store.record_action(
                action_kind=ActionKind.ASSIGN,
                subject_kind=ObjectKind.ASSIGNMENT,
                subject_id=assignment.object_id,
                input_snapshot=snapshot,
                policy_id=policy_id,
                policy_version=policy_version,
                authority=authority,
                decided_at=decided_at,
                alternatives=result.alternatives_for(placement.request_ref),
                alternatives_provenance=result.provenance_for(placement.request_ref),
                verifier=verifier,
                prediction=predictions.get(placement.request_ref),
                override_justification=override_justification,
                reason_codes=(
                    (ReasonCode.SOLVER_TIMEOUT,)
                    if result.status is ScheduleRunStatus.TIMEOUT
                    else ()
                ),
            )
        )
        _record_optimality_claim(store, assignment.object_id, result)

    denial_events = tuple(
        store.record_event(
            event_kind=EventKind.TRIP_DENIED,
            subject_kind=ObjectKind.REQUEST,
            subject_id=resolve(denial.request_ref, "denied request"),
            occurred_at=decided_at,
            actor_kind=authority.authority_kind,
            actor_ref=authority.actor_ref,
            reason_codes=denial.binding_constraints,
            late_arrival_reason=late_arrival_reason,
            payload={
                "decision_snapshot_id": str(snapshot.snapshot_id),
                "decision_snapshot_hash": snapshot.content_hash,
                "solver": f"{result.solver_name}/{result.solver_version}",
                "seam": EPISODE_SEAM_VERSION,
            },
        )
        for denial in result.denials
    )

    by_ref = dict(assignment_objects)
    edges: list[Relationship] = []
    for opportunity in foreclosures:
        if opportunity.by_request_ref not in by_ref:
            raise LookupError(
                f"foreclosure attributed to request {opportunity.by_request_ref!r}, "
                "which this decision did not assign. An assignment that was never "
                "made cannot have consumed anything"
            )
        edges.append(
            store.assert_relationship(
                relationship_kind=RelationshipKind.ASSIGNMENT_FORECLOSED_POOLING_WITH,
                subject_kind=ObjectKind.ASSIGNMENT,
                subject_id=by_ref[opportunity.by_request_ref],
                object_kind=ObjectKind.REQUEST,
                object_id=resolve(
                    opportunity.foreclosed_request_ref, "foreclosed request"
                ),
                asserted_by=opportunity.basis,
                weight=opportunity.weight,
            )
        )

    return RecordedEpisode(
        snapshot_id=snapshot.snapshot_id,
        actions=tuple(actions),
        assignment_objects=tuple(assignment_objects),
        denial_events=denial_events,
        foreclosure_edges=tuple(edges),
    )


def _record_optimality_claim(
    store: OntologyStore, assignment_id: ObjectId, result: DecisionResult
) -> None:
    """Write the producer's optimality claim as DERIVED facts on the assignment.

    ADR-0060's portfolio proves optimality against a bound IT COMPUTED, and that
    bound is the difference between "the best plan we found" and "no better plan
    exists on this grid". Storing it as three facts rather than three columns is
    the ontology's own rule -- a value with no receipt time has nowhere to live
    here -- and it means a later reader can see WHEN the claim was recorded
    relative to the decision.

    An absent bound is stored as `NOT_APPLICABLE`, never as 0.0. A zero bound is
    a claim that the objective cannot go below zero; an absent one is a refusal
    to claim anything, and a learner that cannot tell them apart will read every
    timeout as a proof.
    """
    values = {
        "solver_objective_value": result.objective_value,
        "solver_bound": result.bound,
        "solver_gap": result.gap,
    }
    for attribute, value in values.items():
        store.record_fact(
            subject_kind=ObjectKind.ASSIGNMENT,
            subject_id=assignment_id,
            attribute=attribute,
            fact_class=FactClass.DERIVATION,
            quality=QualityState.TRUSTED,
            sensitivity=SensitivityClass.OPERATIONAL,
            legal_basis=LegalBasis.LEGITIMATE_INTEREST,
            source_system=INTERNAL_DERIVATION_SOURCE,
            value=None if value is None else float(value),
            missing_reason=None if value is not None else MissingnessReason.NOT_APPLICABLE,
        )
    store.record_fact(
        subject_kind=ObjectKind.ASSIGNMENT,
        subject_id=assignment_id,
        attribute="solver_proven_optimal",
        fact_class=FactClass.DERIVATION,
        quality=QualityState.TRUSTED,
        sensitivity=SensitivityClass.OPERATIONAL,
        legal_basis=LegalBasis.LEGITIMATE_INTEREST,
        source_system=INTERNAL_DERIVATION_SOURCE,
        value=result.proven_optimal,
    )


# --------------------------------------------------------------------------- #
# Reading an episode back.
#
# WHY THESE ARE FREE FUNCTIONS AND NOT `OntologyStore` METHODS. The store's
# public surface is PINNED by `test_the_store_exposes_no_generic_writer`, whose
# message reads "every addition that WRITES must be a typed action, and every
# addition that READS must be checked for the point-in-time boundary". Adding
# methods would either break that pin or quietly widen it. So the reader lives
# beside the store instead, and honours both halves of the rule rather than
# routing around it:
#
#   * it WRITES nothing -- there is no INSERT, UPDATE or DELETE in this section;
#   * the boundary-carrying read goes through `OntologyStore.load_snapshot`,
#     which re-derives the information set under `receipt_time < as_of` and
#     raises `SnapshotDriftError` if the past has moved.
#
# The action, event, relationship and outcome reads here are DELIBERATELY
# unfiltered, exactly as `fact_history` is, and for the same reason: an episode
# is an audit view. It MUST see the outcome that arrived after the decision --
# that is the whole point of an outcome -- and the reason that cannot leak is
# that the outcome is a separate row reached through the action, never through
# the snapshot.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DecisionEpisode:
    """One decision, the information set it was taken from, and what followed.

    `information_set` is RE-DERIVED from the store, not stored and returned. If
    anything had been written before its boundary since, `load_snapshot` would
    have raised rather than handed back a plausible answer -- so holding this
    object is evidence, not merely a report.
    """

    action: ActionRecord
    information_set: DecisionSnapshot
    denials: tuple[OntologyEvent, ...]
    foreclosed: tuple[Relationship, ...]
    outcomes: tuple[ActionOutcome, ...]

    @property
    def alternatives_are_unknown(self) -> bool:
        """Whether this episode says nothing about what else was on the table.

        The predicate to filter a training set on. See `AlternativesProvenance`.
        """
        return self.action.alternatives_are_unknown

    @property
    def decision_lag_seconds(self) -> float:
        """How stale the information set was when the decision was taken."""
        return self.action.decision_lag_seconds

    def binding_constraints(self) -> tuple[tuple[str, tuple[ReasonCode, ...]], ...]:
        """(request object id, reason codes) for every request this decision denied."""
        return tuple(
            (str(event.subject_id), event.reason_codes) for event in self.denials
        )

    def outcome(self, metric: str) -> ActionOutcome | None:
        """The outcome for one metric, or None. Several outcomes at several
        horizons is the normal case; asking for one by name is the normal read."""
        for candidate in self.outcomes:
            if candidate.metric == metric:
                return candidate
        return None

    def to_record(self) -> dict:
        """The evidence-shaped projection: what was decided, from what, and what
        followed. Carries no fact VALUES -- see
        `DecisionSnapshot.provenance_manifest`, which this defers to for the same
        reason: an episode record is the artefact most likely to leave the tenant
        boundary."""
        return {
            "action_id": str(self.action.action_id),
            "action_kind": self.action.action_kind.value,
            "subject_id": str(self.action.subject_id),
            "decided_at": self.action.decided_at.isoformat(),
            "was_automated": self.action.was_automated,
            "authority_kind": self.action.authority.authority_kind.value,
            "policy": f"{self.action.policy_id}/v{self.action.policy_version}",
            "verifier_verdict": self.action.verifier.verdict.value,
            "information_set": {
                "snapshot_id": str(self.information_set.snapshot_id),
                "as_of": self.information_set.as_of.isoformat(),
                "content_hash": self.information_set.content_hash,
                "facts": len(self.information_set.facts),
                "events": len(self.information_set.events),
                "relationships": len(self.information_set.relationships),
                "decision_lag_seconds": self.decision_lag_seconds,
            },
            "alternatives": {
                "provenance": self.action.alternatives_provenance.value,
                "count": len(self.action.alternatives),
                "unknown": self.alternatives_are_unknown,
            },
            "denials": [
                {"request_id": rid, "binding_constraints": [c.value for c in codes]}
                for rid, codes in self.binding_constraints()
            ],
            "foreclosed_pooling": [
                {
                    "request_id": str(edge.object_id),
                    "weight": edge.weight,
                    "asserted_by": edge.asserted_by,
                }
                for edge in self.foreclosed
            ],
            "outcomes": [
                {
                    "metric": o.metric,
                    "value": o.value,
                    "horizon_seconds": o.horizon_seconds,
                    "observed_at": o.observed_at.isoformat(),
                }
                for o in self.outcomes
            ],
            "seam": EPISODE_SEAM_VERSION,
        }


def load_action(store: OntologyStore, action_id: ActionId) -> ActionRecord:
    """Read one `ActionRecord` back from the durable record.

    The row, not a cache: an episode reconstructed in a fresh process from a
    fresh connection is the only reconstruction worth anything, and this is the
    step that makes it possible.
    """
    store.database.use_tenant(store.tenant_id)
    rows = store.database.query(
        "SELECT action_id, action_kind, subject_kind, subject_id, input_snapshot_id, "
        "input_snapshot_hash, input_snapshot_as_of, policy_id, policy_version, "
        "alternatives_json, alternatives_provenance, prediction_json, verifier_verdict, "
        "verifier_name, verifier_version, violated_rules_json, override_justification, "
        "authority_kind, authority_ref, authority_role, authority_permissions_json, "
        "authority_on_behalf_of, decided_at, reason_codes, receipt_time, "
        "receipt_sequence, prev_hash, hash FROM ontology_actions "
        "WHERE tenant_id = ? AND action_id = ?",
        (str(store.tenant_id), str(action_id)),
    )
    if not rows:
        raise UnknownActionError(
            f"no action {action_id} recorded for tenant {store.tenant_id}"
        )
    return _action_from_row(rows[0], store.tenant_id)


def _action_from_row(row: Sequence[Any], tenant_id: TenantId) -> ActionRecord:
    (
        action_id,
        action_kind,
        subject_kind,
        subject_id,
        input_snapshot_id,
        input_snapshot_hash,
        input_snapshot_as_of,
        policy_id,
        policy_version,
        alternatives_json,
        alternatives_provenance,
        prediction_json,
        verifier_verdict,
        verifier_name,
        verifier_version,
        violated_rules_json,
        override_justification,
        authority_kind,
        authority_ref,
        authority_role,
        authority_permissions_json,
        authority_on_behalf_of,
        decided_at,
        reason_codes,
        receipt_time,
        receipt_sequence,
        prev_hash,
        row_hash,
    ) = row
    prediction = None
    if prediction_json is not None:
        body = json.loads(prediction_json)
        prediction = ActionPrediction(
            metric=body["metric"],
            point_estimate=body["point"],
            interval_low=body["low"],
            interval_high=body["high"],
            model_version_id=body["model"],
        )
    return ActionRecord(
        action_id=ActionId(action_id),
        tenant_id=tenant_id,
        action_kind=ActionKind(action_kind),
        subject_kind=ObjectKind(subject_kind),
        subject_id=ObjectId(subject_id),
        input_snapshot_id=SnapshotId(input_snapshot_id),
        input_snapshot_hash=input_snapshot_hash,
        input_snapshot_as_of=datetime.fromisoformat(input_snapshot_as_of),
        policy_id=PolicyId(policy_id),
        policy_version=int(policy_version),
        alternatives=tuple(
            ActionAlternative(
                rank=a["rank"],
                candidate_kind=ObjectKind(a["kind"]),
                candidate_id=None if a["id"] is None else ObjectId(a["id"]),
                feasible=a["feasible"],
                failed_constraints=tuple(ReasonCode(c) for c in a["failed"]),
                objective_delta=a["delta"],
            )
            for a in json.loads(alternatives_json)
        ),
        alternatives_provenance=AlternativesProvenance(alternatives_provenance),
        prediction=prediction,
        verifier=VerifierResult(
            verdict=VerifierVerdict(verifier_verdict),
            verifier_name=verifier_name,
            verifier_version=verifier_version,
            violated_rules=tuple(json.loads(violated_rules_json)),
        ),
        override_justification=override_justification,
        authority=Authority(
            authority_kind=AuthorityKind(authority_kind),
            actor_ref=authority_ref,
            role=authority_role,
            permissions=frozenset(
                Permission(p) for p in json.loads(authority_permissions_json)
            ),
            on_behalf_of=authority_on_behalf_of,
        ),
        decided_at=datetime.fromisoformat(decided_at),
        receipt=ReceiptStamp(
            receipt_time=datetime.fromisoformat(receipt_time),
            receipt_sequence=int(receipt_sequence),
        ),
        reason_codes=tuple(ReasonCode(c) for c in json.loads(reason_codes)),
        prev_hash=prev_hash,
        hash=row_hash,
    )


def reconstruct_episode(
    store: OntologyStore, action_id: ActionId
) -> DecisionEpisode:
    """Given an action, recover exactly what was known when it was made.

    THE FOUR STEPS, AND THE ONE THAT MAKES IT PROOF RATHER THAN RETRIEVAL:

      1. Read the action row. It carries the snapshot's id, its content hash and
         its `as_of` -- all three, because the id alone would let a re-derived
         snapshot differ from the one cited, and nothing would notice.
      2. `load_snapshot` RE-DERIVES the information set from the store under
         `receipt_time < as_of`. It does not read a stored fact list, because
         there is none: storing one would make this comparison a tautology.
      3. Compare the re-derived content hash with the one the ACTION pinned. Step
         2 already compared it with the one the SNAPSHOT row pinned; this compares
         it with the one the DECISION pinned, which is a different claim -- an
         action can cite a snapshot that is itself intact but was not the one it
         used, and only this comparison sees that.
      4. Gather what followed: the denials of the same decision, the pooling
         opportunities the assignment foreclosed, and the outcomes at their own
         horizons.

    Raises `EpisodeIntegrityError` at step 3 and lets `SnapshotDriftError` out of
    step 2 -- two different failures with two different remedies, so neither is
    reported as the other.
    """
    action = load_action(store, action_id)
    information_set = store.load_snapshot(action.input_snapshot_id)
    if information_set.content_hash != action.input_snapshot_hash:
        raise EpisodeIntegrityError(
            f"action {action_id} pinned information set "
            f"{action.input_snapshot_hash} but snapshot "
            f"{action.input_snapshot_id} re-derives to "
            f"{information_set.content_hash}. The decision cannot be shown to have "
            "been taken on the facts it names, so nothing learned from it is "
            "defensible"
        )
    return DecisionEpisode(
        action=action,
        information_set=information_set,
        denials=_denials_of(store, action.input_snapshot_id),
        foreclosed=_foreclosed_by(store, action.subject_id),
        outcomes=_outcomes_of(store, action.action_id),
    )


def _denials_of(
    store: OntologyStore, snapshot_id: SnapshotId
) -> tuple[OntologyEvent, ...]:
    """Every `TRIP_DENIED` event citing this decision's information set.

    THE SNAPSHOT ID IS THE EPISODE KEY. One solver run reads one information set
    and every action and denial it produces cites it, so "the denials of this
    decision" is an exact query and not a time-window heuristic -- which would
    have swept in an unrelated denial that happened to land in the same second.
    """
    store.database.use_tenant(store.tenant_id)
    rows = store.database.query(
        "SELECT event_id, event_kind, subject_kind, subject_id, occurred_at, "
        "receipt_time, receipt_sequence, late_arrival_reason, actor_kind, actor_ref, "
        "reason_codes, payload, prev_hash, hash FROM ontology_events "
        "WHERE tenant_id = ? AND event_kind = ? ORDER BY receipt_sequence",
        (str(store.tenant_id), EventKind.TRIP_DENIED.value),
    )
    wanted = str(snapshot_id)
    out: list[OntologyEvent] = []
    for row in rows:
        payload = json.loads(row[11])
        if payload.get("decision_snapshot_id") != wanted:
            continue
        out.append(
            OntologyEvent(
                event_id=row[0],
                tenant_id=store.tenant_id,
                event_kind=EventKind(row[1]),
                subject_kind=ObjectKind(row[2]),
                subject_id=ObjectId(row[3]),
                occurred_at=datetime.fromisoformat(row[4]),
                receipt=ReceiptStamp(
                    receipt_time=datetime.fromisoformat(row[5]),
                    receipt_sequence=int(row[6]),
                ),
                late_arrival_reason=(
                    None if row[7] is None else LateArrivalReason(row[7])
                ),
                actor_kind=AuthorityKind(row[8]),
                actor_ref=row[9],
                reason_codes=tuple(ReasonCode(c) for c in json.loads(row[10])),
                payload=payload,
                prev_hash=row[12],
                hash=row[13],
            )
        )
    return tuple(out)


def _foreclosed_by(
    store: OntologyStore, assignment_id: ObjectId
) -> tuple[Relationship, ...]:
    """The pooling opportunities this assignment consumed, with their weights.

    Retracted edges are excluded the same way `_select_content` excludes them --
    a retraction is a new row naming the old one, and the old one is retained.
    """
    store.database.use_tenant(store.tenant_id)
    rows = store.database.query(
        "SELECT relationship_id, relationship_kind, subject_kind, subject_id, "
        "object_kind, object_id, weight, valid_from, valid_to, asserted_by, "
        "retracts_relationship_id, receipt_time, receipt_sequence "
        "FROM ontology_relationships WHERE tenant_id = ? AND relationship_kind = ? "
        "AND subject_id = ? ORDER BY receipt_sequence",
        (
            str(store.tenant_id),
            RelationshipKind.ASSIGNMENT_FORECLOSED_POOLING_WITH.value,
            str(assignment_id),
        ),
    )
    retracted = {row[10] for row in rows if row[10] is not None}
    return tuple(
        Relationship(
            relationship_id=row[0],
            tenant_id=store.tenant_id,
            relationship_kind=RelationshipKind(row[1]),
            subject_kind=ObjectKind(row[2]),
            subject_id=ObjectId(row[3]),
            object_kind=ObjectKind(row[4]),
            object_id=ObjectId(row[5]),
            weight=row[6],
            valid_from=None if row[7] is None else datetime.fromisoformat(row[7]),
            valid_to=None if row[8] is None else datetime.fromisoformat(row[8]),
            asserted_by=row[9],
            retracts_relationship_id=row[10],
            receipt=ReceiptStamp(
                receipt_time=datetime.fromisoformat(row[11]),
                receipt_sequence=int(row[12]),
            ),
        )
        for row in rows
        if row[0] not in retracted and row[10] is None
    )


def _outcomes_of(
    store: OntologyStore, action_id: ActionId
) -> tuple[ActionOutcome, ...]:
    """Every outcome recorded against this action, in receipt order.

    DELIBERATELY UNBOUNDED IN TIME, and this is the asymmetry that makes an
    episode an episode: the information set is cut at `as_of`, and everything
    that followed is not. The two cannot be confused because they arrive by
    different routes -- the snapshot through `load_snapshot`, which applies the
    boundary; the outcomes through the action, which is not a read path a
    snapshot holder has.
    """
    store.database.use_tenant(store.tenant_id)
    rows = store.database.query(
        "SELECT outcome_id, action_id, metric, value, observed_at, horizon_seconds, "
        "source_system, source_record_id, receipt_time, receipt_sequence "
        "FROM ontology_action_outcomes WHERE tenant_id = ? AND action_id = ? "
        "ORDER BY receipt_sequence",
        (str(store.tenant_id), str(action_id)),
    )
    return tuple(
        ActionOutcome(
            outcome_id=OutcomeId(row[0]),
            tenant_id=store.tenant_id,
            action_id=ActionId(row[1]),
            metric=row[2],
            value=float(row[3]),
            observed_at=datetime.fromisoformat(row[4]),
            receipt=ReceiptStamp(
                receipt_time=datetime.fromisoformat(row[8]),
                receipt_sequence=int(row[9]),
            ),
            horizon_seconds=float(row[5]),
            source_system=row[6],
            source_record_id=row[7],
        )
        for row in rows
    )
