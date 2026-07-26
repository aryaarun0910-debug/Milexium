"""Program H (partial): deadhead teardown -- which hours, which runs, how much.

NTD publishes deadhead as one ANNUAL AGGREGATE percentage per agency. That
number is enough to start a conversation and useless for acting on: an operator
cannot re-crew a year. This module localises non-revenue ("empty") vehicle time
from an operator's own TRIP-LEVEL records down to the hour, the day and the
individual run, which is the level a scheduler actually changes things at.

Three questions, three surfaces on one structured result:

- **WHICH HOURS** -- ``by_hour_of_day`` / ``by_day_of_week`` /
  ``by_day_of_week_and_hour``: empty minutes bucketed by clock position, with a
  segment that straddles an hour boundary split across both hours so the
  buckets reconcile exactly to the headline total.
- **WHICH RUNS** -- ``top_runs``: the vehicle/run/block segments contributing the
  most empty time, ranked. A segment whose run identifier is missing is *never*
  guessed onto a neighbouring run; it lands in ``unattributable``, which is
  reported separately so truncating ``top_runs`` can never hide it.
- **HOW MUCH** -- ``cost``: the empty hours valued at the operator's own cost per
  vehicle-hour. This is the *accounting value of the time*, not a saving. The
  recoverable part is bounded by the operator's fixed-versus-variable split, so
  a modelled envelope is only produced when the caller supplies that split, and
  it is never presented as guaranteed cash (see ``FIXED_COST_HEDGE``).

FRAMING (binding, ADR-0019 + blueprint/01): a teardown is a **modelled**
localisation of where empty time sat, never causal proof and never a promised
saving. That boundary is carried in code three ways, exactly as
``app.replay.comparison`` carries it: single-sourced note constants, field
validators that *raise* if ``causal_proof``/``is_guaranteed_saving`` are set
True, and a structural ``data_provenance`` label. This module reuses
``comparison.MODELLED_COMPARISON_NOTE`` and ``comparison.REPLAY_VERSION`` rather
than restating the discipline, and does not reimplement the baseline-vs-Milexium
comparator.

EVIDENCE DISCIPLINE: every teardown carries a ``TeardownManifest`` holding the
inputs (name, value, where it came from) and the ordered method actually
applied, so an operator can re-derive every figure from their own export
without trusting this code.

PRIVACY: the input vocabulary is trip STRUCTURE only -- start, end, revenue or
empty, and a run reference. ``VehicleSegment`` forbids extra fields, so a rider
identifier cannot be attached to one; ``VehicleSegment.from_row`` reads only the
columns it is pointed at, so every other column of a real export (including
rider columns) is dropped rather than carried; and pointing it at a
rider-identifier column raises. No rider identifier can reach the output.

Status: **Demonstrated**. There is no operator data in this repo -- hence
``DataProvenance`` has no "operator" value; the day a consented operator export
exists, that value is added alongside its consent record, not before.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Callable, Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.canonical.events import canonical_json
from app.canonical.time import UtcDateTime
from app.replay.comparison import MODELLED_COMPARISON_NOTE, REPLAY_VERSION

TEARDOWN_VERSION = "0.1.0"

SegmentKind = Literal["revenue", "deadhead"]
"""What a block of vehicle time was doing. "revenue" = carrying (or otherwise
earning for) a rider; "deadhead" = the vehicle occupied but not earning --
empty repositioning, pull-out, pull-in, the drive to a pickup. The caller's
adapter decides which; this module never infers it from geometry or timing."""

DataProvenance = Literal["real_public", "synthetic"]
"""Where the segments came from. "real_public" = real, publicly published
records (e.g. NYC TLC trip records); "synthetic" = generated or fixture data.
There is deliberately NO "operator" value: this repo holds no operator data,
and a label that could assert one would be the easiest possible way to imply
otherwise."""

DEFAULT_REDUCTION_FRACTION = 0.10
"""The modelled "what if this were cut by a tenth" scenario. 0.10 matches the
existing repo convention (business/ntd/agency_economics.csv's ``value_10pct_deadhead_cut``
column and business/ntd/savings_calculator.py's scenarios), so a teardown and the public
NTD calculator can be read side by side. It is a modelling assumption the
caller may override, never an achieved result."""

MAX_SEGMENT_HOURS = 48
"""A single contiguous vehicle segment longer than two days is a parsing
artefact (a date rollover, an unset end timestamp), not a vehicle. Rejected at
construction so it cannot silently dominate every bucket."""

FIXED_COST_HEDGE = (
    "Modelled envelope, not guaranteed cash: how much of this is genuinely "
    "recoverable depends on the operator's fixed-versus-variable split -- fixed "
    "costs (salaries, depreciation, admin) do not fall proportionally with "
    "vehicle-hours removed. The value at full cost below is the accounting "
    "value of the empty time at the operator's own rate, not a saving."
)

DEADHEAD_TEARDOWN_NOTE = (
    "Modelled teardown, not causal proof and not a promised saving. This "
    "localises non-revenue (empty) vehicle time to hours, days and runs from the "
    "trip-level records supplied; it shows where empty time sat, not that any of "
    "it was avoidable. Any money figure is the accounting value of that time at "
    "the operator's own cost per vehicle-hour, hedged by the fixed-versus-"
    "variable split. Every figure is re-derivable from this manifest's inputs "
    "and method."
)

_RIDER_IDENTIFIER_TOKENS = frozenset(
    {
        "rider",
        "passenger",
        "client",
        "customer",
        "patient",
        "member",
        "ssn",
        "dob",
        "phone",
        "email",
        "medicaid",
        "medicare",
        "mrn",
    }
)
"""Substrings that mark a rider-level identifier in a column name. Matched as
substrings, not whole words, because real exports write these as `rider_id`,
`PassengerNumber` and `clientRef` alike. Used only to *reject* a caller who
points the run-reference mapping at one; every column the mapping does not name
is dropped without inspection, so this list never has to be exhaustive to keep
rider data out of the output."""


class TeardownError(Exception):
    """Raised when a teardown input cannot be used honestly -- a rider
    identifier pointed at a structural column, or a segment that does not
    describe a plausible block of vehicle time."""


def _is_null(value: object) -> bool:
    """True for the null vocabulary a real export actually arrives with: None,
    and the not-equal-to-itself nulls pandas uses (NaN in a string column, NaT in
    a timestamp column -- note pandas.NaT *is* a datetime instance, so an
    isinstance check alone would let one through). pandas.NA raises on
    truthiness rather than comparing, which is caught and treated as null."""
    if value is None:
        return True
    try:
        if value != value:
            return True
    except (TypeError, ValueError):
        return True
    return False


def _reject_rider_identifier(column: str, role: str) -> None:
    lowered = column.lower()
    hits = sorted(token for token in _RIDER_IDENTIFIER_TOKENS if token in lowered)
    if hits:
        raise TeardownError(
            f"column {column!r} was pointed at the {role} mapping but names a "
            f"rider-level identifier ({', '.join(hits)}); a teardown operates on "
            "trip structure only and must never persist a rider identifier"
        )


def _round(value: float) -> float:
    """Fixed emitted precision, so a re-derivation matches digit for digit."""
    return round(value, 6)


class _Teardown(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class VehicleSegment(_Teardown):
    """One contiguous block of one vehicle's time, already classified.

    Trip structure only: when it started, when it ended, whether it was earning,
    and which run/block/vehicle it belonged to. ``extra="forbid"`` means a rider
    identifier cannot be attached to a segment at all -- construction raises.
    ``run_ref`` is the *source system's* identifier (a run, block or vehicle id
    as the operator writes it), left as a plain string for the same reason
    VehicleObservation.vehicle_ref is: it names their entity, not ours. ``None``
    means the export did not say, and is honoured as "unattributable" rather
    than filled in.
    """

    started_at: UtcDateTime
    ended_at: UtcDateTime
    kind: SegmentKind
    run_ref: str | None = Field(
        default=None,
        description="Source-system run/block/vehicle id, or None when the export omitted it.",
    )

    @model_validator(mode="after")
    def _plausible_block_of_vehicle_time(self) -> "VehicleSegment":
        if self.ended_at < self.started_at:
            raise ValueError(
                f"segment ends before it starts ({self.ended_at.isoformat()} < "
                f"{self.started_at.isoformat()})"
            )
        if self.ended_at - self.started_at > timedelta(hours=MAX_SEGMENT_HOURS):
            raise ValueError(
                f"segment spans more than {MAX_SEGMENT_HOURS}h "
                f"({self.started_at.isoformat()} -> {self.ended_at.isoformat()}); a single "
                "contiguous vehicle segment that long is a parsing artefact, not a vehicle"
            )
        return self

    @property
    def minutes(self) -> float:
        return (self.ended_at - self.started_at).total_seconds() / 60.0

    @classmethod
    def from_row(
        cls,
        row: Mapping[str, object],
        *,
        kind: SegmentKind,
        started_at_column: str,
        ended_at_column: str,
        run_ref_column: str | None = None,
    ) -> "VehicleSegment | None":
        """Build a segment from one export row, reading ONLY the named columns.

        Every other column in `row` -- including any rider identifier a real
        operator export carries -- is dropped here and never reaches the
        teardown or its output. Pointing `run_ref_column` at a rider identifier
        raises TeardownError instead: dropping it silently would leave the
        caller believing they had run-level attribution when they do not.

        Returns None when either timestamp is absent or null (including pandas'
        NaT, which *is* a datetime instance), so a caller can count unmeasurable
        rows and report them (see `unmeasured_segments`) rather than imputing
        them as zero empty time.
        """
        if run_ref_column is not None:
            _reject_rider_identifier(run_ref_column, "run_ref")

        started_at = row.get(started_at_column)
        ended_at = row.get(ended_at_column)
        for value in (started_at, ended_at):
            if _is_null(value) or not isinstance(value, datetime):
                return None

        run_ref = None
        if run_ref_column is not None:
            raw = row.get(run_ref_column)
            if not _is_null(raw) and str(raw).strip() != "":
                run_ref = str(raw).strip()

        return cls(started_at=started_at, ended_at=ended_at, kind=kind, run_ref=run_ref)


class CostBasis(_Teardown):
    """The operator's own cost per vehicle-hour, plus where that rate came from.

    `avoidable_share_low`/`high` are the fraction of that rate which actually
    falls when a vehicle-hour is removed -- the fixed-versus-variable split.
    They have NO default: nobody outside the operator's finance office knows
    it, and inventing one is how a teardown becomes a lie in front of a
    director who knows their books. Absent them, the teardown reports the
    accounting value of the empty time and explicitly no envelope.
    """

    cost_per_vehicle_hour: float = Field(gt=0)
    currency: str = "USD"
    source: str = Field(
        min_length=1,
        description="Where the rate came from, verbatim, so it can be checked (e.g. an NTD filing line).",
    )
    avoidable_share_low: float | None = Field(default=None, ge=0.0, le=1.0)
    avoidable_share_high: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _split_is_a_range_or_absent(self) -> "CostBasis":
        low, high = self.avoidable_share_low, self.avoidable_share_high
        if (low is None) != (high is None):
            raise ValueError(
                "avoidable_share_low and avoidable_share_high must be supplied "
                "together: half a fixed-versus-variable split is not a split"
            )
        if low is not None and high is not None and low > high:
            raise ValueError(f"avoidable_share_low ({low}) exceeds avoidable_share_high ({high})")
        return self


class CostEnvelope(_Teardown):
    """HOW MUCH -- and how much of that is not a promise.

    `value_at_full_cost` is arithmetic on the operator's own rate: empty hours
    times cost per vehicle-hour. It is the accounting value of the time, never
    a saving. `modelled_envelope_low`/`high` apply the modelled reduction and
    the operator's own fixed-versus-variable split, and are None (with
    `envelope_basis` saying so) when that split was not supplied.
    """

    currency: str
    cost_per_vehicle_hour: float
    cost_basis_source: str
    deadhead_hours: float
    value_at_full_cost: float
    reduction_fraction: float
    avoidable_share_low: float | None
    avoidable_share_high: float | None
    modelled_envelope_low: float | None
    modelled_envelope_high: float | None
    envelope_basis: str
    is_guaranteed_saving: bool = False
    hedge: str = FIXED_COST_HEDGE

    @field_validator("is_guaranteed_saving")
    @classmethod
    def _never_guarantee_a_saving(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "a deadhead teardown must never present a figure as a guaranteed "
                "saving: fixed costs do not fall proportionally with hours removed"
            )
        return value


class TimeBucket(_Teardown):
    """WHICH HOURS -- empty and earning minutes at one clock position.

    `day_of_week` is None on an hour-of-day-only bucket and `hour_of_day` is
    None on a day-of-week-only bucket; both are set on a joint bucket. Minutes
    are apportioned across hour boundaries, so the buckets in any one grouping
    sum exactly to the headline totals.
    """

    day_of_week: int | None = Field(default=None, ge=0, le=6, description="0=Monday .. 6=Sunday.")
    day_of_week_name: str | None = None
    hour_of_day: int | None = Field(default=None, ge=0, le=23)
    deadhead_minutes: float
    revenue_minutes: float
    deadhead_share_of_bucket: float | None
    share_of_total_deadhead: float | None


class RunContribution(_Teardown):
    """WHICH RUNS -- one run's contribution to the empty time.

    `attributable` is False exactly when the export gave no run identifier;
    that row is the honest "we cannot tell you which run this was" total, and
    is reported outside the ranking so a top-N truncation can never bury it.
    """

    run_ref: str | None
    attributable: bool
    deadhead_minutes: float
    revenue_minutes: float
    segment_count: int
    share_of_total_deadhead: float | None

    @model_validator(mode="after")
    def _attributable_iff_identified(self) -> "RunContribution":
        if self.attributable != (self.run_ref is not None):
            raise ValueError(
                "attributable must be True exactly when a run_ref exists; a run "
                "with no identifier is unattributable, never guessed onto another run"
            )
        return self


class InputRecord(_Teardown):
    """One input the teardown consumed, and where it came from, so the figure
    it feeds can be checked against the operator's own source."""

    name: str
    value: str
    source: str


