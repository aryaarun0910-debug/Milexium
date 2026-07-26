"""Themis stores no inference as observed truth -- MX-ARCH-PROHIBITIONS-016.

    | Themis | must never infer uncertain facts and silently store them as reality |

WHAT IS ALREADY COVERED, AND WHY THIS FILE IS NOT THAT.
`test_ontology_v1.py` proves the individual refusals, one constructed instance at
a time: an imputed value cannot be an observation, a repaired value must say it
was repaired, a tie is not a resolution, confidence defaults to UNSTATED rather
than to certainty. Those are the right tests and they are not repeated here.

This file asserts the same prohibition ONE LEVEL UP, as a property of the shape
of `themis.ontology` rather than of any particular model:

1. **Every provenance field stays mandatory.** They are required today. The
   failure this catches is a future packet adding `quality: QualityState =
   QualityState.TRUSTED` because a caller found it tedious -- at which point an
   ingest that says nothing about quality produces a fact that claims to be
   trusted, and every existing test in `test_ontology_v1.py` still passes.
2. **Every model that carries a number carries provenance** -- itself, or in
   every record that embeds it. This is the generalisation, and the point is
   that it binds models NOT YET WRITTEN. A new `RiskScore` with a `probability`
   and no source fails on the day it is added rather than on the day someone
   reads it.
3. **No uncertainty may be defaulted into certainty, anywhere.** `SnapshotFact.
   confidence` is pinned individually in `test_ontology_v1`; here every
   confidence- and probability-shaped field in the package is held to it.
4. **The refusals hold across the whole cross product**, not at one point of it.
   `test_ontology_v1` proves an IMPUTED OBSERVATION is refused. Here every
   `RepairKind` is tried against every `FactClass`, and every non-NONE repair
   against every non-REPAIRED quality -- 8x5 and 8x4 -- because a refusal that
   was only ever exercised at one corner is exactly the shape of the vacuous
   tests this repository keeps finding.
5. **The record is frozen and closed.** A fact whose provenance can be edited
   after it is written, or which can carry an unmodelled field, is a fact whose
   provenance is decoration.

WHAT CANNOT BE MECHANISED, STATED PLAINLY -- READ THIS BEFORE QUOTING THE FILE.
The prohibition has two halves. Only one of them is testable.

  * **Testable: an inference that DECLARES itself cannot be stored as an
    observation.** Everything below is this half. The type system knows what the
    caller SAID the fact is, so it can refuse the combinations that contradict
    themselves.
  * **NOT testable here: an inference that LIES.** Nothing in this file, and
    nothing that could be written in this file, stops a caller constructing
    `SnapshotFact(fact_class=OBSERVATION, quality=TRUSTED, repair_kind=NONE,
    value=<a number it guessed>)`. The value is a float. Python cannot tell a
    measured 12.0 from an imputed one. The defence against that is the ADAPTER
    layer (`themis/connect/*` declares semantic loss and quarantines rows it
    cannot parse) plus review, and neither is asserted here.

  So the honest claim is: **Themis makes an honest ingest impossible to get
  wrong, and does not make a dishonest one impossible.** Anyone reading these
  tests as the second claim is reading more than they prove. That distinction is
  why this file exists at all -- ADR-0076 recorded Themis's prohibition as having
  "no test", and a test that overclaimed its coverage would have been worse than
  continuing to have none.

  Also NOT covered here, because it is covered elsewhere and duplicating it would
  spread one guarantee over two files: append-only immutability of the ontology
  tables (`ontology_immutability_{sqlite,postgres}.sql` and their conformance
  tests, ADR-0074), row-level tenant isolation, and the snapshot's point-in-time
  boundary (`test_decision_snapshot.py`).
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path
from types import UnionType
from typing import Union, get_args, get_origin

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticUndefined

from themis.ontology import (
    DEFAULT_MATCH_THRESHOLD,
    INTERNAL_DERIVATION_SOURCE,
    FactClass,
    FactId,
    ForcedMatchError,
    IdentityResolution,
    LegalBasis,
    MatchCandidate,
    ObjectId,
    ObjectKind,
    QualityState,
    RepairKind,
    SensitivityClass,
    SnapshotFact,
    new_id,
)
from themis.ontology.ids import CandidateSetId, TenantId
from themis.ontology.receipt import ReceiptStamp

REPO_ROOT = Path(__file__).resolve().parents[3]
ONTOLOGY_DIR = REPO_ROOT / "themis" / "ontology"

EXPECTED_ONTOLOGY_MODULES = frozenset(
    {
        "themis.ontology.graph",
        "themis.ontology.provenance",
        "themis.ontology.actions",
        "themis.ontology.events",
        "themis.ontology.snapshot",
        "themis.ontology.receipt",
    }
)
"""The modules that held provenance-bearing models when this file was written.
A floor for `test_the_model_survey_is_looking_at_the_ontology_and_not_at_an_empty_set`,
NOT the list that is surveyed."""


def ontology_modules() -> tuple[str, ...]:
    """Every module under `themis/ontology/`, DISCOVERED rather than listed.

    A hand-written list would have missed `themis/ontology/episode.py`, which was
    added by a concurrent packet while this file was being written -- and it would
    have missed it silently, which is the precise failure this packet exists to
    stop. The generalisations below are worth having only if they bind models
    nobody has written yet, and a fixed list guarantees they do not.

    The cost is accepted and stated: a new ontology model that breaks one of these
    rules turns this file red the moment it lands. That is the intended behaviour
    and it is why the failure messages say what to do about it.
    """
    return tuple(
        f"themis.ontology.{path.stem}"
        for path in sorted(ONTOLOGY_DIR.glob("*.py"))
        if path.stem != "__init__"
    )

# --------------------------------------------------------------------------- #
# What counts as "a number that could be an inference", and what counts as      #
# saying where it came from                                                     #
# --------------------------------------------------------------------------- #

UNCERTAIN_VALUE_FIELDS = frozenset(
    {
        "value",
        "probability",
        "confidence",
        "weight",
        "score",
        "point_estimate",
        "interval_low",
        "interval_high",
    }
)
"""Fields that carry a quantity a system could have GUESSED rather than
received. `value` and `point_estimate` are the obvious ones; `weight` on a
Relationship and `probability` on a MatchCandidate are the two where a guess is
the normal case rather than the exception."""

PROVENANCE_FIELDS = frozenset(
    {
        "receipt",
        "source_system",
        "method",
        "fact_class",
        "model_version_id",
        "asserted_by",
        "verifier_name",
        "observed_at",
        "basis",
    }
)
"""Fields that say where a value came from: when we received it, which system
sent it, which rule proposed it, which model produced it, who asserted it.

