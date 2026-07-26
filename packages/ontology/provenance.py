"""Field-level provenance: what a single claim is, where it came from, and on
what footing Milexium may use it.

THE UNIT IS A FIELD, NOT A ROW. A paratransit booking row mixes a pseudonym held
to perform a contract, a mobility-device code that is health-adjacent, a pickup
coordinate that may sit inside a women's refuge, and a dispatcher's free-text
note. A table-level privacy label forces one rule onto all four: either the
strictest (and the pickup zone becomes unusable for scheduling) or the loosest
(and the refuge coordinate leaves the boundary). `packages/canonical/vocab.py`
already made this call for `SensitivityClass` -- "attached to fields, not just
tables, so an export/redaction step can act field-by-field rather than trusting
a table-level label". This module is that decision carried through to every
attribute of every object in the ontology.

WHAT A `SnapshotFact` CARRIES, AND WHY EACH ONE IS MANDATORY.

  source system + source record id
      Without both, a disputed value cannot be taken back to the operator and
      checked. `source_record_id` is required for anything that came from
      outside; only an internally DERIVED fact may omit it.
  event time
      When the claim is about. For an OBSERVATION this is when it was observed;
      for a PREDICTION or a PLAN it is the instant being predicted or planned
      for, which may legitimately be in the future.
  Milexium receipt time
      When we found out. The ONLY field the point-in-time boundary is keyed on.
      Writer-assigned; see `packages/ontology/receipt.py`.
  confidence / quality state
      A telemetry ping and a hand-typed correction are not equally trustworthy
      and must not be averaged as if they were.
  repair lineage
      What was done to the value between the source and here. An IMPUTED value
      that cannot be distinguished from an observed one is how a model learns to
      predict its own imputation rule.
  privacy classification
      `SensitivityClass`, plus `special_category` for the health-adjacent case
      that classification does not distinguish.
  legal-use basis
      Per field, because "we may dispatch with this" and "we may train on this"
      are different permissions and the second is routinely absent.
  missingness reason
      "Null" is not one fact but nine. See `MissingnessReason`.

THE INVARIANT THAT MAKES THE SNAPSHOT'S BOUNDARY A THEOREM.
An OBSERVATION is rejected at construction if its `event_time` is later than its
`receipt_time` -- you cannot receive an observation before it is observed.
Because a snapshot admits a fact only when `receipt_time < as_of`, it follows
without any further filtering that every observation in a snapshot describes the
strict past. That deduction is why this module applies no filter on event time
and the snapshot applies none either: a second filter would have needed an
exception for predictions, and the exception would have been the hole.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.canonical.time import UtcDateTime
from packages.ontology.ids import CandidateSetId, FactId, ObjectId, TenantId
from packages.ontology.receipt import ReceiptStamp
from packages.ontology.vocab import (
    FactClass,
    LegalBasis,
    MissingnessReason,
    ObjectKind,
    QualityState,
    RepairKind,
    SensitivityClass,
)

__all__ = [
    "INTERNAL_DERIVATION_SOURCE",
    "DEFAULT_MATCH_THRESHOLD",
    "FactValue",
    "SnapshotFact",
    "MatchCandidate",
    "IdentityResolution",
    "ForcedMatchError",
]

INTERNAL_DERIVATION_SOURCE = "milexium.derivation"
"""The only `source_system` value permitted to omit a `source_record_id`.

A well-known constant rather than a `None` source, so a fact computed inside
Milexium is visibly distinguishable in a table dump from one whose source was
simply not recorded. The two are very different when an operator asks where a
number came from."""

DEFAULT_MATCH_THRESHOLD = 0.95
"""The probability at or above which a unique top identity candidate may be
treated as resolved.

A GUESS, and one of the cheapest in this package to change -- it is a single
constant with no other consumer, and `IdentityResolution.would_resolve` takes
the threshold as an argument so a caller need not accept this default at all.
0.95 is chosen to be deliberately conservative: an unresolved identity produces
`MissingnessReason.UNRESOLVED_IDENTITY` with every candidate retained, which is
a recoverable state, whereas a wrong merge silently attributes one rider's trip
history to another and is not recoverable once trained on. The right value is an
operator-specific question -- see the packet's `guesses_about_operator_data`."""