class MethodStep(_Teardown):
    """One step of the arithmetic actually applied, stated precisely enough to
    be re-run by hand on the same export."""

    step: str
    detail: str


class TeardownManifest(_Teardown):
    """Pins what a teardown used and how, so it is reproducible and auditable.

    `teardown_id` is deterministic in the segments and the modelling choices:
    the same export torn down the same way pins the same id.
    """

    teardown_version: str
    replay_version: str
    teardown_id: str
    dataset_label: str
    data_provenance: DataProvenance
    run_ref_source: str
    segment_count: int
    segment_sha256: str
    observed_from: UtcDateTime | None
    observed_to: UtcDateTime | None
    unmeasured_segment_count: int
    unmeasured_reason: str | None
    inputs: tuple[InputRecord, ...]
    method: tuple[MethodStep, ...]
    note: str = DEADHEAD_TEARDOWN_NOTE
    replay_discipline_note: str = MODELLED_COMPARISON_NOTE


class DeadheadTeardown(_Teardown):
    """The structured answer to "which hours, which runs, how much".

    `causal_proof` is fixed False and raises if set: a teardown measures where
    empty time sat in records that were already produced; it says nothing about
    what caused it or what removing it would achieve.
    """

    manifest: TeardownManifest
    total_deadhead_minutes: float
    total_revenue_minutes: float
    deadhead_share_of_vehicle_time: float | None
    by_hour_of_day: tuple[TimeBucket, ...]
    by_day_of_week: tuple[TimeBucket, ...]
    by_day_of_week_and_hour: tuple[TimeBucket, ...]
    top_runs: tuple[RunContribution, ...]
    unattributable: RunContribution | None
    attributed_run_count: int = Field(
        description=(
            "How many identified runs contributed any empty time at all -- the full "
            "ranking's length before top_n truncation, so a reader can see what the "
            "top-N is a top-N of."
        )
    )
    cost: CostEnvelope | None
    is_modelled: bool = True
    causal_proof: bool = False
    interpretation: str = DEADHEAD_TEARDOWN_NOTE

    @field_validator("causal_proof")
    @classmethod
    def _never_claim_causation(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "a DeadheadTeardown must never claim causal proof (ADR-0019 / "
                "blueprint/01 boundary); causal_proof is always False"
            )
        return value