`basis` was added when `themis/ontology/episode.py` landed mid-packet. Its
`ForeclosedOpportunity.weight` is a capacity-attribution share, and the model
requires a `basis` naming "producing procedure and version, plus whether its
enumeration was exhaustive" -- which is provenance in the strict sense the rule
means, written independently by another packet. That the generalisation was
satisfied by a module written without reference to it is the best evidence
available that it is the right generalisation."""

CERTAINTY_FIELDS = frozenset({"confidence", "probability"})
"""The subset whose DEFAULT is the interesting question. A default of 1.0 is the
arithmetic form of the claim this repository exists not to make; a default of
0.5 is barely better, because it is still a number nobody supplied."""

MANDATORY_FACT_PROVENANCE = (
    "fact_id",
    "tenant_id",
    "subject_kind",
    "subject_id",
    "attribute",
    "fact_class",
    "receipt",
    "quality",
    "sensitivity",
    "legal_basis",
    "source_system",
)
"""Every field of `SnapshotFact` that must stay required. Not "every field" --
`value`, `missing_reason`, `event_time`, `confidence`, `repairs_fact_id` and
`repair_note` are legitimately optional, and `repair_kind` legitimately defaults
to NONE (nothing was done to the value, which is the honest default rather than
an assumed one)."""


# --------------------------------------------------------------------------- #
# Fixtures                                                                      #
# --------------------------------------------------------------------------- #

TENANT = new_id(TenantId)
STAMP = ReceiptStamp(
    receipt_time=datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc), receipt_sequence=1
)


def _fact(**overrides) -> SnapshotFact:
    payload = {
        "fact_id": new_id(FactId),
        "tenant_id": TENANT,
        "subject_kind": ObjectKind.RIDER,
        "subject_id": new_id(ObjectId),
        "attribute": "mobility_aid",
        "value": "wheelchair",
        "fact_class": FactClass.DECLARATION,
        "receipt": STAMP,
        "quality": QualityState.TRUSTED,
        "sensitivity": SensitivityClass.IDENTITY,
        "legal_basis": LegalBasis.CONTRACT_PERFORMANCE,
        "source_system": "operator-export",
        "source_record_id": "row-1",
    }
    payload.update(overrides)
    return SnapshotFact(**payload)


def _candidate(probability: float, object_id: ObjectId | None = None) -> MatchCandidate:
    return MatchCandidate(
        candidate_object_id=object_id or new_id(ObjectId),
        candidate_kind=ObjectKind.RIDER,
        probability=probability,
        method="fuzzy-name-dob",
    )


def _resolution(*candidates: MatchCandidate, **overrides) -> IdentityResolution:
    payload = {
        "candidate_set_id": new_id(CandidateSetId),
        "tenant_id": TENANT,
        "subject_kind": ObjectKind.RIDER,
        "source_system": "operator-export",
        "source_record_id": "booking-9",
        "candidates": candidates,
        "receipt": STAMP,
    }
    payload.update(overrides)
    return IdentityResolution(**payload)


def _models() -> dict[str, type[BaseModel]]:
    """Every pydantic model DEFINED in themis.ontology, keyed by name."""
    found: dict[str, type[BaseModel]] = {}
    for module_name in ontology_modules():
        module = importlib.import_module(module_name)
        for name, obj in vars(module).items():
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseModel)
                and obj is not BaseModel
                and obj.__module__ == module_name
            ):
                found[name] = obj
    return found


def _embedded_models(model: type[BaseModel]) -> set[type[BaseModel]]:
    """The models this one holds as fields, unwrapping Optional, tuple and list."""
    out: set[type[BaseModel]] = set()

    def walk(annotation) -> None:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            out.add(annotation)
            return
        if get_origin(annotation) in (Union, UnionType) or get_args(annotation):
            for arg in get_args(annotation):
                walk(arg)

    for info in model.model_fields.values():
        walk(info.annotation)
    return out


def _embedders(models: dict[str, type[BaseModel]]) -> dict[type[BaseModel], set[type[BaseModel]]]:
    reverse: dict[type[BaseModel], set[type[BaseModel]]] = {m: set() for m in models.values()}
    for holder in models.values():
        for held in _embedded_models(holder):
            reverse.setdefault(held, set()).add(holder)
    return reverse


def _names_its_own_provenance(model: type[BaseModel]) -> bool:
    return any(
        name in PROVENANCE_FIELDS and info.is_required()
        for name, info in model.model_fields.items()
    )


def _traceable(
    model: type[BaseModel],
    embedders: dict[type[BaseModel], set[type[BaseModel]]],
    seen: frozenset[type[BaseModel]] = frozenset(),
) -> bool:
    """A model is traceable if it names its own provenance, or if EVERY record
    that embeds it does.

    The second clause is not a loophole, it is how a nested value object works:
    `ActionPrediction` deliberately allows `model_version_id=None` (the estimate
    came from a rule or a human, which is different provenance rather than
    missing provenance), and it is only ever carried inside an `ActionRecord`,
    which has a mandatory receipt, a policy version and an authority. EVERY, not
    ANY: one careless container is enough to make the value untraceable, and
    "some caller records it properly" is not a guarantee.
    """
    if _names_its_own_provenance(model):
        return True
    if model in seen:
        return False
    holders = embedders.get(model, set())
    if not holders:
        return False
    return all(_traceable(h, embedders, seen | {model}) for h in holders)


# --------------------------------------------------------------------------- #
# 0. The walker is not vacuous                                                  #
# --------------------------------------------------------------------------- #


def test_the_model_survey_is_looking_at_the_ontology_and_not_at_an_empty_set() -> None:
    """Every generalisation below iterates a set of models discovered by
    reflection. If that discovery returns nothing -- a renamed module, a changed
    `__module__` -- the loops run zero times and every one of them passes."""
    discovered = set(ontology_modules())
    missing = sorted(EXPECTED_ONTOLOGY_MODULES - discovered)
    assert missing == [], (
        f"these ontology modules were not discovered: {missing}. The survey is looking "
        "in the wrong directory and every generalisation below is running over less "
        "than it claims."
    )

    models = _models()
    assert len(models) >= 10, f"only {len(models)} ontology models discovered: {sorted(models)}"
    for expected in ("SnapshotFact", "MatchCandidate", "IdentityResolution", "ActionOutcome"):
        assert expected in models, f"{expected} was not discovered; the survey is broken"


def test_the_survey_finds_models_that_actually_carry_a_number() -> None:
    """The generalisations in section 2 are all of the form "every model carrying
    an uncertain value does X". If no model carries one, they are all true and
    all worthless."""
    models = _models()
    carrying = {
        name
        for name, model in models.items()
        if set(model.model_fields) & UNCERTAIN_VALUE_FIELDS
    }

    assert len(carrying) >= 4, (
        f"only {len(carrying)} ontology models carry an uncertain quantity: "
        f"{sorted(carrying)}. UNCERTAIN_VALUE_FIELDS has drifted out of step with the "
        "package and the rules below are checking almost nothing."
    )
    assert {"SnapshotFact", "MatchCandidate"} <= carrying


# --------------------------------------------------------------------------- #
# 1. Provenance is mandatory and cannot acquire a default                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("field", MANDATORY_FACT_PROVENANCE)
def test_no_provenance_field_of_a_fact_may_acquire_a_default(field: str) -> None:
    """The drift this catches is not a bug anyone would write on purpose. It is
    the convenience default: an ingest has fifty call sites, `quality` is the same
    at forty-eight of them, so it gets a default -- and from that moment a caller
    who says NOTHING about quality produces a fact that asserts TRUSTED. Nothing
    in `test_ontology_v1.py` would notice: every test there passes a quality
    explicitly."""
    info = SnapshotFact.model_fields[field]

    assert info.is_required(), (
        f"SnapshotFact.{field} now has a default ({info.default!r}). A provenance "
        "field with a default is a claim the caller never made: silence becomes an "
        "assertion. If the field genuinely has an honest default, it is not a "
        "provenance field and does not belong in MANDATORY_FACT_PROVENANCE -- say "
        "which, in an ADR."
    )


def test_the_optional_fields_of_a_fact_are_optional_for_a_stated_reason() -> None:
    """The other side of the same list, so it cannot be satisfied by simply making
    everything required. Each of these is optional because ABSENCE is meaningful,
    and the meaning is not "assume the usual"."""
    optional = {
        name for name, info in SnapshotFact.model_fields.items() if not info.is_required()
    }

    assert optional == {
        "value",  # absent when missing_reason says why -- the XOR
        "missing_reason",  # absent when there is a value
        "event_time",  # absent for a timeless declaration or derivation
        "confidence",  # absent means UNSTATED, and that is the point
        "repair_kind",  # defaults to NONE: nothing was done, which is honest
        "repairs_fact_id",
        "repair_note",
        "special_category",
        "source_record_id",  # only INTERNAL_DERIVATION_SOURCE may omit it
    }, (
        "the optional/required split on SnapshotFact has moved. Each optional field is "
        "optional because its ABSENCE carries a meaning; a new one needs that meaning "
        "written down, and a field leaving this set should leave "
        "MANDATORY_FACT_PROVENANCE's side of the line instead."
    )


def test_confidence_is_never_defaulted_into_certainty_anywhere_in_the_ontology() -> None:
    """`test_ontology_v1` pins this for `SnapshotFact.confidence`. Here it is the
    rule for the package: no field expressing a degree of belief may arrive with a
    number the caller did not supply. UNSTATED and 0.5 are different claims, and
    UNSTATED and 1.0 are opposite ones."""
    offenders: list[str] = []
    for name, model in _models().items():
        for field, info in model.model_fields.items():
            if field not in CERTAINTY_FIELDS:
                continue
            if info.is_required():
                continue
            if info.default is None or info.default is PydanticUndefined:
                continue
            offenders.append(f"{name}.{field} defaults to {info.default!r}")

    assert offenders == [], (
        "a degree of belief is defaulted rather than stated:\n"
        + "\n".join(offenders)
        + "\n\nA caller who supplies no confidence has not made a weak claim; they have "
        "made no claim. Required, or None, and nothing in between."
    )


# --------------------------------------------------------------------------- #
# 2. Every number carries its provenance -- including numbers not yet written    #
# --------------------------------------------------------------------------- #


def test_every_model_that_carries_a_number_can_say_where_it_came_from() -> None:
    """THE GENERALISATION, and the reason this file is not just more instance
    tests.

    An inference is a number. If a model can hold a number and cannot say where
    it came from, then storing an inference as reality is not merely possible --
    it is indistinguishable from storing an observation, because the record has
    nowhere to put the difference. Every model in the package that holds one is
    checked, so a model added next month is checked too."""
    models = _models()
    embedders = _embedders(models)

    offenders: list[str] = []
    for name, model in sorted(models.items()):
        carried = sorted(set(model.model_fields) & UNCERTAIN_VALUE_FIELDS)
        if not carried:
            continue
        if _traceable(model, embedders):
            continue
        holders = sorted(h.__name__ for h in embedders.get(model, set()))
        offenders.append(
            f"  {name} carries {carried} with no required provenance field "
            f"({sorted(PROVENANCE_FIELDS)}), and is embedded in {holders or 'nothing'}"
        )

    assert offenders == [], (
        "a value in the ontology cannot be traced to where it came from:\n"
        + "\n".join(offenders)
        + "\n\nThemis governs what is TRUE. A number with no source is not a fact, it is "
        "an assertion by whoever wrote the row -- and once it is stored, an operator "
        "asking 'where did this come from' gets no answer, which is the entire thing "
        "this product promises not to happen. Give the model a mandatory provenance "
        "field, or make it a value object carried only inside records that have one."
    )


def test_the_traceability_check_rejects_a_model_that_cannot_say_where_a_number_came_from() -> None:
    """The mutation. The real ontology is clean, so the loop above never populates
    its offender list, and a `_traceable` that returned True unconditionally would
    pass it. Here is a model of exactly the shape the rule exists to refuse: a
    probability, no source, embedded in nothing."""

    class RiskScore(BaseModel):
        subject_id: str
        probability: float

    orphan: dict[type[BaseModel], set[type[BaseModel]]] = {RiskScore: set()}
    assert not _traceable(RiskScore, orphan)

    class ScoredRecord(BaseModel):
        receipt: ReceiptStamp
        score: RiskScore

    # Carried inside a record that stamps a receipt: traceable through its holder.
    assert _traceable(RiskScore, {RiskScore: {ScoredRecord}, ScoredRecord: set()})

    # ... but only if EVERY holder does. One careless container is enough.
    class LooseRecord(BaseModel):
        score: RiskScore

    assert not _traceable(
        RiskScore, {RiskScore: {ScoredRecord, LooseRecord}, ScoredRecord: set(), LooseRecord: set()}
    ), (
        "traceability through holders must be ALL, not ANY -- otherwise one container "
        "that records nothing is excused by a sibling that records everything"
    )


def test_every_record_carrying_provenance_is_frozen_and_closed() -> None:
    """Provenance that can be edited after the fact is not provenance, and a model
    that accepts unmodelled fields is a place an ingest can park the operator's
    raw rider name next to the pseudonym. Both are `model_config` settings, which
    means both are one line away from being switched off."""
    offenders: list[str] = []
    for name, model in sorted(_models().items()):
        if not (set(model.model_fields) & PROVENANCE_FIELDS):
            continue
        config = model.model_config
        if not config.get("frozen"):
            offenders.append(f"{name} is not frozen: its provenance can be rewritten in place")
        if config.get("extra") != "forbid":
            offenders.append(f"{name} accepts extra fields: an unmodelled value can ride along")

    assert offenders == [], "\n".join(offenders)


# --------------------------------------------------------------------------- #
# 3. The refusals hold across the whole cross product, not at one corner         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "fact_class", [c for c in FactClass if c is not FactClass.DERIVATION]
)
def test_an_imputed_value_is_refused_for_every_fact_class_except_derivation(
    fact_class: FactClass,
) -> None:
    """`test_ontology_v1` proves this for OBSERVATION. The corner it does not
    reach is the one that matters next: an imputed PLAN or an imputed DECLARATION
    is the same lie in a different costume, and a rule that only guards
    OBSERVATION guards the case someone already thought of.

    An imputed value was COMPUTED HERE. That makes it a derivation, whatever the
    caller wanted to call it."""
    with pytest.raises(ValidationError, match="IMPUTED"):
        _fact(
            fact_class=fact_class,
            repair_kind=RepairKind.IMPUTED,
            quality=QualityState.REPAIRED,
            event_time=STAMP.receipt_time,
        )


def test_an_imputed_derivation_is_accepted_so_the_rule_is_a_boundary_not_a_ban() -> None:
    """The positive control. If IMPUTED were refused everywhere, the test above
    would pass for the wrong reason and imputation would be impossible rather than
    honest -- and imputation is legitimate, it just has to declare itself."""
    fact = _fact(
        fact_class=FactClass.DERIVATION,
        repair_kind=RepairKind.IMPUTED,
        quality=QualityState.REPAIRED,
        source_system=INTERNAL_DERIVATION_SOURCE,
        source_record_id=None,
    )

    assert fact.repair_kind is RepairKind.IMPUTED
    assert fact.quality is QualityState.REPAIRED
    assert not fact.trainable or fact.legal_basis is not LegalBasis.NOT_ESTABLISHED


@pytest.mark.parametrize("repair", [r for r in RepairKind if r is not RepairKind.NONE])
@pytest.mark.parametrize(
    "quality", [q for q in QualityState if q is not QualityState.REPAIRED]
)
def test_a_repaired_value_cannot_claim_any_untouched_quality(
    repair: RepairKind, quality: QualityState
) -> None:
    """The full 8x4. A downstream consumer weighting by `quality` is the whole
    reason the field exists; a repaired value wearing TRUSTED is a silent thumb on
    that scale, and so is one wearing SUSPECT or CONFLICTED -- those say the
    SOURCE was doubtful, not that we changed the number."""
    kwargs = {"repair_kind": repair, "quality": quality}
    if repair is RepairKind.MANUALLY_CORRECTED:
        kwargs["repair_note"] = "dispatcher corrected a transposed pickup time"
    if repair is RepairKind.IMPUTED:
        kwargs["fact_class"] = FactClass.DERIVATION

    with pytest.raises(ValidationError, match="repaired value must say so"):
        _fact(**kwargs)


@pytest.mark.parametrize("repair", [r for r in RepairKind if r is not RepairKind.NONE])
def test_every_repair_kind_is_recordable_when_it_declares_itself(repair: RepairKind) -> None:
    """The positive control for the cross product above. Without it, a validator
    that rejected EVERY repair would satisfy all 32 refusals and the package would
    have quietly become unable to record a legitimate unit normalisation."""
    kwargs = {"repair_kind": repair, "quality": QualityState.REPAIRED}
    if repair is RepairKind.MANUALLY_CORRECTED:
        kwargs["repair_note"] = "dispatcher corrected a transposed pickup time"
    if repair is RepairKind.IMPUTED:
        kwargs["fact_class"] = FactClass.DERIVATION

    assert _fact(**kwargs).repair_kind is repair


@pytest.mark.parametrize(
    "fact_class",
    [c for c in FactClass if c not in (FactClass.DERIVATION, FactClass.PREDICTION)],
)
def test_milexium_s_own_derivation_source_cannot_produce_any_other_kind_of_claim(
    fact_class: FactClass,
) -> None:
    """`INTERNAL_DERIVATION_SOURCE` is the one source permitted to have no
    `source_record_id`, because there is no operator record behind it. That
    exemption must not become a way to write an unsourced OBSERVATION: a fact
    Milexium computed cannot also be a fact Milexium witnessed."""
    with pytest.raises(ValidationError, match="derivations and"):
        _fact(
            fact_class=fact_class,
            source_system=INTERNAL_DERIVATION_SOURCE,
            source_record_id=None,
            event_time=STAMP.receipt_time,
        )


# --------------------------------------------------------------------------- #
# 4. An uncertain identity is retained, never resolved into reality             #
# --------------------------------------------------------------------------- #


def test_would_resolve_never_returns_a_candidate_the_evidence_does_not_support() -> None:
    """A property over the shape of the candidate set rather than three worked
    examples.

    `IdentityResolution` is where "infer and store as reality" would do the most
    damage: a merge at 0.61 silently attributes one rider's trip history to
    another, and once a model has trained on it there is nothing to undo. The
    class's answer is `would_resolve` -- a PURE proposal. This walks the decision
    surface around the threshold and asserts the proposal is either the unique
    strict argmax at or above it, or nothing at all."""
    proposed_count = refused_count = 0
    for probabilities in (
        (0.99,),
        (0.96, 0.03),
        (0.5, 0.5),
        (0.61, 0.39),
        (0.95, 0.04),
        (0.949, 0.05),
        (0.4, 0.35, 0.2),
        (0.34, 0.33, 0.33),
    ):
        candidates = tuple(_candidate(p) for p in probabilities)
        resolution = _resolution(*candidates)
        proposed = resolution.would_resolve(DEFAULT_MATCH_THRESHOLD)

        ranked = sorted(candidates, key=lambda c: c.probability, reverse=True)
        top = ranked[0]
        tied = len(ranked) > 1 and abs(ranked[1].probability - top.probability) < 1e-12

        if top.probability >= DEFAULT_MATCH_THRESHOLD and not tied:
            assert proposed == top.candidate_object_id, probabilities
            proposed_count += 1
        else:
            assert proposed is None, (
                f"{probabilities} produced a proposal; below the threshold or tied, the "
                "candidates stay retained and the dependent facts stay UNRESOLVED"
            )
            refused_count += 1

    # Both branches have to have run, or this is a one-sided test wearing a loop.
    # A threshold of 0.0 would make every case resolve and a threshold of 1.0 would
    # make none, and either way the assertion above would still be green.
    assert proposed_count >= 2, f"only {proposed_count} case proposed a resolution"
    assert refused_count >= 4, f"only {refused_count} cases stayed unresolved"


def test_proposing_a_resolution_does_not_make_one() -> None:
    """The distinction the whole class turns on: `would_resolve` PROPOSES, and
    recording a resolution is a separate, receipt-stamped write. A method that
    resolved in place would destroy the instant the resolution became known, and
    a snapshot taken before it would then wrongly see it."""
    resolution = _resolution(_candidate(0.99), _candidate(0.005))
    before = resolution.model_dump()

    proposed = resolution.would_resolve()

    assert proposed is not None
    assert resolution.resolved_object_id is None, (
        "would_resolve mutated the record: the identity is now resolved without a new "
        "receipt, and every snapshot taken before this moment has retroactively changed"
    )
    assert resolution.is_resolved is False
    assert resolution.model_dump() == before


@pytest.mark.parametrize(
    "probabilities,resolve_to",
    [
        ((0.5, 0.5), 0),  # a tie
        ((0.5, 0.5), 1),  # the same tie, other side
        ((0.4, 0.6), 0),  # the weaker one
        ((0.33, 0.33, 0.34), 0),  # a weaker one among three
        ((0.49, 0.49, 0.02), 0),  # a tie for first, with a third present
    ],
)
def test_a_merge_the_candidates_do_not_support_is_refused(
    probabilities: tuple[float, ...], resolve_to: int
) -> None:
    """The destructive answers a warehouse gives, refused by construction: pick
    either side of a tie, pick the weaker one. The candidates are retained
    precisely so the question can be reopened when better evidence arrives."""
    candidates = tuple(_candidate(p) for p in probabilities)

    with pytest.raises(ForcedMatchError):
        _resolution(
            *candidates,
            resolved_object_id=candidates[resolve_to].candidate_object_id,
            resolution_rule="unique-argmax>=0.95",
        )


def test_resolving_to_something_that_was_never_a_candidate_is_refused() -> None:
    """The other forced merge: a resolution to an object that was not among the
    hypotheses considered. That is not a decision about the candidate set, it is a
    decision taken somewhere else and written into it."""
    with pytest.raises(ForcedMatchError, match="not among the"):
        _resolution(
            _candidate(0.99),
            _candidate(0.005),
            resolved_object_id=new_id(ObjectId),
            resolution_rule="unique-argmax>=0.95",
        )


def test_the_match_threshold_is_advisory_and_the_recorded_rule_is_what_binds() -> None:
    """FINDING, asserted because it is the sharpest edge in this class and I had
    it wrong before running it.

    `DEFAULT_MATCH_THRESHOLD` (0.95) is NOT a construction-time constraint. It
    lives in `would_resolve`, which PROPOSES. The constructor enforces two things
    -- the resolution must be the UNIQUE STRONGEST candidate, and it must name the
    rule it was made under -- and nothing else. So a 0.61-versus-0.39 merge IS
    recordable, and `would_resolve` would have refused to propose it.

    That is deliberate rather than a hole, and the reason is the case the
    threshold cannot see: a dispatcher phones the rider and confirms the match.
    The evidence is now external to the scorer, the probability is stale, and a
    hard 0.95 gate would make the one resolution anybody is actually confident
    about the one the system refuses to record. What keeps it honest is
    `resolution_rule` being mandatory -- the merge carries the authority it was
    made under, so 'operator-confirmed-by-phone' and 'unique-argmax>=0.95' are
    distinguishable forever after.

    Written down here because the class docstring reads as though 0.61 merges are
    impossible ("this class does none of them"), and they are not. Anyone relying
    on the threshold to be enforced is relying on the wrong thing: what is
    enforced is that the merge is attributable."""
    strongest = _candidate(0.61)
    weak_merge = _resolution(
        strongest,
        _candidate(0.39),
        resolved_object_id=strongest.candidate_object_id,
        resolution_rule="operator-confirmed-by-phone",
    )

    assert weak_merge.is_resolved, (
        "the constructor has started enforcing DEFAULT_MATCH_THRESHOLD. That is a "
        "stronger rule than this class had -- update this test and the finding it "
        "records, and check that an operator-confirmed match can still be written."
    )
    assert weak_merge.would_resolve(DEFAULT_MATCH_THRESHOLD) is None, (
        "the automatic path would now propose a 0.61 merge; the threshold has moved "
        "and the class has lost the gap between 'a rule proposed this' and 'a human "
        "confirmed it'"
    )
    assert weak_merge.resolution_rule == "operator-confirmed-by-phone"
    assert len(weak_merge.candidates) == 2, "the losing hypothesis is still retained"


def test_an_unresolved_identity_marks_its_dependents_rather_than_dropping_them() -> None:
    """The recoverable state. An unresolved identity is not an error and not a
    reason to discard the booking: the trip happened, and the record says which
    part of it is not yet attributable."""
    resolution = _resolution(_candidate(0.61), _candidate(0.39))

    assert resolution.missingness() is not None
    assert resolution.missingness().value == "unresolved_identity"
    assert len(resolution.candidates) == 2, "both hypotheses are kept"

    fact = _fact(value=None, missing_reason=resolution.missingness())
    assert fact.value is None
    assert fact.is_known is False


def test_a_resolution_that_is_supported_still_has_to_name_its_rule() -> None:
    """The positive control for the four refusals above -- without it, an
    `IdentityResolution` that refused every resolution would satisfy all of them
    -- and the additional requirement that a resolution states the rule it was
    made under, so a later reviewer can re-run it."""
    strong = _candidate(0.99)
    resolved = _resolution(
        strong,
        _candidate(0.005),
        resolved_object_id=strong.candidate_object_id,
        resolution_rule="unique-argmax>=0.95",
    )
    assert resolved.is_resolved
    assert resolved.missingness() is None

    with pytest.raises(ValidationError, match="rule it was made under"):
        _resolution(
            strong, _candidate(0.005), resolved_object_id=strong.candidate_object_id
        )


def test_a_candidate_set_that_is_not_probabilities_is_refused() -> None:
    """Hypotheses about ONE identity are mutually exclusive, so they cannot sum
    above 1. A scorer whose outputs do is not producing probabilities, and every
    threshold downstream -- including the 0.95 that decides whether a merge
    happens -- would be meaningless against it."""
    with pytest.raises(ValidationError, match="mutually"):
        _resolution(_candidate(0.8), _candidate(0.5))

    # A residual below 1 is expected and means "possibly none of these".
    assert _resolution(_candidate(0.4), _candidate(0.3)).would_resolve() is None