FactValue = float | int | str | bool | None
"""The value a fact carries.

DELIBERATELY NARROW. A nested structure would be a place to hide an untimestamped
sub-object, which is precisely what this package refuses -- everything that has
its own history has to be its own fact with its own receipt time. A composite
"address" is three facts, not one dict, and that is the point.
"""


class SnapshotFact(BaseModel):
    """ONE field-level claim about ONE attribute of ONE object, with its full
    provenance envelope.

    Frozen and `extra='forbid'`: an ingest cannot smuggle an unmodelled field
    (an operator's raw rider name alongside the pseudonym, a free-text note that
    would read as a reason code) onto a fact and have it flow into a snapshot.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fact_id: FactId
    tenant_id: TenantId

    # -- what the claim is about ------------------------------------------- #
    subject_kind: ObjectKind
    subject_id: ObjectId
    attribute: str = Field(
        min_length=1,
        description=(
            "The attribute named. A plain string, not a closed enum, and this is "
            "the one place the package accepts an open vocabulary: the attribute "
            "set is exactly what varies between operators, and a closed enum "
            "would mean an operator's genuinely-held field could not be loaded "
            "at all -- the opposite of 'their records can be loaded the day they "
            "arrive'. Consumers branch on `attribute` only through explicit "
            "lookups that handle absence."
        ),
    )

    # -- the value, or the reason there is none ---------------------------- #
    value: FactValue = None
    missing_reason: MissingnessReason | None = None

    # -- the two clocks ----------------------------------------------------- #
    fact_class: FactClass
    event_time: UtcDateTime | None = Field(
        default=None,
        description=(
            "When the claim is ABOUT. Required for an observation (when it was "
            "observed) and for a prediction or plan (the instant being predicted "
            "or planned for). Optional for a declaration or a derivation, which "
            "may be timeless."
        ),
    )
    receipt: ReceiptStamp = Field(
        description=(
            "When Milexium received this fact. THE field the point-in-time "
            "boundary is keyed on, and the only clock the caller does not own."
        )
    )

    # -- quality ------------------------------------------------------------ #
    quality: QualityState
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Calibrated probability the value is correct, where the source "
            "supplies or the repair implies one. None means UNSTATED, never 1.0 "
            "-- defaulting an unknown confidence to certainty is the arithmetic "
            "version of the claim this repository exists not to make."
        ),
    )

    # -- repair lineage (backward-pointing only; see RepairKind) ------------ #
    repair_kind: RepairKind = RepairKind.NONE
    repairs_fact_id: FactId | None = None
    repair_note: str | None = None

    # -- governance --------------------------------------------------------- #
    sensitivity: SensitivityClass
    special_category: bool = Field(
        default=False,
        description=(
            "Health, disability or other special-category personal data. A "
            "SEPARATE flag rather than a fifth member of SensitivityClass, so "
            "the canonical privacy vocabulary is reused unforked (a second "
            "privacy enum is the drift packages/canonical/vocab.py warns "
            "about). An eligibility determination is IDENTITY-classified AND "
            "special-category; the two facts are independent."
        ),
    )
    legal_basis: LegalBasis

    # -- source -------------------------------------------------------------- #
    source_system: str = Field(min_length=1)
    source_record_id: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "SnapshotFact":
        # 1. A value XOR a reason there is none. Both is a contradiction; neither
        #    is an undifferentiated null, which is the thing this class abolishes.
        has_value = self.value is not None
        has_reason = self.missing_reason is not None
        if has_value and has_reason:
            raise ValueError(
                f"fact {self.attribute!r} carries both a value ({self.value!r}) and a "
                f"missingness reason ({self.missing_reason.value}): a field is either "
                "known or it is not"
            )
        if not has_value and not has_reason:
            raise ValueError(
                f"fact {self.attribute!r} has no value and no missingness reason. "
                "An unexplained null is exactly what this record exists to make "
                "impossible -- state WHY it is absent (MissingnessReason has nine "
                "cases; 'not_collected' is a legitimate answer)"
            )

        # 2. THE OBSERVATION RULE -- see this module's docstring. It is what makes
        #    the snapshot's past-only property a deduction rather than a filter.
        if self.fact_class is FactClass.OBSERVATION:
            # An observation that carries a VALUE must say when it was observed;
            # one that records an ABSENCE need not, because there was nothing
            # observed to time. The theorem is unaffected: it is about values,
            # and an absent observation has none to leak. Requiring a time for an
            # absence would force callers to invent one, and an invented
            # observation time is worse than a stated absence.
            if self.event_time is None and has_value:
                raise ValueError(
                    "an observation carrying a value must state when it was observed "
                    "(event_time)"
                )
            if self.event_time is not None and self.event_time > self.receipt.receipt_time:
                raise ValueError(
                    f"observation of {self.attribute!r} claims to have been observed at "
                    f"{self.event_time.isoformat()}, AFTER Milexium received it at "
                    f"{self.receipt.receipt_time.isoformat()}. An observation cannot "
                    "arrive before it happens -- this is a prediction, a plan, or a "
                    "clock defect"
                )
        if self.fact_class in (FactClass.PREDICTION, FactClass.PLAN):
            if self.event_time is None:
                raise ValueError(
                    f"a {self.fact_class.value} must state the instant it is about "
                    "(event_time); an untimed prediction cannot be scored"
                )

        # 3. Repair lineage. An imputed value may never wear an observation's
        #    clothes -- a model that cannot tell them apart learns its own
        #    imputation rule and reports the result as skill.
        if self.repair_kind is RepairKind.NONE:
            if self.repairs_fact_id is not None:
                raise ValueError(
                    "repairs_fact_id names a repaired fact but repair_kind is 'none'"
                )
        else:
            if self.quality is not QualityState.REPAIRED:
                raise ValueError(
                    f"repair_kind={self.repair_kind.value} but quality="
                    f"{self.quality.value}: a repaired value must say so, or a "
                    "consumer weighting by quality will treat it as untouched"
                )
        if self.repair_kind is RepairKind.IMPUTED and self.fact_class is not (
            FactClass.DERIVATION
        ):
            raise ValueError(
                "an IMPUTED value is a derivation, never an observation, a plan or "
                "a declaration: it was computed here, not received"
            )
        if self.repair_kind is RepairKind.MANUALLY_CORRECTED and not self.repair_note:
            raise ValueError(
                "a manual correction must carry a note saying what was corrected and "
                "on whose say-so; an unexplained hand edit is indistinguishable from "
                "tampering"
            )
        if self.repairs_fact_id is not None and self.repairs_fact_id == self.fact_id:
            raise ValueError("a fact cannot repair itself")

        # 4. Governance.
        if self.source_system != INTERNAL_DERIVATION_SOURCE and not self.source_record_id:
            raise ValueError(
                f"fact from external source {self.source_system!r} has no "
                "source_record_id: a disputed value must be traceable back to the "
                "operator's own record. Only "
                f"{INTERNAL_DERIVATION_SOURCE!r} may omit it"
            )
        if self.source_system == INTERNAL_DERIVATION_SOURCE and self.fact_class not in (
            FactClass.DERIVATION,
            FactClass.PREDICTION,
        ):
            raise ValueError(
                f"{INTERNAL_DERIVATION_SOURCE!r} may only produce derivations and "
                f"predictions, not a {self.fact_class.value}"
            )
        if self.special_category and self.legal_basis is LegalBasis.NOT_ESTABLISHED:
            # DELIBERATELY THE WEAKEST DEFENSIBLE CHECK. Which bases actually
            # suffice for special-category data is a legal question with different
            # answers in different jurisdictions, and encoding one jurisdiction's
            # answer here would be a legal opinion this repository is not entitled
            # to hold. What IS defensible everywhere: holding health-adjacent data
            # on no stated basis at all is not a position anyone would defend.
            raise ValueError(
                f"special-category fact {self.attribute!r} has legal_basis="
                "'not_established'. Holding health-adjacent data on no stated basis "
                "is not a footing; name one, or record the field as "
                "MissingnessReason.SUPPRESSED_LEGAL instead of storing it"
            )
        return self

    # -- read helpers -------------------------------------------------------- #
    @property
    def is_known(self) -> bool:
        return self.value is not None

    @property
    def trainable(self) -> bool:
        """Whether this fact may enter a MODEL TRAINING snapshot.

        Dispatch and training do not have the same footing. A fact whose lawful
        basis was never established can still be acted on operationally (the
        operator holds it and asked us to dispatch with it); using it to build a
        durable statistical asset is a different act. `NOT_ESTABLISHED` is
        therefore excluded from training and admitted for dispatch, and
        `packages/ontology/store.py` applies this at snapshot construction so
        the exclusion cannot be forgotten by a downstream feature builder.
        """
        return self.legal_basis is not LegalBasis.NOT_ESTABLISHED

    def redacted(self) -> "SnapshotFact":
        """This fact with its value replaced by a suppression marker.

        Returns a NEW fact -- the original is frozen and is not modified -- whose
        `missing_reason` is `SUPPRESSED_PRIVACY`, so a redacted export still
        says a value existed and why it is not shown, rather than looking like a
        field the operator never collected. The distinction matters to anyone
        computing coverage statistics over an export.
        """
        return self.model_validate(
            {
                **self.model_dump(),
                "value": None,
                "missing_reason": MissingnessReason.SUPPRESSED_PRIVACY,
            }
        )


# --------------------------------------------------------------------------- #
# Uncertain identity: candidates, retained
# --------------------------------------------------------------------------- #
class ForcedMatchError(Exception):
    """An attempt to declare an identity resolved that the candidates do not
    support -- naming a non-candidate, or naming a candidate that is not the
    unique strongest one.

    NOT a `ValueError`: pydantic re-raises those from a validator as a
    `ValidationError`, and a forced merge must be distinguishable from a
    malformed field at every call site. See `SnapshotLeakageError` for the full
    reasoning."""


class MatchCandidate(BaseModel):
    """One hypothesis about which object a source record refers to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_object_id: ObjectId
    candidate_kind: ObjectKind
    probability: float = Field(
        gt=0.0,
        le=1.0,
        description=(
            "Probability this candidate is the right one. Strictly positive: a "
            "zero-probability candidate is not a candidate, and admitting one "
            "would let a rejected hypothesis sit in the set looking considered."
        ),
    )
    method: str = Field(
        min_length=1,
        description="How the candidate was proposed (an exact key, a fuzzy name/DOB score, a trip-pattern match). Kept so a match rule can be audited and re-run.",
    )
    evidence: tuple[str, ...] = Field(
        default=(),
        description="The specific features that fired, as short opaque tokens. Never raw personal data -- an evidence string saying 'surname exact' is auditable; one containing the surname is a disclosure.",
    )