_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# (day_of_week, hour_of_day, kind) -> minutes, the atom every bucket is summed from.
_Atom = tuple[int, int, str, float]


def _hour_slices(started_at: datetime, ended_at: datetime) -> list[tuple[datetime, float]]:
    """Split a segment at hour boundaries: [(hour_start, minutes_in_that_hour)].

    A segment from 09:50 to 10:20 belongs half to 09:00 and half to 10:00; the
    alternative (charging it whole to its start hour) would put empty time in
    hours it did not happen in, which is precisely the error a teardown exists
    to fix. Zero-length segments yield nothing.
    """
    slices: list[tuple[datetime, float]] = []
    cursor = started_at
    while cursor < ended_at:
        hour_start = cursor.replace(minute=0, second=0, microsecond=0)
        slice_end = min(hour_start + timedelta(hours=1), ended_at)
        slices.append((hour_start, (slice_end - cursor).total_seconds() / 60.0))
        cursor = slice_end
    return slices


def _atoms(segments: tuple[VehicleSegment, ...]) -> list[_Atom]:
    atoms: list[_Atom] = []
    for segment in segments:
        for hour_start, minutes in _hour_slices(segment.started_at, segment.ended_at):
            atoms.append((hour_start.weekday(), hour_start.hour, segment.kind, minutes))
    return atoms


