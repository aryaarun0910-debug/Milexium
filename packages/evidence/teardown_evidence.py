"""A deadhead teardown carried inside an evidence pack -- and re-derived from it.

ADR-0039's `DeadheadTeardown` is the artifact a design partner is actually
handed: a specific, checkable finding about their own operation ("these hours,
these runs, this much empty time"). It was built to be verifiable -- a
deterministic `teardown_id`, an order-independent `segment_sha256`, every input
as `(name, value, source)`, numbered method steps -- and nothing verified it.
ADR-0017's `EvidencePack` is the portable bundle a third party re-verifies
WITHOUT Milexium. This module joins them.

**This module is the VERIFICATION side, and it deliberately imports nothing
from `packages.replay`.** That is the whole point. A verifier that called
`teardown_deadhead` again, or re-read the number it is checking, would have
verified nothing: it would only prove the generator agrees with itself. Here,
`rederive_teardown` recomputes the headline figures from two things only --

1. the **embedded segments** (the trip-structure rows the teardown ran on), and
2. the **manifest's declared input records** (`cost_per_vehicle_hour`,
   `reduction_fraction`, the operator's avoidable share), parsed out of the
   recorded `(name, value, source)` triples,

-- re-implementing the manifest's own numbered method steps, and only then
compares the result against the claimed figures. Inputs flow to outputs; the
claim is never an input to its own check. `packages/evidence/teardown_capture.py`
is the single module allowed to import the generator, and it only converts a
`DeadheadTeardown` into the models below.

**What re-derivation does and does not prove.** It proves the figures follow
arithmetically from the segments and inputs carried in the pack. It proves
nothing about whether those segments describe the operation faithfully, whether
any of the empty time was avoidable, or whether any money would be recovered --
the teardown's own hedges (`FIXED_COST_HEDGE`, ADR-0019's modelled-not-causal
note) are carried verbatim into the pack precisely because arithmetic
verification must not be mistaken for either.

Status: **Demonstrated**, exactly as ADR-0039 and ADR-0017 are.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, field_validator

from packages.canonical.events import canonical_json

TEARDOWN_EVIDENCE_VERSION = "0.1.0"

REDACTED_RUN_REF = "[REDACTED]"
"""What a run identifier becomes in a redacted pack. Deliberately NOT `None`:
`None` means "the export never carried a run reference" (honestly
unattributable), and overwriting a known run with that would turn a redaction
into a false statement about the source data."""

TEARDOWN_IN_PACK_NOTE = (
    "This pack carries a modelled deadhead teardown together with the "
    "trip-structure segments it was computed from, so a third party can "
    "RECOMPUTE its headline figures from those segments and the manifest's "
    "declared inputs instead of trusting the recorded numbers. Re-derivation "
    "checks arithmetic, not truth: it proves the figures follow from the data "
    "supplied, never that any empty time was avoidable, that the data "
    "describes the operation faithfully, or that any money would be recovered."
)

REDACTED_TEARDOWN_NOTE = (
    "REDACTED teardown: run identifiers are masked in both the ranking and the "
    "embedded segments, so the manifest's segment_sha256 and teardown_id can no "
    "longer be reproduced from what this pack carries, and no run can be "
    "re-attributed. The minute and money figures REMAIN re-derivable (they do "
    "not depend on run identity) and are still checked. What redaction costs is "
    "the binding between these segments and the original teardown: a redacted "
    "pack proves its figures follow from the segments it carries, not that "
    "those segments are the ones the teardown originally ran on. Preserving "
    "that binding under redaction needs per-field commitments, listed as not "
    "built in ADR-0017."
)

_SEGMENT_KINDS = ("revenue", "deadhead")
_PROVENANCE_VALUES = ("real_public", "synthetic")
"""Mirrors ADR-0039's `DataProvenance` EXACTLY, including the absence of an
"operator" value: this repo holds no operator data, and an evidence pack -- the
artifact that actually leaves the building -- is the last place a label
implying otherwise may be introduced."""

# Comparison tolerance. The generator emits figures rounded to 6 decimal places
# (ADR-0039's fixed emitted precision), so an honest figure differs from an exact
# re-derivation by at most 5e-7, plus float summation-order noise that scales
# with magnitude. A tamper smaller than this is invisible HERE -- but not to the
# bundle checksum, which catches any byte change at all.
_ROUNDING_SLACK = 1e-6
_RELATIVE_SLACK = 1e-9


class _TE(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TeardownSegmentRow(_TE):
    """One embedded segment: trip STRUCTURE only -- when it started, when it
    ended, whether it was earning, and which run it belonged to.

    These are the same four fields ADR-0039's `VehicleSegment` carries and the
    only four it reads, restated here as plain JSON-safe values so a pack can be
    loaded and re-derived without importing the generator. Nothing else can ride
    along: `extra="forbid"` plus a fixed four-field shape means a rider
    identifier cannot be attached to a segment on its way into a pack, just as
    it cannot be attached on its way into a teardown.

    Timestamps are held as the ISO-8601 strings the fingerprint is computed
    over, so the fingerprint is reproduced from bytes rather than from a
    re-formatting of a parsed value.
    """

    started_at: str
    ended_at: str
    kind: str
    run_ref: str | None

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in _SEGMENT_KINDS:
            raise ValueError(f"segment kind must be one of {_SEGMENT_KINDS}, got {value!r}")
        return value


class TeardownFigures(_TE):
    """The headline figures exactly as the teardown emitted them -- the CLAIM
    that gets re-derived and checked.

    Deliberately carries no input value. Every input (the cost per vehicle-hour,
    the modelled reduction fraction, the operator's avoidable share) lives in
    the manifest's `(name, value, source)` records, so re-derivation always runs
    inputs -> figures and can never be satisfied by reading a figure back out of
    the thing it is checking.

    `value_at_full_cost` is the accounting value of the empty time at the
    operator's own rate, NOT a saving; `hedge` carries ADR-0039's
    `FIXED_COST_HEDGE` verbatim and `envelope_basis` carries its refusal to
    guess a recoverable fraction when the operator's fixed-versus-variable split
    was not supplied.
    """

    total_deadhead_minutes: float
    total_revenue_minutes: float
    deadhead_share_of_vehicle_time: float | None
    deadhead_hours: float | None
    value_at_full_cost: float | None
    modelled_envelope_low: float | None
    modelled_envelope_high: float | None
    currency: str | None
    envelope_basis: str | None
    hedge: str | None
    is_guaranteed_saving: bool = False

    @field_validator("is_guaranteed_saving")
    @classmethod
    def _never_guarantee_a_saving(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "an evidence pack must never present a teardown's cost envelope "
                "as a guaranteed or realised saving: fixed costs do not fall "
                "proportionally with vehicle-hours removed (ADR-0039 "
                "FIXED_COST_HEDGE). The pack is the artifact a partner reads, so "
                "the refusal is enforced here as well as at the source."
            )
        return value


class TeardownBucketRow(_TE):
    """WHICH HOURS -- one clock position's empty and earning minutes, as
    claimed. `day_of_week` is None on an hour-of-day-only bucket and
    `hour_of_day` is None on a day-of-week-only bucket."""

    day_of_week: int | None
    hour_of_day: int | None
    deadhead_minutes: float
    revenue_minutes: float
    deadhead_share_of_bucket: float | None
    share_of_total_deadhead: float | None


class TeardownRunRow(_TE):
    """WHICH RUNS -- one run's contribution, as claimed. `attributable` is False
    exactly when the export carried no run reference; that row is reported
    outside the ranking so a top-N truncation can never bury it. A redacted pack
    masks `run_ref` to `[REDACTED]` and leaves `attributable` True: the run WAS
    identified in the source, it simply is not disclosed here."""

    run_ref: str | None
    attributable: bool
    deadhead_minutes: float
    revenue_minutes: float
    segment_count: int
    share_of_total_deadhead: float | None

    @field_validator("attributable")
    @classmethod
    def _attributable_is_a_fact_not_a_flag(cls, value: bool, info) -> bool:
        run_ref = info.data.get("run_ref")
        if value != (run_ref is not None):
            raise ValueError(
                "attributable must be True exactly when a run_ref is present; a "
                "segment with no identifier is unattributable, never guessed onto "
                "another run"
            )
        return value


class TeardownEvidence(_TE):
    """A deadhead teardown in pack-carriable form: the manifest verbatim, the
    claimed figures and surfaces, and the segments those figures must follow
    from.

    `manifest` is the ADR-0039 `TeardownManifest` dumped verbatim as a dict --
    the same convention `EvidencePack.evidence` already uses for the
    `EvidencePacket`, and the reason a pack can be loaded and re-derived with no
    `packages.replay` import anywhere in the verification path.

    `data_provenance` restates the manifest's provenance as a VALIDATED field
    (the manifest is a verbatim record and could say anything); re-derivation
    checks the two agree. It admits only "real_public" or "synthetic" -- a pack
    built from real public data says so, and there is no "operator" value to
    say anything else with.
    """

    evidence_version: str = TEARDOWN_EVIDENCE_VERSION
    manifest: dict
    teardown_id: str
    data_provenance: str
    figures: TeardownFigures
    by_hour_of_day: tuple[TeardownBucketRow, ...]
    by_day_of_week: tuple[TeardownBucketRow, ...]
    top_runs: tuple[TeardownRunRow, ...]
    unattributable: TeardownRunRow | None
    attributed_run_count: int
    segments: tuple[TeardownSegmentRow, ...]
    run_refs_redacted: bool = False
    is_modelled: bool = True
    causal_proof: bool = False
    interpretation: str
    note: str = TEARDOWN_IN_PACK_NOTE

    @field_validator("data_provenance")
    @classmethod
    def _provenance_survives_and_cannot_be_invented(cls, value: str) -> str:
        if value not in _PROVENANCE_VALUES:
            raise ValueError(
                f"data_provenance must be one of {_PROVENANCE_VALUES}, got "
                f"{value!r}. In particular there is no 'operator' provenance: "
                "this repository holds no operator data (ADR-0039), and an "
                "evidence pack must not be the place one is claimed."
            )
        return value

    @field_validator("causal_proof")
    @classmethod
    def _never_claim_causation(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "a teardown carried in an evidence pack must never claim causal "
                "proof (ADR-0019 / blueprint/01 boundary); causal_proof is always "
                "False"
            )
        return value


class TeardownRederivation(BaseModel):
    """The result of independently recomputing a carried teardown.

    `figures_rederived` is False only when a checked figure genuinely disagrees
    with the data. `fingerprint_rederived` is None -- not False -- when the
    check was not possible by declared design (a redacted pack), so "we could
    not check this" is never reported as "this passed" or as "this failed".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    figures_rederived: bool
    fingerprint_rederived: bool | None
    checked: tuple[str, ...]
    mismatches: tuple[str, ...]
    reasons: tuple[str, ...]


# --------------------------------------------------------------------------- #
# Re-derivation: the manifest's method steps, re-implemented from the segments #
# --------------------------------------------------------------------------- #


def _parse_instant(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _segment_minutes(row: TeardownSegmentRow) -> float:
    return (_parse_instant(row.ended_at) - _parse_instant(row.started_at)).total_seconds() / 60.0


def rederive_segment_fingerprint(segments: tuple[TeardownSegmentRow, ...]) -> str:
    """Recompute the order-independent segment fingerprint from the embedded
    rows, following the algorithm ADR-0039 documents: sort the four structural
    fields, serialize with the repository's normative `canonical_json`, sha256.

    Independently implemented here rather than imported from the generator --
    importing `segment_set_fingerprint` would make the check confirm only that
    one function agrees with itself. `canonical_json` is shared deliberately: it
    is the normative serializer an external re-implementation is told to
    reproduce byte-for-byte (ADR-0017), not generator logic.
    """
    ordered = sorted(
        [[s.started_at, s.ended_at, s.kind, s.run_ref] for s in segments],
        key=lambda row: (row[0], row[1], row[2], row[3] or ""),
    )
    return hashlib.sha256(canonical_json({"segments": ordered}).encode("utf-8")).hexdigest()


def _hour_slices(started_at: datetime, ended_at: datetime) -> list[tuple[datetime, float]]:
    """Method step 2, re-implemented: split a segment at hour boundaries so its
    minutes land in the hours they actually fell in (09:50-10:20 gives 10 to
    hour 09 and 20 to hour 10)."""
    slices: list[tuple[datetime, float]] = []
    cursor = started_at
    while cursor < ended_at:
        hour_start = cursor.replace(minute=0, second=0, microsecond=0)
        slice_end = min(hour_start + timedelta(hours=1), ended_at)
        slices.append((hour_start, (slice_end - cursor).total_seconds() / 60.0))
        cursor = slice_end
    return slices


def _share(part: float, whole: float) -> float | None:
    if whole <= 0:
        return None
    return part / whole


def _round(value: float) -> float:
    return round(value, 6)


def _close(claimed: float, rederived: float) -> bool:
    return abs(claimed - rederived) <= _ROUNDING_SLACK + abs(rederived) * _RELATIVE_SLACK


def _declared_inputs(manifest: dict) -> dict[str, str]:
    """The manifest's `(name, value, source)` input records as name -> value.
    These are the DECLARED inputs a re-derivation is entitled to use; the
    figures themselves are never read from here."""
    records = manifest.get("inputs") or ()
    declared: dict[str, str] = {}
    for record in records:
        if isinstance(record, dict) and "name" in record and "value" in record:
            declared[str(record["name"])] = str(record["value"])
    return declared


def _parse_rate(text: str) -> tuple[float, str] | None:
    """Parse the declared `cost_per_vehicle_hour` record, recorded as
    "<rate> <currency>". Returns None (never a default) when it cannot be read:
    a re-derivation that invented a rate would confirm a figure it had made up."""
    parts = text.split()
    if len(parts) != 2:
        return None
    try:
        return float(parts[0]), parts[1]
    except ValueError:
        return None


def _parse_share_range(text: str) -> tuple[float, float] | None:
    """Parse the declared avoidable (variable) share, recorded as "<low> .. <high>",
    or None when the operator's fixed-versus-variable split was not supplied --
    in which case no envelope may exist to check."""
    parts = text.split("..")
    if len(parts) != 2:
        return None
    try:
        return float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return None


class _Checker:
    """Collects per-figure comparisons so every checked figure is named in the
    result, whether it matched or not."""

    def __init__(self) -> None:
        self.checked: list[str] = []
        self.mismatches: list[str] = []

    def number(self, name: str, claimed: float | None, rederived: float | None) -> None:
        self.checked.append(name)
        if (claimed is None) != (rederived is None):
            # "no value" and "a value" are a real disagreement: a figure that
            # should be absent (no denominator, no cost basis) is not a zero.
            self.mismatches.append(f"{name}: claimed {claimed!r}, re-derived {rederived!r}")
            return
        if claimed is None or rederived is None:
            return
        if not _close(claimed, rederived):
            self.mismatches.append(
                f"{name}: claimed {claimed!r}, re-derived {rederived!r} from the "
                "embedded segments and the manifest's declared inputs"
            )

    def equal(self, name: str, claimed: object, rederived: object) -> None:
        self.checked.append(name)
        if claimed != rederived:
            self.mismatches.append(f"{name}: claimed {claimed!r}, re-derived {rederived!r}")


def _check_buckets(
    checker: _Checker,
    label: str,
    claimed: tuple[TeardownBucketRow, ...],
    rederived: dict[tuple[int | None, int | None], dict[str, float]],
    total_deadhead: float,
) -> None:
    keys_claimed = [(b.day_of_week, b.hour_of_day) for b in claimed]
    checker.equal(f"{label}.buckets", sorted(map(str, keys_claimed)), sorted(map(str, rederived)))
    for bucket in claimed:
        key = (bucket.day_of_week, bucket.hour_of_day)
        sums = rederived.get(key)
        if sums is None:
            checker.mismatches.append(
                f"{label}[{key}]: claimed a bucket the segments produce no minutes for"
            )
            continue
        where = f"{label}[day={bucket.day_of_week},hour={bucket.hour_of_day}]"
        checker.number(f"{where}.deadhead_minutes", bucket.deadhead_minutes, sums["deadhead"])
        checker.number(f"{where}.revenue_minutes", bucket.revenue_minutes, sums["revenue"])
        checker.number(
            f"{where}.deadhead_share_of_bucket",
            bucket.deadhead_share_of_bucket,
            _share(sums["deadhead"], sums["deadhead"] + sums["revenue"]),
        )
        checker.number(
            f"{where}.share_of_total_deadhead",
            bucket.share_of_total_deadhead,
            _share(sums["deadhead"], total_deadhead),
        )


def rederive_teardown(evidence: TeardownEvidence) -> TeardownRederivation:
    """Recompute a carried teardown's figures from the pack's own contents and
    report whether the claim survives.

    Reads exactly two sources: the embedded segments, and the manifest's
    declared input records. Re-implements the manifest's numbered method steps
    (classify -> bucket at hour boundaries -> attribute to runs -> reconcile ->
    cost) and compares the result to the claimed figures. Nothing is read from
    the generator, and no claimed figure is used to compute the value it is
    checked against.
    """
    checker = _Checker()
    reasons: list[str] = []
    segments = evidence.segments
    manifest = evidence.manifest
    declared = _declared_inputs(manifest)

    # -- the pack's own self-description must agree with the record it carries.
    checker.equal("manifest.teardown_id", evidence.teardown_id, manifest.get("teardown_id"))
    checker.equal("manifest.data_provenance", evidence.data_provenance, manifest.get("data_provenance"))
    checker.equal("manifest.segment_count", manifest.get("segment_count"), len(segments))

    # -- step 1/2/3: totals, hour and day buckets, run attribution, from segments.
    total_deadhead = sum(_segment_minutes(s) for s in segments if s.kind == "deadhead")
    total_revenue = sum(_segment_minutes(s) for s in segments if s.kind == "revenue")

    figures = evidence.figures
    checker.number("total_deadhead_minutes", figures.total_deadhead_minutes, total_deadhead)
    checker.number("total_revenue_minutes", figures.total_revenue_minutes, total_revenue)
    checker.number(
        "deadhead_share_of_vehicle_time",
        figures.deadhead_share_of_vehicle_time,
        _share(total_deadhead, total_deadhead + total_revenue),
    )

    by_hour: dict[tuple[int | None, int | None], dict[str, float]] = defaultdict(
        lambda: {"revenue": 0.0, "deadhead": 0.0}
    )
    by_day: dict[tuple[int | None, int | None], dict[str, float]] = defaultdict(
        lambda: {"revenue": 0.0, "deadhead": 0.0}
    )
    for segment in segments:
        for hour_start, minutes in _hour_slices(
            _parse_instant(segment.started_at), _parse_instant(segment.ended_at)
        ):
            by_hour[(None, hour_start.hour)][segment.kind] += minutes
            by_day[(hour_start.weekday(), None)][segment.kind] += minutes

    _check_buckets(checker, "by_hour_of_day", evidence.by_hour_of_day, dict(by_hour), total_deadhead)
    _check_buckets(checker, "by_day_of_week", evidence.by_day_of_week, dict(by_day), total_deadhead)

    if evidence.run_refs_redacted:
        reasons.append(
            "run attribution not re-checked: run identifiers are redacted, so no "
            "segment can be matched to the run it is claimed under"
        )
    else:
        _check_runs(checker, evidence, segments, total_deadhead)

    # -- step 5: cost, from the DECLARED inputs, never from the claimed figures.
    _check_cost(checker, figures, declared, total_deadhead, reasons)

    # -- the data binding: does the fingerprint still cover what is embedded?
    if evidence.run_refs_redacted:
        fingerprint_rederived: bool | None = None
        reasons.append(
            "segment fingerprint not re-checkable: masking run identifiers changes "
            "the bytes the manifest's segment_sha256 was computed over, so this "
            "pack cannot prove its segments are the ones the teardown ran on "
            "(see REDACTED_TEARDOWN_NOTE)"
        )
    else:
        recomputed = rederive_segment_fingerprint(segments)
        claimed_fingerprint = manifest.get("segment_sha256")
        fingerprint_rederived = recomputed == claimed_fingerprint
        if not fingerprint_rederived:
            checker.mismatches.append(
                f"manifest.segment_sha256: manifest says {claimed_fingerprint}, "
                f"re-derived {recomputed} from the embedded segments (these are not "
                "the segments this teardown was computed from)"
            )

    return TeardownRederivation(
        figures_rederived=not checker.mismatches,
        fingerprint_rederived=fingerprint_rederived,
        checked=tuple(checker.checked),
        mismatches=tuple(checker.mismatches),
        reasons=tuple(reasons),
    )


def _check_runs(
    checker: _Checker,
    evidence: TeardownEvidence,
    segments: tuple[TeardownSegmentRow, ...],
    total_deadhead: float,
) -> None:
    """Method step 3, re-implemented: group whole segments by run reference,
    rank by empty minutes, and hold the unidentified ones separately."""
    totals: dict[str | None, dict[str, float]] = defaultdict(
        lambda: {"revenue": 0.0, "deadhead": 0.0, "segments": 0.0}
    )
    for segment in segments:
        entry = totals[segment.run_ref]
        entry[segment.kind] += _segment_minutes(segment)
        entry["segments"] += 1

    def compare(row: TeardownRunRow, where: str) -> None:
        sums = totals.get(row.run_ref)
        if sums is None:
            checker.mismatches.append(f"{where}: claimed run {row.run_ref!r} has no segments")
            return
        checker.number(f"{where}.deadhead_minutes", row.deadhead_minutes, sums["deadhead"])
        checker.number(f"{where}.revenue_minutes", row.revenue_minutes, sums["revenue"])
        checker.equal(f"{where}.segment_count", row.segment_count, int(sums["segments"]))
        checker.number(
            f"{where}.share_of_total_deadhead",
            row.share_of_total_deadhead,
            _share(sums["deadhead"], total_deadhead),
        )

    ranked = sorted(
        (
            (run_ref, sums)
            for run_ref, sums in totals.items()
            if run_ref is not None and sums["deadhead"] > 0
        ),
        key=lambda item: (-_round(item[1]["deadhead"]), item[0]),
    )
    checker.equal("attributed_run_count", evidence.attributed_run_count, len(ranked))
    checker.equal(
        "top_runs.order",
        [row.run_ref for row in evidence.top_runs],
        [run_ref for run_ref, _ in ranked[: len(evidence.top_runs)]],
    )
    for index, row in enumerate(evidence.top_runs):
        compare(row, f"top_runs[{index}]")

    checker.equal("unattributable.present", evidence.unattributable is not None, None in totals)
    if evidence.unattributable is not None and None in totals:
        compare(evidence.unattributable, "unattributable")


def _check_cost(
    checker: _Checker,
    figures: TeardownFigures,
    declared: dict[str, str],
    total_deadhead: float,
    reasons: list[str],
) -> None:
    """Method step 5, re-implemented: the money figures from the declared rate
    and the declared modelling assumptions."""
    rate_text = declared.get("cost_per_vehicle_hour")
    claims_envelope = (
        figures.modelled_envelope_low is not None or figures.modelled_envelope_high is not None
    )
    claims_money = (
        figures.value_at_full_cost is not None
        or figures.deadhead_hours is not None
        or claims_envelope
    )

    if rate_text is None:
        if claims_money:
            checker.mismatches.append(
                "a money figure is claimed but the manifest declares no "
                "cost_per_vehicle_hour input to re-derive it from"
            )
        else:
            reasons.append(
                "no money figure claimed and no cost input declared: nothing to "
                "re-derive on the cost side"
            )
        return

    rate = _parse_rate(rate_text)
    if rate is None:
        checker.mismatches.append(
            f"declared cost_per_vehicle_hour {rate_text!r} could not be read as "
            "'<rate> <currency>', so the money figures cannot be re-derived and "
            "are not assumed correct"
        )
        return
    cost_per_hour, currency = rate

    deadhead_hours = total_deadhead / 60.0
    value_at_full_cost = deadhead_hours * cost_per_hour
    checker.number("deadhead_hours", figures.deadhead_hours, deadhead_hours)
    checker.number("value_at_full_cost", figures.value_at_full_cost, value_at_full_cost)
    checker.equal("currency", figures.currency, currency)

    reduction_text = declared.get("reduction_fraction")
    share = _parse_share_range(declared.get("avoidable_share_of_cost_per_hour", ""))

    if share is None or reduction_text is None:
        if claims_envelope:
            checker.mismatches.append(
                "a modelled envelope is claimed but the manifest declares no "
                "usable avoidable-share / reduction-fraction input to re-derive it from"
            )
        else:
            reasons.append(
                "no modelled envelope claimed: the operator's fixed-versus-variable "
                "split was not supplied, so the recoverable fraction is unknown and "
                "was not guessed (ADR-0039)"
            )
        return

    try:
        reduction_fraction = float(reduction_text)
    except ValueError:
        checker.mismatches.append(
            f"declared reduction_fraction {reduction_text!r} is not a number, so the "
            "modelled envelope cannot be re-derived"
        )
        return

    low, high = share
    checker.number(
        "modelled_envelope_low",
        figures.modelled_envelope_low,
        value_at_full_cost * reduction_fraction * low,
    )
    checker.number(
        "modelled_envelope_high",
        figures.modelled_envelope_high,
        value_at_full_cost * reduction_fraction * high,
    )


# --------------------------------------------------------------------------- #
# Redaction                                                                     #
# --------------------------------------------------------------------------- #


def redact_teardown_evidence(evidence: TeardownEvidence) -> TeardownEvidence:
    """Mask every run identifier in a carried teardown -- in the ranking AND in
    the embedded segments -- and record, in the artifact itself, exactly which
    guarantee that costs.

    A run reference is the operator's own operational identifier (ADR-0039
    keeps it as the source system writes it), so it leaves with the redacted
    pack or it does not leave at all. Nothing rider-linked is masked here
    because nothing rider-linked can be present: a segment carries four
    structural fields and no more, by construction at both ends.

    The masked pack keeps re-derivable minute and money figures (they never
    depended on run identity) and loses the fingerprint binding; `note` says so
    rather than leaving a reader to discover it.
    """
    if evidence.run_refs_redacted:
        return evidence

    def mask(run_ref: str | None) -> str | None:
        return None if run_ref is None else REDACTED_RUN_REF

    segments = tuple(
        row.model_copy(update={"run_ref": mask(row.run_ref)}) for row in evidence.segments
    )
    top_runs = tuple(
        row.model_copy(update={"run_ref": mask(row.run_ref)}) for row in evidence.top_runs
    )
    return evidence.model_copy(
        update={
            "segments": segments,
            "top_runs": top_runs,
            "run_refs_redacted": True,
            "note": f"{TEARDOWN_IN_PACK_NOTE} {REDACTED_TEARDOWN_NOTE}",
        }
    )