class IdentityResolution(BaseModel):
    """The candidate set for ONE uncertain identity, retained with probabilities.

    THE POINT OF THIS CLASS IS THE MERGE THAT DOES NOT HAPPEN. Operator intake
    routinely produces a booking whose rider reference matches two pseudonyms at
    0.61 and 0.39. Every warehouse-shaped answer to that is destructive: pick the
    higher one (and silently attribute a trip to the wrong person), create a
    third merged rider (and destroy both histories), or drop the record (and lose
    the trip). This class does none of them. It stores both hypotheses, marks the
    dependent facts `MissingnessReason.UNRESOLVED_IDENTITY`, and stays
    resolvable later when better evidence arrives -- as a NEW resolution with a
    NEW receipt time, which a snapshot taken before it will correctly not see.

    Frozen: a resolution is asserted, never edited. A revised resolution is a new
    record.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_set_id: CandidateSetId
    tenant_id: TenantId
    subject_kind: ObjectKind
    source_system: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    candidates: tuple[MatchCandidate, ...] = Field(min_length=1)
    resolved_object_id: ObjectId | None = Field(
        default=None,
        description=(
            "The candidate accepted, if any. None means UNRESOLVED and is the "
            "honest default -- not an error state, and not a reason to discard "
            "the record."
        ),
    )
    resolution_rule: str | None = Field(
        default=None,
        description="The rule under which the resolution was made (e.g. 'unique-argmax>=0.95'). Required when resolved.",
    )
    receipt: ReceiptStamp

    @model_validator(mode="after")
    def _validate(self) -> "IdentityResolution":
        kinds = {c.candidate_kind for c in self.candidates}
        if kinds != {self.subject_kind}:
            raise ValueError(
                f"every candidate must be of the subject kind {self.subject_kind.value!r}; "
                f"got {sorted(k.value for k in kinds)}"
            )
        ids = [c.candidate_object_id for c in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError(
                "the same object appears twice in the candidate set: two probabilities "
                "for one hypothesis cannot both be right"
            )
        total = sum(c.probability for c in self.candidates)
        if total > 1.0 + 1e-9:
            # Mutually exclusive hypotheses. Summing above 1 means the scorer is
            # not producing probabilities, and treating its output as one would
            # make every downstream threshold meaningless.
            raise ValueError(
                f"candidate probabilities sum to {total:.6f} > 1: these are mutually "
                "exclusive hypotheses about one identity. A residual below 1 is "
                "expected and means 'possibly none of these'"
            )
        if self.resolved_object_id is not None:
            if self.resolved_object_id not in ids:
                raise ForcedMatchError(
                    "resolved_object_id names an object that is not among the "
                    "candidates: a resolution must be one of the hypotheses actually "
                    "considered"
                )
            best = max(c.probability for c in self.candidates)
            winners = [c for c in self.candidates if c.probability >= best - 1e-12]
            if len(winners) != 1 or winners[0].candidate_object_id != self.resolved_object_id:
                raise ForcedMatchError(
                    "resolved_object_id is not the unique strongest candidate. A tie, "
                    "or a resolution to a weaker hypothesis, must stay unresolved -- "
                    "the candidates are retained precisely so it can be revisited"
                )
            if not self.resolution_rule:
                raise ValueError("a resolution must state the rule it was made under")
        elif self.resolution_rule:
            raise ValueError(
                "resolution_rule is set but resolved_object_id is None: an unresolved "
                "identity was not resolved under any rule"
            )
        return self

    @property
    def is_resolved(self) -> bool:
        return self.resolved_object_id is not None

    def would_resolve(
        self, threshold: float = DEFAULT_MATCH_THRESHOLD
    ) -> ObjectId | None:
        """The object this set WOULD resolve to at `threshold`, or None.

        PURE and non-mutating: it proposes, it does not decide. Recording a
        resolution is a separate, receipt-stamped write, so the instant a
        resolution became known is preserved and a snapshot taken before it
        correctly does not see it. A method that resolved in place would have
        destroyed exactly that.
        """
        if not 0.0 < threshold <= 1.0:
            raise ValueError(f"threshold must be in (0, 1], got {threshold}")
        ranked = sorted(self.candidates, key=lambda c: c.probability, reverse=True)
        top = ranked[0]
        if top.probability < threshold:
            return None
        if len(ranked) > 1 and abs(ranked[1].probability - top.probability) < 1e-12:
            return None  # a tie is not a resolution
        return top.candidate_object_id

    def missingness(self) -> Literal[MissingnessReason.UNRESOLVED_IDENTITY] | None:
        """The missingness reason facts depending on this identity must carry
        while it is unresolved."""
        return None if self.is_resolved else MissingnessReason.UNRESOLVED_IDENTITY


def observation_precedes_receipt(event_time: datetime, receipt_time: datetime) -> bool:
    """The observation rule, exposed as a predicate so the conformance suite can
    assert the deduction in the module docstring directly rather than only
    through a constructor that happens to enforce it."""
    return event_time <= receipt_time