def _share(part: float, whole: float) -> float | None:
    """A share, or None when there is no denominator -- never 0/0, never a
    fabricated 0.0 standing in for "we cannot say"."""
    if whole <= 0:
        return None
    return _round(part / whole)


def _buckets(
    atoms: list[_Atom],
    key: Callable[[_Atom], tuple[int | None, int | None]],
    total_deadhead: float,
) -> tuple[TimeBucket, ...]:
    totals: dict[tuple[int | None, int | None], dict[str, float]] = defaultdict(
        lambda: {"revenue": 0.0, "deadhead": 0.0}
    )
    for atom in atoms:
        totals[key(atom)][atom[2]] += atom[3]

    buckets = []
    for (day_of_week, hour_of_day), sums in totals.items():
        deadhead, revenue = sums["deadhead"], sums["revenue"]
        buckets.append(
            TimeBucket(
                day_of_week=day_of_week,
                day_of_week_name=None if day_of_week is None else _DAY_NAMES[day_of_week],
                hour_of_day=hour_of_day,
                deadhead_minutes=_round(deadhead),
                revenue_minutes=_round(revenue),
                deadhead_share_of_bucket=_share(deadhead, deadhead + revenue),
                share_of_total_deadhead=_share(deadhead, total_deadhead),
            )
        )
    return tuple(
        sorted(
            buckets,
            key=lambda b: (
                -1 if b.day_of_week is None else b.day_of_week,
                -1 if b.hour_of_day is None else b.hour_of_day,
            ),
        )
    )


def _run_contributions(
    segments: tuple[VehicleSegment, ...], total_deadhead: float
) -> tuple[tuple[RunContribution, ...], RunContribution | None]:
    totals: dict[str | None, dict[str, float]] = defaultdict(
        lambda: {"revenue": 0.0, "deadhead": 0.0, "segments": 0.0}
    )
    for segment in segments:
        entry = totals[segment.run_ref]
        entry[segment.kind] += segment.minutes
        entry["segments"] += 1

    def contribution(run_ref: str | None, sums: dict[str, float]) -> RunContribution:
        return RunContribution(
            run_ref=run_ref,
            attributable=run_ref is not None,
            deadhead_minutes=_round(sums["deadhead"]),
            revenue_minutes=_round(sums["revenue"]),
            segment_count=int(sums["segments"]),
            share_of_total_deadhead=_share(sums["deadhead"], total_deadhead),
        )

    unattributable = (
        contribution(None, totals[None]) if None in totals else None
    )
    # Only runs that actually contributed empty time are ranked: a run with zero
    # deadhead is not a "top contributor to empty time", it is noise in the list.
    ranked = [
        contribution(run_ref, sums)
        for run_ref, sums in totals.items()
        if run_ref is not None and sums["deadhead"] > 0
    ]
    ranked.sort(key=lambda run: (-run.deadhead_minutes, run.run_ref or ""))
    return tuple(ranked), unattributable


def _cost_envelope(
    cost_basis: CostBasis, total_deadhead_minutes: float, reduction_fraction: float
) -> CostEnvelope:
    deadhead_hours = total_deadhead_minutes / 60.0
    value_at_full_cost = deadhead_hours * cost_basis.cost_per_vehicle_hour

    low = high = None
    envelope_basis = (
        "no envelope: the operator's fixed-versus-variable split was not supplied, "
        "so the recoverable fraction of this value is unknown and is not guessed"
    )
    if cost_basis.avoidable_share_low is not None and cost_basis.avoidable_share_high is not None:
        low = _round(value_at_full_cost * reduction_fraction * cost_basis.avoidable_share_low)
        high = _round(value_at_full_cost * reduction_fraction * cost_basis.avoidable_share_high)
        envelope_basis = (
            f"value_at_full_cost x reduction_fraction ({reduction_fraction}) x the "
            f"operator-supplied avoidable (variable) share "
            f"({cost_basis.avoidable_share_low}-{cost_basis.avoidable_share_high})"
        )

    return CostEnvelope(
        currency=cost_basis.currency,
        cost_per_vehicle_hour=cost_basis.cost_per_vehicle_hour,
        cost_basis_source=cost_basis.source,
        deadhead_hours=_round(deadhead_hours),
        value_at_full_cost=_round(value_at_full_cost),
        reduction_fraction=reduction_fraction,
        avoidable_share_low=cost_basis.avoidable_share_low,
        avoidable_share_high=cost_basis.avoidable_share_high,
        modelled_envelope_low=low,
        modelled_envelope_high=high,
        envelope_basis=envelope_basis,
    )


def segment_set_fingerprint(segments: tuple[VehicleSegment, ...]) -> str:
    """Order-independent checksum over a segment set -- the same segments
    fingerprint identically however they were iterated. Structure only: start,
    end, kind and run reference, the same four fields the teardown reads."""
    ordered = sorted(
        [
            [s.started_at.isoformat(), s.ended_at.isoformat(), s.kind, s.run_ref]
            for s in segments
        ],
        key=lambda row: (row[0], row[1], row[2], row[3] or ""),
    )
    return hashlib.sha256(canonical_json({"segments": ordered}).encode("utf-8")).hexdigest()


def _teardown_id(
    segment_sha256: str,
    dataset_label: str,
    data_provenance: str,
    reduction_fraction: float,
    cost_basis: CostBasis | None,
) -> str:
    payload = {
        "teardown_version": TEARDOWN_VERSION,
        "segment_sha256": segment_sha256,
        "dataset_label": dataset_label,
        "data_provenance": data_provenance,
        "reduction_fraction": reduction_fraction,
        "cost_basis": None if cost_basis is None else cost_basis.model_dump(mode="json"),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _method(run_ref_source: str, reduction_fraction: float, has_cost: bool) -> tuple[MethodStep, ...]:
    steps = [
        MethodStep(
            step="1. classify",
            detail=(
                "Each input is one contiguous block of one vehicle's time, already "
                "labelled 'revenue' (earning) or 'deadhead' (empty) by the adapter that "
                "read the export. This module never infers which is which from geometry, "
                "gaps or timing."
            ),
        ),
        MethodStep(
            step="2. bucket by clock position",
            detail=(
                "Each segment is split at hour boundaries and its minutes added to the "
                "hour(s) they actually fell in (09:50-10:20 contributes 10 minutes to "
                "hour 09 and 20 to hour 10). Hour-of-day and day-of-week are read off the "
                "segment's own timestamps, so the buckets are in whatever clock the export "
                "is written in -- if the export is local wall-clock time, these are local "
                "hours. Buckets in each grouping sum exactly to the headline totals."
            ),
        ),
        MethodStep(
            step="3. attribute to runs",
            detail=(
                f"Segments are grouped by their run reference (this dataset: {run_ref_source}) "
                "and ranked by empty minutes, descending. Segments whose run reference the "
                "export did not carry are summed into a single 'unattributable' row and "
                "reported separately -- never apportioned across, or merged into, the runs "
                "that were identified. Runs contributing zero empty minutes are not ranked."
            ),
        ),
        MethodStep(
            step="4. reconcile",
            detail=(
                "total_deadhead_minutes equals the sum of deadhead_minutes over every "
                "bucket in any one grouping, and equals the sum over top_runs plus the "
                "unattributable row (before top-N truncation). Anyone can check this "
                "against their own export."
            ),
        ),
    ]
    if has_cost:
        steps.append(
            MethodStep(
                step="5. cost",
                detail=(
                    "value_at_full_cost = (total_deadhead_minutes / 60) x the operator's own "
                    "cost per vehicle-hour. That is the accounting value of the empty time, "
                    "NOT a saving. Any modelled envelope multiplies it by the modelled "
                    f"reduction fraction ({reduction_fraction}) and by the operator's own "
                    "avoidable (variable) share of cost per hour; without that split, no "
                    "envelope is produced."
                ),
            )
        )
    return tuple(steps)


def teardown_deadhead(
    segments: Iterable[VehicleSegment],
    *,
    dataset_label: str,
    data_provenance: DataProvenance,
    run_ref_source: str,
    cost_basis: CostBasis | None = None,
    reduction_fraction: float = DEFAULT_REDUCTION_FRACTION,
    top_n_runs: int = 10,
    unmeasured_segments: int = 0,
    unmeasured_reason: str | None = None,
) -> DeadheadTeardown:
    """Localise empty vehicle time to hours, days and runs, and value it.

    `run_ref_source` names what a "run" is in this export (e.g. "block_id", or
    the closest available fleet unit) -- a ranking of runs is meaningless if the
    reader cannot tell what was ranked. `unmeasured_segments`/`unmeasured_reason`
    let a caller report rows whose empty time could not be measured at all
    (e.g. a source that publishes no on-scene timestamp) instead of letting them
    silently count as zero empty time.

    Returns a DeadheadTeardown: a *modelled* localisation, never causal proof
    and never a promised saving.
    """
    if not 0.0 <= reduction_fraction <= 1.0:
        raise TeardownError(f"reduction_fraction must be within [0, 1], got {reduction_fraction}")
    if top_n_runs < 0:
        raise TeardownError(f"top_n_runs must not be negative, got {top_n_runs}")
    if unmeasured_segments < 0:
        raise TeardownError(f"unmeasured_segments must not be negative, got {unmeasured_segments}")

    ordered = tuple(segments)

    total_deadhead = sum(s.minutes for s in ordered if s.kind == "deadhead")
    total_revenue = sum(s.minutes for s in ordered if s.kind == "revenue")

    atoms = _atoms(ordered)
    by_hour = _buckets(atoms, lambda a: (None, a[1]), total_deadhead)
    by_day = _buckets(atoms, lambda a: (a[0], None), total_deadhead)
    by_day_hour = _buckets(atoms, lambda a: (a[0], a[1]), total_deadhead)

    ranked_runs, unattributable = _run_contributions(ordered, total_deadhead)
    cost = None if cost_basis is None else _cost_envelope(cost_basis, total_deadhead, reduction_fraction)

    segment_sha256 = segment_set_fingerprint(ordered)
    observed_from = min((s.started_at for s in ordered), default=None)
    observed_to = max((s.ended_at for s in ordered), default=None)

    inputs = [
        InputRecord(name="segment_count", value=str(len(ordered)), source=dataset_label),
        InputRecord(
            name="observation_window",
            value=(
                "no segments supplied"
                if observed_from is None
                else f"{observed_from.isoformat()} .. {observed_to.isoformat()}"
            ),
            source=dataset_label,
        ),
        InputRecord(name="run_ref_source", value=run_ref_source, source=dataset_label),
        InputRecord(name="data_provenance", value=data_provenance, source=dataset_label),
        InputRecord(
            name="unmeasured_segments",
            value=str(unmeasured_segments),
            source=unmeasured_reason or dataset_label,
        ),
        InputRecord(
            name="reduction_fraction",
            value=str(reduction_fraction),
            source=(
                "caller-supplied modelling assumption; the repo default 0.10 matches "
                "business/ntd/agency_economics.csv's value_10pct_deadhead_cut convention"
            ),
        ),
    ]
    if cost_basis is not None:
        inputs.append(
            InputRecord(
                name="cost_per_vehicle_hour",
                value=f"{cost_basis.cost_per_vehicle_hour} {cost_basis.currency}",
                source=cost_basis.source,
            )
        )
        inputs.append(
            InputRecord(
                name="avoidable_share_of_cost_per_hour",
                value=(
                    "not supplied -- fixed-versus-variable split unknown"
                    if cost_basis.avoidable_share_low is None
                    else f"{cost_basis.avoidable_share_low} .. {cost_basis.avoidable_share_high}"
                ),
                source=cost_basis.source,
            )
        )

    manifest = TeardownManifest(
        teardown_version=TEARDOWN_VERSION,
        replay_version=REPLAY_VERSION,
        teardown_id=_teardown_id(
            segment_sha256, dataset_label, data_provenance, reduction_fraction, cost_basis
        ),
        dataset_label=dataset_label,
        data_provenance=data_provenance,
        run_ref_source=run_ref_source,
        segment_count=len(ordered),
        segment_sha256=segment_sha256,
        observed_from=observed_from,
        observed_to=observed_to,
        unmeasured_segment_count=unmeasured_segments,
        unmeasured_reason=unmeasured_reason,
        inputs=tuple(inputs),
        method=_method(run_ref_source, reduction_fraction, cost_basis is not None),
    )

    return DeadheadTeardown(
        manifest=manifest,
        total_deadhead_minutes=_round(total_deadhead),
        total_revenue_minutes=_round(total_revenue),
        deadhead_share_of_vehicle_time=_share(total_deadhead, total_deadhead + total_revenue),
        by_hour_of_day=by_hour,
        by_day_of_week=by_day,
        by_day_of_week_and_hour=by_day_hour,
        top_runs=ranked_runs[:top_n_runs],
        unattributable=unattributable,
        attributed_run_count=len(ranked_runs),
        cost=cost,
    )
