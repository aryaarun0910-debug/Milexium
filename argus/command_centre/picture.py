"""Composing the operating picture. Argus asks; the other layers answer.

WHAT THIS MODULE MAY DO. Call into Themis, Metis and Aletheia, read committed
files in the governed corpus, count things it was handed, and format. That is
the whole list.

WHAT IT MAY NOT DO, and the reason the module is shaped the way it is: decide
anything. There is no threshold here that decides whether a fleet is short, no
rule that turns a solver's verdict into a recommendation, no fallback that
supplies a plausible number when a layer declines to produce one. Where a layer
refuses, this module renders the refusal verbatim and moves on -- see
`_forecast_risk`, where the model registry has no champion and the page says so
instead of showing an estimate.

Every value leaves here as an `attribution.Figure`, which cannot exist without a
`Source`. The handful of declared modelling inputs the DARP projection needs are
`Source(origin="scenario")` and are listed in full on the page, because a
picture that blended them into the governed numbers would be exactly the kind of
manufactured authority this layer exists not to be.

THE SCENARIO IS THE DEMO'S. The two synthetic operator-export files, the column
map, the drift windows and the declared pickup window all come from
`argus.demo.walkthrough` by import rather than by copy, so the command centre
and the terminal walkthrough cannot drift apart in what they are about.
"""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from argus.command_centre.attribution import Figure, FigureLedger, Source
from argus.demo import walkthrough as demo

from themis.core import ModelRegistry
from metis.decide.capacity_value import (
    CAPACITY_VALUE_VERSION,
    PRIOR_IS_AN_ASSUMPTION_NOTE,
    build_ensemble,
    empty_routes,
    prior_from_observed,
)
from metis.decide.compatibility import (
    ASSIGNED_ACCESSIBILITY_NOTE,
    assign_accessibility,
    certify_insertion,
    check_equipment_feasibility,
)
from metis.decide.compatibility import _EQUIPMENT_CHECKER as EQUIPMENT_CHECKER
from metis.decide.cpsat_darp import exact_schedule
from metis.decide.darp_ir import DarpInstance, DarpNode, DarpRoute, DarpSolution, DarpVisit
from metis.forecast.features import feature_names_for
from metis.forecast.runtime import ForecastRuntime, NoChampionError
from metis.forecast.serve_drift import assess_drift, derive_reference_from_rows

# --------------------------------------------------------------------------
# DECLARED SCENARIO INPUTS.
#
# Every one of these is a modelling choice with no authority behind it. They
# are gathered here, rather than buried at their point of use, because the page
# lists them in full and a reader is entitled to see the complete set. Two of
# them are imported from the walkthrough rather than restated, so there is one
# place they can be changed.
# --------------------------------------------------------------------------

#: How long after the scheduled pickup a rider may still be collected. The
#: walkthrough already declares this for its late booking and labels it
#: SYNTHETIC; the DARP projection applies the SAME window to every request,
#: because a projection that gave the late booking a wider window than the
#: trips it competes with would be rigged in its favour.
PICKUP_WINDOW_MINUTES = 20.0

#: Longest ride the projection admits, likewise the walkthrough's own figure for
#: the late booking (a 35-minute nominal ride with a 75-minute drop-off bound).
MAX_RIDE_MINUTES = 75.0

#: Seats per vehicle in the DARP projection. The operator export carries no
#: vehicle configuration at all -- not a seat count, not a wheelchair position
#: count, not a make or model.
VEHICLE_SEATS = 3

#: A deployed wheelchair station's footprint against the shared floor, in
#: seat-equivalents, and how many stations an accessible vehicle carries. Metis
#: owns the meaning of both (`compatibility.AccessibilityProfile`); the values
#: here are declared because the export cannot supply them.
WHEELCHAIR_POSITIONS = 1
WHEELCHAIR_FOOTPRINT = 2

#: Share of requests labelled as needing a wheelchair-accessible vehicle, and
#: how many of the three vehicles are accessible. ASSIGNED, not observed -- see
#: `compatibility.ASSIGNED_ACCESSIBILITY_NOTE`, which travels with every figure
#: that depends on it.
WHEELCHAIR_SHARE = 0.35
ACCESSIBLE_VEHICLES = 2

#: The scenario draw. 4 independent draws of 16 hypothetical future trips each:
#: enough that `CapacityValue.stderr` is a real error bar rather than zero by
#: construction, and cheap enough to run at page-build time.
CAPACITY_DRAWS = 4
CAPACITY_SCENARIOS = 16
CAPACITY_SEED = 20260726

#: Largest accessibility-assignment seed the search below will try.
_MAX_ASSIGNMENT_SEED = 64

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = _REPO_ROOT / "aletheia" / "artifacts" / "command-centre"

SYNTHETIC_BANNER = (
    "SYNTHETIC SCENARIO. No operator has ever sent this repository an export. "
    "Every operational number on this page is computed from two synthetic files "
    "that say so in their own filenames, and is evidence about those files and "
    "nothing else. Milexium has zero customers, zero pilots and zero operator "
    "data; nothing here is Validated."
)

ARGUS_PROHIBITION = (
    "Argus must never invent a fact, constraint, reason or recommendation. "
    "Argus renders authority; it does not manufacture authority."
)


# --------------------------------------------------------------------------
# the shapes the renderer consumes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioInput:
    name: str
    value: str
    why: str


@dataclass(frozen=True)
class Refusal:
    """Something the platform declined to produce, and why that is the product."""

    key: str
    headline: str
    refused: str
    why: str
    source: Source


@dataclass(frozen=True)
class Option:
    """One candidate placement for the request under decision.

    `binding` is the constraint that actually bound, taken from the authority
    that bound it -- an enum reason code from the solver, or a checker's own
    detail string. It is never prose written here.
    """

    label: str
    authority: str
    feasible: bool
    binding: str
    detail: str
    recommended: bool = False


@dataclass(frozen=True)
class HourBand:
    hour: int
    pickups: int
    wheelchair_pickups: int
    vehicles_in_service: int
    accessible_in_service: int
    accessible_positions: int

    @property
    def accessible_short(self) -> bool:
        return self.wheelchair_pickups > self.accessible_positions


@dataclass
class OperatingPicture:
    """Everything the page shows, with every value already attributed."""

    generated_at: datetime
    service_day: str
    ledger: FigureLedger
    #: One source per table on the page. Tables carry numbers too, and a number
    #: without its source is the thing this artifact exists not to show.
    table_sources: dict[str, Source] = field(default_factory=dict)
    scenario_inputs: list[ScenarioInput] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)
    options: list[Option] = field(default_factory=list)
    hour_bands: list[HourBand] = field(default_factory=list)
    vehicles: list[dict] = field(default_factory=list)
    requests: list[dict] = field(default_factory=list)
    ledger_events: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    drift_features: list[dict] = field(default_factory=list)
    capacity_rows: list[dict] = field(default_factory=list)
    runtime_seconds: float = 0.0

    def figure(self, key: str) -> Figure:
        for candidate in self.ledger.figures:
            if candidate.key == key:
                return candidate
        raise KeyError(key)

    def has(self, key: str) -> bool:
        return any(candidate.key == key for candidate in self.ledger.figures)

    def to_record(self) -> dict:
        return {
            "artifact": "argus_command_centre",
            "generated_utc": self.generated_at.isoformat(),
            "generator": "argus/command_centre/picture.py",
            "status": "Demonstrated. Not Validated.",
            "prohibition": ARGUS_PROHIBITION,
            "synthetic_banner": SYNTHETIC_BANNER,
            "service_day": self.service_day,
            "runtime_seconds": round(self.runtime_seconds, 3),
            "figures": self.ledger.to_records(),
            "figures_by_origin": self.ledger.by_origin(),
            "table_sources": {
                key: source.to_record() for key, source in self.table_sources.items()
            },
            "scenario_inputs": [
                {"name": s.name, "value": s.value, "why": s.why} for s in self.scenario_inputs
            ],
            "refusals": [
                {
                    "key": r.key,
                    "headline": r.headline,
                    "refused": r.refused,
                    "why": r.why,
                    "source": r.source.to_record(),
                }
                for r in self.refusals
            ],
            "options": [
                {
                    "label": o.label,
                    "authority": o.authority,
                    "feasible": o.feasible,
                    "binding": o.binding,
                    "detail": o.detail,
                    "recommended": o.recommended,
                }
                for o in self.options
            ],
            "hour_bands": [
                {
                    "hour": b.hour,
                    "pickups": b.pickups,
                    "wheelchair_pickups": b.wheelchair_pickups,
                    "vehicles_in_service": b.vehicles_in_service,
                    "accessible_in_service": b.accessible_in_service,
                    "accessible_positions": b.accessible_positions,
                    "accessible_short": b.accessible_short,
                }
                for b in self.hour_bands
            ],
            "vehicles": self.vehicles,
            "requests": self.requests,
            "capacity_rows": self.capacity_rows,
            "drift_features": self.drift_features,
            "ledger_events": self.ledger_events,
            "limitations": self.limitations,
            "findings": self.findings,
        }


# --------------------------------------------------------------------------
# sources used in more than one place
# --------------------------------------------------------------------------


def _corpus_source(path: Path, detail: str) -> Source:
    return Source(
        origin="corpus",
        citation=demo._rel(path),
        detail=detail,
        sha256=demo._sha256(path) if path.exists() else None,
    )


def _scenario_source(name: str, detail: str) -> Source:
    return Source(
        origin="scenario",
        citation=f"argus/command_centre/picture.py::{name}",
        detail=detail,
    )


def _declared_accessibility() -> Source:
    return _scenario_source(
        "WHEELCHAIR_SHARE, ACCESSIBLE_VEHICLES, WHEELCHAIR_POSITIONS, WHEELCHAIR_FOOTPRINT",
        f"{WHEELCHAIR_SHARE:.0%} of requests assigned as wheelchair users, "
        f"{ACCESSIBLE_VEHICLES} accessible vehicles, {WHEELCHAIR_POSITIONS} position each, "
        f"{WHEELCHAIR_FOOTPRINT} seat-equivalents per deployed station. The export carries "
        "no accessibility field of any kind",
    )


def _declared_projection() -> Source:
    return _scenario_source(
        "PICKUP_WINDOW_MINUTES, MAX_RIDE_MINUTES, VEHICLE_SEATS, zone layout",
        f"{PICKUP_WINDOW_MINUTES:.0f}-minute pickup window, {MAX_RIDE_MINUTES:.0f}-minute "
        f"maximum ride, {VEHICLE_SEATS} seats, and a regular-polygon zone layout scaled to "
        "the export's own mean trip duration. None of these is carried by the export",
    )


_QUIET = lambda *args, **kwargs: None  # noqa: E731 -- the walkthrough's own print hook


def _artifact_resolver_that_is_never_reached(model_version):  # pragma: no cover
    """The runtime resolves a champion before it ever resolves an artifact, and
    there is no champion. Raising here rather than returning a path means a
    future checkout that DOES register one fails loudly instead of quietly
    serving a forecast this page is not built to display."""
    raise RuntimeError(
        f"the command centre has no artifact resolver; it did not expect to reach "
        f"model {model_version.model_version_id}"
    )


# --------------------------------------------------------------------------
# the build
# --------------------------------------------------------------------------


def build_operating_picture(*, include_real_drift: bool = True) -> OperatingPicture:
    """Drive the layers once and return everything the page renders.

    `include_real_drift` exists only as a runtime lever: the serve-time drift
    section reads a 571k-row committed panel and is the single most expensive
    thing on the page. Turning it off REMOVES the section rather than replacing
    it with anything, and the page says which sections it is missing.
    """
    started = time.perf_counter()
    picture = OperatingPicture(
        generated_at=datetime.now(timezone.utc),
        service_day="",
        ledger=FigureLedger(),
    )

    client, adapter_ts = demo._new_client()
    result = demo.WalkthroughResult()
    demo._step_1_pii(_QUIET, result, adapter_ts)
    summary, raw_rows, accepted_rows = demo._step_2_intake(_QUIET, result, client, adapter_ts)
    records = demo._step_3_canonical(_QUIET, result, summary, raw_rows)
    decision = demo._step_4_decide(_QUIET, result, client, accepted_rows)
    teardown, _segments = demo._step_5_teardown(_QUIET, result, accepted_rows)

    pairs = _pair_records_to_rows(records, accepted_rows)
    picture.service_day = min(
        rec.request.times.scheduled_pickup_at for rec, _ in pairs
    ).date().isoformat()

    _current_state(picture, result, summary, records, pairs, accepted_rows)
    projection = _build_projection(picture, pairs, accepted_rows)
    _accessible_capacity(picture, projection)
    _forecast_risk(picture)
    _the_decision(picture, result, decision, projection)
    _future_capacity_cost(picture, projection)
    if include_real_drift:
        _serve_time_drift(picture)
    else:
        picture.limitations.append(
            "The serve-time drift section was skipped (include_real_drift=False), so this "
            "page carries no measured evidence about the exchangeability the conformal "
            "interval assumes. Absence of a drift section is not absence of drift."
        )
    _teardown_outcome(picture, result, teardown)
    _authorisation(picture, client, decision)
    _outcome_against_expectation(picture, result, pairs)
    _scenario_disclosure(picture, projection)

    picture.runtime_seconds = time.perf_counter() - started
    picture.ledger.emit(
        "runtime_seconds",
        "Page build time",
        f"{picture.runtime_seconds:.1f} s",
        Source(
            origin="argus",
            citation="argus/command_centre/picture.py::build_operating_picture",
            detail=(
                "wall time of this build, measured with time.perf_counter around the "
                "composition; excludes interpreter start and module import"
            ),
        ),
        note=(
            "One machine, one run. ADR-0056 recorded a 2.8x thermal swing and ADR-0061 "
            "saw 4.2x between two runs of the same benchmark, so treat this as "
            "indicative rather than a specification."
        ),
    )
    return picture


# --------------------------------------------------------------------------
# 1. current state
# --------------------------------------------------------------------------


def _pair_records_to_rows(records, accepted_rows) -> list[tuple[object, dict]]:
    """Line canonical records up with the export rows they came from.

    The adapter emits one record per accepted row in row order, but nothing in
    the public API promises that, and a silent mis-pairing would attach the
    wrong trip reference to every figure on the page. So the correspondence is
    CHECKED on two independently-carried fields and raises if it does not hold,
    rather than being assumed.
    """
    if len(records) != len(accepted_rows):
        raise RuntimeError(
            f"{len(records)} canonical records against {len(accepted_rows)} accepted rows: "
            "the command centre cannot attribute a figure to a trip it cannot identify"
        )
    for record, row in zip(records, accepted_rows):
        if record.outcome.vehicle_ref != row["VehicleNo"].strip():
            raise RuntimeError(
                f"record/row pairing broke at {row['BookingRef']}: canonical vehicle "
                f"{record.outcome.vehicle_ref!r} against export {row['VehicleNo']!r}"
            )
    return list(zip(records, accepted_rows))


def _current_state(picture, result, summary, records, pairs, accepted_rows) -> None:
    ledger = picture.ledger
    export = _corpus_source(
        demo.EXPORT_PART2,
        "the operator's corrected re-send; SYNTHETIC, and the filename says so",
    )
    themis_intake = Source(
        origin="themis",
        citation="themis.connect.OperatorExportAdapter via argus.sdk.MilexiumClient.ingest",
        detail="the intake verdict for this send: rows imported, rows quarantined, repairs recorded",
    )
    themis_canonical = Source(
        origin="themis",
        citation="themis.connect IngestSummary.records (canonical ServiceRequest + Outcome)",
        detail="the canonical records the accepted rows became",
    )

    ledger.emit(
        "export_rows",
        "Rows in the export",
        str(result.part2_rows),
        export,
        value=result.part2_rows,
    )
    ledger.emit(
        "requests_in_play",
        "Requests in play",
        str(result.canonical_requests),
        themis_canonical,
        note="One canonical ServiceRequest + Outcome pair per imported row.",
        value=result.canonical_requests,
    )
    ledger.emit(
        "quarantined",
        "Rows quarantined, not imported",
        str(result.part2_quarantined),
        themis_intake,
        note=(
            "Conservation holds: imported + quarantined equals rows submitted "
            f"({result.conservation_holds}). No row is silently discarded."
        ),
        value=result.part2_quarantined,
    )
    ledger.emit(
        "denied_requests",
        "Requests the operator recorded as DENIED",
        str(result.canonical_denied),
        themis_canonical,
        note="A denial is a record, not an absence -- which is why it can be counted at all.",
        value=result.canonical_denied,
    )
    ledger.emit(
        "no_show_requests",
        "Requests recorded as NO SHOW",
        str(result.canonical_no_show),
        themis_canonical,
        value=result.canonical_no_show,
    )
    ledger.emit(
        "repair_records",
        "Repairs recorded against imported rows",
        str(result.semantic_loss_records),
        themis_intake,
        note=(
            "Every repair names its rule, the original value and the repaired value, so a "
            "reviewer can undo any of them. Rules fired: "
            + ", ".join(sorted(result.part2_repair_rules))
        ),
        value=result.semantic_loss_records,
    )

    shifts = demo._vehicle_shifts(accepted_rows)
    shift_source = Source(
        origin="themis",
        citation="argus.demo.walkthrough._vehicle_shifts over canonical Outcome.vehicle_ref",
        detail=(
            "each vehicle's shift envelope taken from its own observed first and last "
            "activity in the export, padded five minutes"
        ),
    )
    ledger.emit(
        "vehicles_in_play",
        "Vehicles in play",
        str(len(shifts)),
        shift_source,
        note=(
            "The export carries no pull-out or pull-in time, so each envelope is a FLOOR "
            "on the real shift, not the shift."
        ),
        value=len(shifts),
    )
    runs = sorted({rec.outcome.run_ref for rec, _ in pairs if rec.outcome.run_ref})
    unrun = sum(1 for rec, _ in pairs if not rec.outcome.run_ref)
    ledger.emit(
        "runs_in_play",
        "Named runs",
        str(len(runs)),
        themis_canonical,
        note=(
            f"{unrun} imported trip(s) name no run at all. Their empty time is measurable "
            "and is reported separately rather than being attached to a run that did not "
            "incur it."
        ),
        value=len(runs),
    )

    picture.table_sources["vehicles"] = shift_source
    picture.table_sources["requests"] = themis_canonical
    for label, (start, end) in shifts:
        assigned = [rec for rec, _ in pairs if rec.outcome.vehicle_ref == label]
        picture.vehicles.append(
            {
                "label": label,
                "shift_start": start.strftime("%H:%M"),
                "shift_end": end.strftime("%H:%M"),
                "trips": len(assigned),
                "runs": sorted({rec.outcome.run_ref for rec in assigned if rec.outcome.run_ref}),
            }
        )
    for record, row in pairs:
        picture.requests.append(
            {
                "ref": row["BookingRef"].strip(),
                "vehicle": record.outcome.vehicle_ref,
                "run": record.outcome.run_ref or "",
                "pickup_zone": record.request.pickup_zone,
                "dropoff_zone": record.request.dropoff_zone,
                "scheduled": record.request.times.scheduled_pickup_at.strftime("%H:%M"),
                "status": record.request.status.value,
                "on_time": record.outcome.on_time,
            }
        )

    picture.refusals.append(
        Refusal(
            key="pii",
            headline="The first send imported nothing",
            refused=(
                f"{result.part1_rows} of {result.part1_rows} rows refused on PII grounds, "
                f"including the row whose rider-name cell was blank. Rider names and phone "
                f"numbers were redacted out of the quarantine records themselves "
                f"(values leaked: {result.part1_redaction_leaked})."
            ),
            why=(
                "The check runs before parsing, before repair, before every other "
                "validation. The presence of the COLUMN means the export shape carries "
                "personal data, and an all-blank column in a sample would hide a populated "
                "one in the full extract."
            ),
            source=Source(
                origin="themis",
                citation="themis.connect.operator_export (PII gate, REDACTION_MARKER)",
                detail="quarantine verdicts and redaction check computed on this run's records",
            ),
        )
    )
    picture.refusals.append(
        Refusal(
            key="ambiguous_date",
            headline="The same column, two dates, two different verdicts",
            refused=(
                "An ambiguous day/month date was quarantined "
                f"(quarantined={result.ambiguous_date_quarantined}) while its unambiguous "
                f"twin was repaired with the rule recorded "
                f"(repaired={result.unambiguous_date_repaired})."
            ),
            why=(
                "There is no thirteenth month, so one reading exists and is repaired. The "
                "other has two and nothing in the file says which. Picking one silently "
                "would move a trip a month and no downstream number would look wrong."
            ),
            source=Source(
                origin="themis",
                citation="themis.connect.repair_rule_of / quarantine reasons",
                detail="the two verdicts this run produced on the same column",
            ),
        )
    )


# --------------------------------------------------------------------------
# 2. the DARP projection the capacity lens needs
# --------------------------------------------------------------------------


@dataclass
class Projection:
    """The scenario, expressed in the vocabulary `metis.decide` speaks.

    Kept as an explicit object so the page can say which of its inputs were
    declared here and which came off a canonical record.
    """

    instance: DarpInstance
    profile: object
    routes: list[list[int]]
    vehicle_labels: list[str]
    request_refs: list[str]
    request_records: list[object]
    late_request: int
    assignment_seed: int
    zone_coords: dict[str, tuple[float, float]]
    mean_observed_minutes: float


def _build_projection(picture, pairs, accepted_rows) -> Projection:
    """Project the canonical day onto a dial-a-ride instance.

    The times, zones, vehicles and assignments are canonical. The GEOMETRY is
    not: `DarpInstance` is a Euclidean instance whose distances are travel
    times, and the export carries zone identifiers with no coordinates
    anywhere in this repository. So the zones are laid out on a regular polygon
    -- a declared shape -- scaled by one rule taken from the data itself: the
    mean pairwise travel time equals the mean observed trip duration in the
    export. The shape is an assumption, the scale is a measurement, and the
    page says which is which.
    """
    ledger = picture.ledger
    scheduled = [
        (record, row)
        for record, row in pairs
        if record.request.status.value != "no_show"
    ]
    performed = [(r, row) for r, row in pairs if row["ActualPU"] and row["ActualDO"]]
    durations = [
        (demo._utc(row["ActualDO"]) - demo._utc(row["ActualPU"])).total_seconds() / 60.0
        for _, row in performed
    ]
    mean_minutes = statistics.fmean(durations)

    zones = sorted(
        {record.request.pickup_zone for record, _ in pairs}
        | {record.request.dropoff_zone for record, _ in pairs}
    )
    k = len(zones)
    unit = [(math.cos(2 * math.pi * i / k), math.sin(2 * math.pi * i / k)) for i in range(k)]
    unit_pairs = [(i, j) for i in range(k) for j in range(i + 1, k)]
    scale = mean_minutes / statistics.fmean(math.dist(unit[i], unit[j]) for i, j in unit_pairs)
    coords = {zone: (unit[i][0] * scale, unit[i][1] * scale) for i, zone in enumerate(zones)}

    ledger.emit(
        "mean_trip_minutes",
        "Mean observed trip duration",
        f"{mean_minutes:.1f} min",
        Source(
            origin="corpus",
            citation=demo._rel(demo.EXPORT_PART2) + " (ActualPU, ActualDO)",
            detail=(
                f"mean over the {len(durations)} performed trips in the export. Read "
                "OUTSIDE the canonical path -- see the finding below"
            ),
            sha256=demo._sha256(demo.EXPORT_PART2),
        ),
        note="The scale of the projected zone layout is set to reproduce this figure.",
        value=round(mean_minutes, 4),
    )
    picture.findings.append(
        "Milexium's own canonical records cannot drive Milexium's own travel-time "
        "geometry. The canonical intake column list carries no trip END time and neither "
        "does Outcome, so the mean trip duration above is read directly from the export's "
        "unmapped ActualDO column, outside the canonical path. The walkthrough hit the "
        "same wall for its deadhead teardown; this is the second surface to need it."
    )

    ordered = [rec for rec, _ in scheduled if rec.request.status.value != "denied"]
    ordered_rows = [row for rec, row in scheduled if rec.request.status.value != "denied"]
    denied = [(rec, row) for rec, row in scheduled if rec.request.status.value == "denied"]
    if len(denied) != 1:
        raise RuntimeError(
            f"expected exactly one denied request to pose the decision about; got {len(denied)}"
        )
    ordered.append(denied[0][0])
    ordered_rows.append(denied[0][1])

    day_start = min(r.request.times.scheduled_pickup_at for r in ordered).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    minutes = lambda when: (when - day_start).total_seconds() / 60.0  # noqa: E731

    shifts = demo._vehicle_shifts(accepted_rows)
    horizon_lo = min(minutes(start) for _, (start, _) in shifts) - 30.0
    horizon_hi = max(minutes(end) for _, (_, end) in shifts) + 30.0

    n = len(ordered)
    nodes = [DarpNode(0, 0.0, 0.0, 0.0, 0, horizon_lo, horizon_hi)]
    for index, record in enumerate(ordered, start=1):
        x, y = coords[record.request.pickup_zone]
        start = minutes(record.request.times.scheduled_pickup_at)
        nodes.append(DarpNode(index, x, y, 0.0, 1, start, start + PICKUP_WINDOW_MINUTES))
    for index, record in enumerate(ordered, start=1):
        x, y = coords[record.request.dropoff_zone]
        start = minutes(record.request.times.scheduled_pickup_at)
        nodes.append(DarpNode(n + index, x, y, 0.0, -1, start, start + MAX_RIDE_MINUTES))
    nodes.append(DarpNode(2 * n + 1, 0.0, 0.0, 0.0, 0, horizon_lo, horizon_hi))

    instance = DarpInstance.build(
        name=f"milexium-command-centre-{picture.service_day}",
        num_vehicles=len(shifts),
        num_requests=n,
        max_route_duration=horizon_hi - horizon_lo,
        vehicle_capacity=VEHICLE_SEATS,
        max_ride_time=MAX_RIDE_MINUTES,
        nodes=nodes,
    )

    labels = [label for label, _ in shifts]
    routes: list[list[int]] = []
    for label in labels:
        ids = [
            index
            for index, record in enumerate(ordered, start=1)
            if record.outcome.vehicle_ref == label
            and record.request.status.value != "denied"
        ]
        sequence = [instance.depot_start]
        for request_id in ids:
            sequence.append(instance.pickup_index(request_id))
            sequence.append(instance.dropoff_index(request_id))
        sequence.append(instance.depot_end)
        routes.append(sequence)

    profile, seed = _assign_accessibility_that_the_day_survives(instance, routes)

    ledger.emit(
        "projected_requests",
        "Requests in the capacity projection",
        str(n),
        Source(
            origin="themis",
            citation="canonical ServiceRequest (no-shows excluded)",
            detail=(
                "every scheduled request on the day, including the one the operator "
                "denied; a no-show is not a request the fleet had to fit"
            ),
        ),
        value=n,
    )
    assign_source = Source(
        origin="metis",
        citation="metis.decide.compatibility.assign_accessibility",
        detail=f"exact-share assignment at seed {seed}, run this build",
    )
    ledger.add(
        Figure.derived_from(
            "wheelchair_requests",
            "Requests ASSIGNED as needing a wheelchair-accessible vehicle",
            f"{len(profile.wheelchair_requests)} of {n}",
            [assign_source, _declared_accessibility()],
            detail=(
                "Metis assigned the labels; the share and the seed rule were declared here. "
                "The export carries no accessibility field of any kind"
            ),
            note=ASSIGNED_ACCESSIBILITY_NOTE,
            value=sorted(profile.wheelchair_requests),
        )
    )
    ledger.add(
        Figure.derived_from(
            "accessible_vehicles",
            "Vehicles ASSIGNED as wheelchair-accessible",
            f"{len(profile.accessible_vehicles)} of {len(labels)}",
            [assign_source, _declared_accessibility()],
            detail="which vehicles carry a wheelchair position, and how many",
            note=ASSIGNED_ACCESSIBILITY_NOTE,
            value=sorted(profile.accessible_vehicles),
        )
    )
    ledger.add(
        Figure.derived_from(
            "equipment_layer_can_bind",
            "Can the equipment layer refuse anything the seat count would allow?",
            str(profile.can_bind(instance)),
            [
                Source(
                    origin="metis",
                    citation="metis.decide.compatibility.AccessibilityProfile.can_bind",
                    detail=(
                        "Metis's own guard against drawing conclusions from a "
                        "configuration in which the constraint under study is inert"
                    ),
                ),
                _declared_accessibility(),
                _declared_projection(),
            ],
            detail=(
                "Metis answers the question; the configuration it answers about is the "
                "declared one"
            ),
            note=(
                "False here would mean every accessible-capacity statement below was "
                "vacuous. It is checked rather than assumed because this repository has "
                "already shipped one constraint that was inert on every fixture that "
                "tested it (ADR-0073)."
            ),
            value=profile.can_bind(instance),
        )
    )

    return Projection(
        instance=instance,
        profile=profile,
        routes=routes,
        vehicle_labels=labels,
        request_refs=[row["BookingRef"].strip() for row in ordered_rows],
        request_records=ordered,
        late_request=n,
        assignment_seed=seed,
        zone_coords=coords,
        mean_observed_minutes=mean_minutes,
    )


def _committed_solution(instance: DarpInstance, routes) -> DarpSolution | None:
    scheduled_routes = []
    for vehicle, sequence in enumerate(routes):
        begins = exact_schedule(instance, sequence)
        if begins is None:
            return None
        scheduled_routes.append(
            DarpRoute(
                vehicle=vehicle,
                visits=tuple(
                    DarpVisit(node_index=node, begin_service=begin)
                    for node, begin in zip(sequence, begins)
                ),
            )
        )
    served = tuple(
        instance.request_of(node)
        for sequence in routes
        for node in sequence
        if instance.is_pickup(node)
    )
    return DarpSolution(
        instance_name=instance.name,
        num_requests=instance.num_requests,
        routes=tuple(scheduled_routes),
        status="feasible",
        objective=None,
        served_requests=tuple(sorted(served)),
        solver_name="operator-export (already committed)",
        solver_version="n/a",
        seed=0,
    )


def _assign_accessibility_that_the_day_survives(instance, routes):
    """Pick the accessibility-assignment seed by a stated rule, not by result.

    The rule: the SMALLEST seed for which the operator's own already-completed
    day is itself equipment-feasible. A picture that opened by declaring the
    operator's finished work impossible would be reporting an artefact of
    labels Milexium invented, not anything about the day.

    The rule deliberately says nothing about the outcome. It does not require
    the denied trip to be a wheelchair rider, does not require any vehicle to
    refuse, and does not look at a single foreclosure number -- whatever falls
    out of the first qualifying seed is what the page reports. Seed 0 qualifies
    on this scenario; the search exists so a future change to the fixture fails
    loudly rather than silently reporting violations as findings.
    """
    solution = _committed_solution(instance, routes)
    if solution is None:
        raise RuntimeError(
            "the committed routes admit no exact schedule under the declared pickup "
            "window -- the projection cannot represent the day that actually happened"
        )
    for seed in range(_MAX_ASSIGNMENT_SEED):
        profile = assign_accessibility(
            instance,
            seed=seed,
            wheelchair_share=WHEELCHAIR_SHARE,
            accessible_vehicles=ACCESSIBLE_VEHICLES,
            wheelchair_positions=WHEELCHAIR_POSITIONS,
            wheelchair_footprint=WHEELCHAIR_FOOTPRINT,
        )
        violations = check_equipment_feasibility(instance, profile, solution)
        if not violations:
            return profile, seed
    raise RuntimeError(
        f"no accessibility assignment in {_MAX_ASSIGNMENT_SEED} seeds leaves the "
        "operator's completed day equipment-feasible; the page will not report "
        "violations it manufactured as if they were the operator's"
    )


# --------------------------------------------------------------------------
# 3. scarce accessible capacity
# --------------------------------------------------------------------------


def _accessible_capacity(picture, projection: Projection) -> None:
    ledger = picture.ledger
    instance, profile = projection.instance, projection.profile

    positions = sum(profile.positions_on(v) for v in range(instance.num_vehicles))
    ledger.add(
        Figure.derived_from(
            "wheelchair_positions_total",
            "Wheelchair positions in the fleet",
            str(positions),
            [
                Source(
                    origin="metis",
                    citation="metis.decide.compatibility.AccessibilityProfile.positions_on",
                    detail="summed over the fleet at the assigned profile",
                ),
                _declared_accessibility(),
            ],
            detail="a count over a declared fleet configuration",
            note=(
                "A wheelchair position is not a seat and the two are not fungible. A "
                f"deployed station consumes {WHEELCHAIR_FOOTPRINT} seat-equivalents of "
                f"shared floor against a {VEHICLE_SEATS}-seat vehicle, so the floor can "
                "refuse a group the seat count would allow."
            ),
            value=positions,
        )
    )

    hours: dict[int, dict] = {}
    wheelchair_ids = set(profile.wheelchair_requests)
    for index, record in enumerate(projection.request_records, start=1):
        hour = record.request.times.scheduled_pickup_at.hour
        bucket = hours.setdefault(hour, {"pickups": 0, "wheelchair": 0})
        bucket["pickups"] += 1
        if index in wheelchair_ids:
            bucket["wheelchair"] += 1

    shift_by_label = {v["label"]: (v["shift_start"], v["shift_end"]) for v in picture.vehicles}
    for hour in sorted(hours):
        in_service = 0
        accessible = 0
        for vehicle_index, label in enumerate(projection.vehicle_labels):
            start, end = shift_by_label[label]
            if int(start[:2]) <= hour <= int(end[:2]):
                in_service += 1
                if profile.is_accessible(vehicle_index):
                    accessible += 1
        picture.hour_bands.append(
            HourBand(
                hour=hour,
                pickups=hours[hour]["pickups"],
                wheelchair_pickups=hours[hour]["wheelchair"],
                vehicles_in_service=in_service,
                accessible_in_service=accessible,
                accessible_positions=accessible * WHEELCHAIR_POSITIONS,
            )
        )

    hour_band_source = Source(
        origin="metis",
        citation=(
            "metis.decide.compatibility.AccessibilityProfile "
            "+ canonical scheduled_pickup_at + observed shift envelopes"
        ),
        detail=(
            "per hour: assigned wheelchair pickups against wheelchair positions on the "
            "vehicles whose shift envelope covers that hour"
        ),
    )
    picture.table_sources["hour_bands"] = Figure.derived_from(
        "hour_bands_table",
        "Hour bands",
        "table",
        [hour_band_source, _declared_accessibility()],
        detail=(
            "hourly counts of governed records against a declared fleet configuration"
        ),
    ).source

    short = [band.hour for band in picture.hour_bands if band.accessible_short]
    ledger.add(
        Figure.derived_from(
            "hours_accessible_short",
            "Hours where assigned wheelchair demand exceeds accessible positions in service",
            (", ".join(f"{h:02d}:00" for h in short) if short else "none"),
            [hour_band_source, _declared_accessibility()],
            detail=(
                "the hours at which the count above crosses; both the demand labels and "
                "the position count are declared"
            ),
            note=(
                "A count of simultaneous demand against simultaneous positions, at hour "
                "resolution. It is not a feasibility verdict -- two pickups in the same "
                "hour may or may not overlap in the vehicle. The feasibility question is "
                "answered by the checkers below, not here."
            ),
            value=short,
        )
    )


# --------------------------------------------------------------------------
# 4. forecast risk -- and the refusal that stands in its place
# --------------------------------------------------------------------------


def _forecast_risk(picture) -> None:
    """Ask Metis for a demand forecast for the upcoming window.

    On a fresh clone there is no champion model to ask: the trained boosters are
    gitignored local artifacts (DATA_STORAGE.md) and nothing has been promoted.
    The runtime is asked ANYWAY, on every build, and whatever it says is what the
    page shows. Argus does not carry a fallback estimate,
    because a fallback estimate is precisely the invented fact this layer is
    forbidden to produce.
    """
    ledger = picture.ledger
    runtime = ForecastRuntime(
        ModelRegistry(),
        artifact_resolver=_artifact_resolver_that_is_never_reached,
    )
    horizon_start = datetime.fromisoformat(f"{picture.service_day}T00:00:00+00:00")
    refusal_detail = ""
    served = None
    try:
        # A real call to the real runtime. Model resolution happens before the
        # feature row is examined, so the refusal below is Metis's own and not a
        # pre-emptive guess by this module about what Metis would have said.
        served = runtime.forecast(
            "forecast.demand",
            {},
            horizon_start=horizon_start,
            horizon_end=horizon_start.replace(hour=23, minute=59),
            issued_at=picture.generated_at,
        )
    except NoChampionError as refused:
        refusal_detail = str(refused)
    if served is not None:  # pragma: no cover -- no champion exists on any checkout yet
        raise RuntimeError(
            "a champion demand model resolved unexpectedly; the forecast-risk section "
            "renders a refusal it is no longer entitled to render"
        )

    schema = feature_names_for("zone_hour_demand_v1")
    ledger.emit(
        "forecast_available",
        "Demand forecast for the upcoming window",
        "NONE — the model registry has no champion to serve",
        Source(
            origin="metis",
            citation="metis.forecast.runtime.ForecastRuntime + themis.core.ModelRegistry",
            detail=(
                "the registry was asked for the champion model for task 'forecast.demand' "
                f"and refused: {refusal_detail}"
            ),
        ),
        note=(
            "Argus shows no number here. The forecasting stack exists and is benchmarked "
            "(aletheia/benchmarks/quality/forecast_leaderboard.json), but its trained "
            "artifacts are local-only and no champion is registered against this synthetic "
            "tenant. A plausible figure in this box would be an invented one, so the box "
            "stays empty and says why."
        ),
        value=False,
    )
    ledger.emit(
        "forecast_feature_schema",
        "Feature schema a forecast would be served on",
        f"zone_hour_demand_v1 ({len(schema)} features)",
        Source(
            origin="metis",
            citation="metis.forecast.features.feature_names_for('zone_hour_demand_v1')",
            detail="the feature contract the demand model is registered against",
        ),
        value=len(schema),
    )
    picture.refusals.append(
        Refusal(
            key="no_forecast",
            headline="No demand forecast is shown, and none is substituted",
            refused=(
                "Argus asked the model registry for the champion demand model and was "
                f"refused: {refusal_detail}"
            ),
            why=(
                "This is the prohibition at its bluntest. Argus composes what the other "
                "layers produce; when Metis produces nothing, the honest render is nothing. "
                "A page that filled this box from a plausible-looking heuristic would be "
                "manufacturing exactly the authority it is not allowed to hold."
            ),
            source=Source(
                origin="metis",
                citation="metis.forecast.runtime.NoChampionError",
                detail="the exception the runtime raised on this build",
            ),
        )
    )
    picture.limitations.append(
        "Because no forecast is served, the demand-against-capacity picture on this page "
        "is entirely BACKWARD-looking: it is the demand already in the book for the "
        "service day, not a forecast of demand that has not arrived. The 'upcoming window' "
        "framing describes the decision's position in time, not a prediction."
    )


# --------------------------------------------------------------------------
# 5. the decision, and the alternatives with their exact binding constraints
# --------------------------------------------------------------------------


def _the_decision(picture, result, decision, projection: Projection) -> None:
    ledger = picture.ledger
    solver = Source(
        origin="metis",
        citation="metis.decide.solve (milexium-decide 0.1.0)",
        detail="the scheduling authority's verdict on the posed problem, this run",
    )
    ledger.emit(
        "decision_status",
        "Scheduling verdict",
        f"{result.decision_status.upper()} (proven optimal: {result.decision_proven_optimal})",
        solver,
        value=result.decision_status,
    )
    ledger.emit(
        "decision_served",
        "Requests served in the solved problem",
        f"{result.decision_served} served, {result.decision_denied} denied",
        solver,
        value=[result.decision_served, result.decision_denied],
    )
    ledger.emit(
        "decision_reason_codes",
        "The constraint that bound",
        ", ".join(result.denial_reason_codes) or "none",
        Source(
            origin="metis",
            citation="metis.decide solver denial reason codes (themis.canonical.ReasonCode)",
            detail="enum codes from the hard constraint that actually bound, at decision time",
        ),
        note=(
            "Not SHAP output, not generated prose, not a post-hoc explanation. The "
            "aggregate code is silent about vehicles it did not bind on -- which is why "
            "each candidate is probed separately below."
        ),
        value=list(result.denial_reason_codes),
    )
    ledger.emit(
        "feasibility_violations",
        "Independent feasibility violations",
        str(result.feasibility_violations),
        Source(
            origin="metis",
            citation="metis.decide.check_feasibility",
            detail=(
                "an independent checker that never imports the solver, re-checking the "
                "solver's own answer"
            ),
        ),
        value=result.feasibility_violations,
    )

    for label, alternative in zip(projection.vehicle_labels, decision.alternatives):
        codes = list(alternative["failed_constraints"])
        picture.options.append(
            Option(
                label=label,
                authority="metis.decide.solve (one-vehicle probe)",
                feasible=bool(alternative["feasible"]),
                binding=", ".join(codes) if codes else "—",
                detail=(
                    "a separate solve of a one-vehicle problem carrying that vehicle's "
                    "already-committed trips; the codes are what that solve returned"
                ),
            )
        )

    equipment_refusals = 0
    for vehicle, label in enumerate(projection.vehicle_labels):
        outcome = certify_insertion(
            projection.instance,
            projection.profile,
            vehicle,
            projection.routes[vehicle],
            projection.late_request,
        )
        if EQUIPMENT_CHECKER in outcome.rejected_by:
            equipment_refusals += 1
        if outcome.certified:
            binding = "—"
            detail = outcome.detail
        else:
            codes = sorted({violation.code.value for violation in outcome.violations})
            binding = ", ".join(codes) if codes else "NO_FEASIBLE_SCHEDULE"
            detail = (
                f"rejected by {', '.join(outcome.rejected_by)} after "
                f"{outcome.sequences_tried} insertion position(s), exhaustive"
            )
            if outcome.violations:
                detail += f". First violation: {outcome.violations[0].detail}"
        picture.options.append(
            Option(
                label=label,
                authority="metis.decide.compatibility.certify_insertion (two checkers)",
                feasible=outcome.certified,
                binding=binding,
                detail=detail,
                recommended=outcome.certified,
            )
        )

    picture.table_sources["options"] = Source(
        origin="metis",
        citation=(
            "metis.decide.solve (one-vehicle probes) "
            "+ metis.decide.compatibility.certify_insertion (two independent checkers)"
        ),
        detail=(
            "each row is a separate solve or a separate exhaustive certification run at "
            "build time; the binding constraint is the authority's own reason code"
        ),
    )
    ledger.emit(
        "alternatives_probed",
        "Candidate placements probed",
        f"{len(picture.options)} probes across {len(projection.vehicle_labels)} vehicles "
        f"and 2 independent authorities",
        Source(
            origin="metis",
            citation=(
                "metis.decide.solve (one-vehicle probes) "
                "+ metis.decide.compatibility.certify_insertion"
            ),
            detail="every candidate was solved or certified, not asserted",
        ),
        value=len(picture.options),
    )
    ledger.emit(
        "equipment_checker_refusals",
        "Placements the EQUIPMENT checker refused, of those it was asked about",
        f"{equipment_refusals} of {len(projection.vehicle_labels)}",
        Source(
            origin="metis",
            citation=(
                "metis.decide.compatibility.check_equipment_feasibility, via "
                "CertificationOutcome.rejected_by"
            ),
            detail=(
                "counted from the checker each certification named, not inferred from "
                "the verdict"
            ),
        ),
        note=(
            "Reported whether or not it is zero. A layer that never appears in a "
            "rejection is a layer that has not been tested, and Metis carries "
            "`rejected_by` precisely so that can be seen rather than assumed. On this "
            "scenario the wheelchair-position constraint binds inside the SCHEDULING "
            "authority instead (see NO_ACCESSIBLE_CAPACITY in the table below); the "
            "conformance suite "
            "separately constructs the case that makes this checker fire, because a "
            "count of zero here is not evidence that it could not."
        ),
        value=equipment_refusals,
    )

    picture.findings.append(
        "The two authorities disagree about this trip, and the disagreement is structural "
        "rather than a bug in either. `metis.decide.DecisionProblem` carries a shift start "
        "and end PER VEHICLE, which is why the scheduling authority denies on SHIFT_END. "
        "`metis.decide.darp_ir.DarpInstance` has a single depot with a single time window "
        "and cannot express a per-vehicle shift at all, so the capacity lens cannot see the "
        "constraint that actually binds this decision. Where the lens certifies an "
        "insertion the scheduler denied, it is answering a strictly weaker question. The "
        "authority on WHETHER to serve is the scheduler; the lens is used below only for "
        "WHAT IT WOULD COST, and its answer is labelled a counterfactual."
    )
    picture.limitations.append(
        "The capacity projection cannot represent per-vehicle shifts. Any statement it "
        "makes about a placement is conditional on the shift being available, which for "
        "this decision it is not."
    )


# --------------------------------------------------------------------------
# 6. what the commitment costs in future capacity
# --------------------------------------------------------------------------


def marginal_cost_of_a_block(released) -> tuple[float, float]:
    """Read `foreclosed(committed -> this vehicle emptied)` as a COST.

    A separate, named, public function on purpose. On this scenario every value
    it returns happens to be zero, so a sign error inside it would be invisible
    in the artifact -- which is exactly the shape of the vacuous test this
    repository keeps finding. Pulling it out lets the conformance suite hand it
    a non-zero value and check the sign directly, rather than hoping the fixture
    reaches the case.

    `-0.0 or 0.0` is not decoration: `round(-0.0, 3)` is `-0.0`, and a page
    reporting "-0.00 future trips foreclosed" reads as a defect.
    """
    return (
        -released.trips_foreclosed or 0.0,
        -released.accessible_trips_foreclosed or 0.0,
    )


def _future_capacity_cost(picture, projection: Projection) -> None:
    ledger = picture.ledger
    instance, profile = projection.instance, projection.profile
    observed = [r for r in range(1, instance.num_requests + 1) if r != projection.late_request]
    prior = prior_from_observed(instance, profile, observed)
    ensemble = build_ensemble(
        instance,
        profile,
        prior,
        draws=CAPACITY_DRAWS,
        scenarios=CAPACITY_SCENARIOS,
        seed=CAPACITY_SEED,
    )

    capacity_source = Source(
        origin="metis",
        citation=f"metis.decide.capacity_value {CAPACITY_VALUE_VERSION}",
        detail=(
            f"{CAPACITY_DRAWS} independent draws of {CAPACITY_SCENARIOS} hypothetical "
            "future trips; a trip counts as reachable only when two independent checkers "
            "accept a concrete schedule for it"
        ),
    )
    capacity_inputs = [capacity_source, _declared_projection(), _declared_accessibility()]

    empty = empty_routes(instance)
    empty_snapshot = ensemble.snapshot(empty)
    committed = ensemble.snapshot(projection.routes)
    total_reach = committed.reach_before
    accessible_reach = committed.accessible_reach_before

    ledger.add(
        Figure.derived_from(
            "reach_empty_fleet",
            "Sampled future trips an EMPTY fleet could still absorb",
            f"{empty_snapshot.reach_before:.2f} of {CAPACITY_SCENARIOS}"
            f" ({empty_snapshot.accessible_reach_before:.2f} needing a wheelchair vehicle)",
            capacity_inputs,
            detail=(
                "Metis computed the reachability; the instance it computed over is the "
                "declared projection of the canonical day"
            ),
            value=[empty_snapshot.reach_before, empty_snapshot.accessible_reach_before],
        )
    )
    ledger.add(
        Figure.derived_from(
            "reach_committed_fleet",
            "Sampled future trips the DAY AS COMMITTED can still absorb",
            f"{total_reach:.2f} of {CAPACITY_SCENARIOS}"
            f" ({accessible_reach:.2f} needing a wheelchair vehicle)",
            capacity_inputs,
            detail="the same computation against the day's committed routes",
            note=(
                "ADR-0073's headline distributional metric: a forward statement about the "
                "fleet a plan leaves behind, not a count of who was served. It is "
                "MARGINAL, not simultaneous -- each hypothetical trip is asked about on "
                "its own, so this is an upper bound on what a draw could actually carry."
            ),
            value=[total_reach, accessible_reach],
        )
    )
    picture.table_sources["capacity_rows"] = Figure.derived_from(
        "capacity_rows_table", "Foreclosure by commitment", "table", capacity_inputs,
        detail="one foreclosure estimate per commitment, against the same draws",
    ).source

    day_foreclosed = empty_snapshot.reach_before - total_reach
    day_accessible_foreclosed = empty_snapshot.accessible_reach_before - accessible_reach
    ledger.add(
        Figure.derived_from(
            "day_foreclosure",
            "Future trips the day as committed has already foreclosed",
            f"{day_foreclosed:.2f} total, {day_accessible_foreclosed:.2f} accessible",
            capacity_inputs,
            detail="the difference between the two reach figures above, same draws",
            note=(
                "Read this against the projection's limits, not as a fleet-utilisation "
                "statistic. The projection cannot represent per-vehicle shifts, so every "
                "vehicle looks available all day and the fleet has slack the real day did "
                "not have. A near-zero figure here is a property of that looseness."
            ),
            value=[day_foreclosed, day_accessible_foreclosed],
        )
    )

    empty_route = [instance.depot_start, instance.depot_end]
    for vehicle, label in enumerate(projection.vehicle_labels):
        if len(projection.routes[vehicle]) <= 2:
            continue  # pragma: no cover -- every vehicle in this scenario is loaded
        # MARGINAL, GIVEN THE REST OF THE DAY: what this vehicle's block costs
        # while the other vehicles carry what they actually carried. The other
        # framing -- scoring the block against an otherwise EMPTY fleet, which is
        # the pattern `attach_capacity_features` uses to compare candidate shares
        # -- answers a different question and reads zero on any fleet with slack,
        # because the idle vehicles absorb every hypothetical trip anyway.
        #
        # Computed as `foreclosed(committed -> this vehicle emptied)` and read
        # with the sign flipped, which is the SAME quantity per draw as
        # `value_of(emptied, committed)`: the two differ only in which state is
        # `before`. It is done this way because the incremental form reuses the
        # committed snapshot's reach matrix and costs a fraction of the honest
        # form, and the honest form was measured returning identical figures.
        released = ensemble.value_of_replacement(committed, vehicle, empty_route)
        cost, accessible_cost = marginal_cost_of_a_block(released)
        picture.capacity_rows.append(
            {
                "label": label,
                "kind": "committed block (marginal, given the rest of the day)",
                "accessible": profile.is_accessible(vehicle),
                "trips_foreclosed": round(cost, 3),
                "accessible_trips_foreclosed": round(accessible_cost, 3),
                "stderr": round(released.stderr, 3),
                "accessible_stderr": round(released.accessible_stderr, 3),
                "distinguishable_from_zero": abs(cost) > released.stderr,
            }
        )

    counterfactual = None
    for vehicle, label in enumerate(projection.vehicle_labels):
        outcome = certify_insertion(
            instance, profile, vehicle, projection.routes[vehicle], projection.late_request
        )
        if not outcome.certified:
            continue
        value = ensemble.value_of_replacement(
            committed, vehicle, list(outcome.certificate.sequence)
        )
        counterfactual = (label, value)
        picture.capacity_rows.append(
            {
                "label": f"{label} + the denied trip",
                "kind": "COUNTERFACTUAL placement",
                "accessible": profile.is_accessible(vehicle),
                "trips_foreclosed": round(value.trips_foreclosed, 3),
                "accessible_trips_foreclosed": round(value.accessible_trips_foreclosed, 3),
                "stderr": round(value.stderr, 3),
                "accessible_stderr": round(value.accessible_stderr, 3),
                "distinguishable_from_zero": abs(value.trips_foreclosed) > value.stderr,
            }
        )
        break

    if counterfactual is not None:
        label, value = counterfactual
        ledger.add(
            Figure.derived_from(
                "counterfactual_foreclosure",
                "If the shift could be extended: future trips foreclosed by serving the "
                "denied rider",
                f"{value.trips_foreclosed:.2f} ± {value.stderr:.2f} "
                f"({value.accessible_trips_foreclosed:.2f} ± {value.accessible_stderr:.2f} "
                f"needing a wheelchair vehicle)",
                capacity_inputs,
                detail="foreclosure of the certified insertion, against the same draws",
                note=(
                    f"A COUNTERFACTUAL. The scheduling authority denied this trip on every "
                    f"vehicle; the lens can certify it onto {label} only because the lens "
                    "cannot see shift ends. The figure prices the option an operator would "
                    "have to buy, and is not a recommendation to serve."
                ),
                value=[value.trips_foreclosed, value.accessible_trips_foreclosed],
            )
        )
        distinguishable = abs(value.trips_foreclosed) > value.stderr
        ledger.emit(
            "foreclosure_distinguishable",
            "Is that foreclosure larger than its own sampling noise?",
            "yes" if distinguishable else "NO — not distinguishable from zero",
            Source(
                origin="metis",
                citation="metis.decide.capacity_value.CapacityValue.stderr",
                detail=(
                    "standard error of the mean across the independent draws, computed by "
                    "the same call that produced the estimate"
                ),
            ),
            note=(
                "A foreclosure difference smaller than its standard error is not a "
                "finding, and the type carries the number that says so rather than "
                "leaving it to a reader's goodwill."
            ),
            value=distinguishable,
        )
        if not distinguishable:
            picture.refusals.append(
                Refusal(
                    key="foreclosure_noise",
                    headline="The foreclosure estimate declines to be read as a finding",
                    refused=(
                        f"{value.trips_foreclosed:.2f} future trips foreclosed, against a "
                        f"standard error of {value.stderr:.2f} across "
                        f"{CAPACITY_DRAWS} draws — the estimate is not distinguishable "
                        f"from zero at this draw count."
                    ),
                    why=(
                        "The estimate is reported WITH its error bar rather than rounded "
                        "into a headline. More draws would narrow it; this page does not "
                        "pretend the ones it ran were enough."
                    ),
                    source=Source(
                        origin="metis",
                        citation="metis.decide.capacity_value.CapacityValue",
                        detail="draws, per-draw deltas and standard error as returned",
                    ),
                )
            )

    if all(row["trips_foreclosed"] == 0 for row in picture.capacity_rows[:-1]):
        picture.findings.append(
            "The projection's fleet has slack the real day did not, and the capacity "
            "figures show it: every committed block scores ZERO foreclosure. Three "
            "vehicles, one depot window and no per-vehicle shift bound mean nearly every "
            "hypothetical trip fits somewhere, so removing any single vehicle's whole "
            "block changes nothing. Tightening max_route_duration to the day's own "
            "longest block was tried and changed nothing either. The figure that does "
            "bite is the marginal insertion, because it takes away the one vehicle that "
            "could have carried a particular future trip at a particular time. Reported "
            "as a negative result rather than dropped, because a table of zeros with no "
            "explanation is indistinguishable from a broken computation."
        )

    ledger.emit(
        "capacity_prior_note",
        "What the future-capacity numbers assume",
        "The demand half is a PLACEHOLDER PRIOR, not a forecast",
        Source(
            origin="metis",
            citation="metis.decide.capacity_value.PRIOR_IS_AN_ASSUMPTION_NOTE",
            detail="carried verbatim from the module that computed the figures",
        ),
        note=PRIOR_IS_AN_ASSUMPTION_NOTE,
    )
    picture.limitations.append(
        "The feasibility half of every foreclosure figure is exact -- two independent "
        "checkers accept a concrete schedule or the trip does not count. The demand half "
        "resamples requests already observed and displaces them; absolute foreclosure "
        "counts inherit that assumption entirely."
    )


# --------------------------------------------------------------------------
# 7. serve-time drift: the condition that would invalidate a forecast
# --------------------------------------------------------------------------


def _serve_time_drift(picture) -> None:
    """Run Milexium's own serve-time drift monitor on real public demand data.

    Explicitly NOT about the synthetic operator. It is on the page because it
    answers "what would invalidate a forecast-derived recommendation" with a
    measurement rather than a paragraph -- and because the monitor is seen
    returning BOTH answers, on an exchangeable control and on a real serving
    window, so a reader can tell a real test from a warning that is always on.
    """
    ledger = picture.ledger
    if not (demo.AAR_PANEL.exists() and demo.WEATHER_PANEL.exists()):
        picture.limitations.append(
            "The committed demand panels are not present in this checkout, so no "
            "serve-time drift evidence is shown. Nothing was fabricated in their place."
        )
        return

    import random

    names = feature_names_for("zone_hour_demand_v1")
    rows = demo._aar_feature_rows()
    reference_rows = [
        row
        for row in rows
        if demo.DRIFT_REFERENCE_WINDOW[0] <= row["day"] <= demo.DRIFT_REFERENCE_WINDOW[1]
    ]
    serving_rows = [
        row
        for row in rows
        if demo.DRIFT_SERVING_WINDOW[0] <= row["day"] <= demo.DRIFT_SERVING_WINDOW[1]
    ]
    order = list(range(len(reference_rows)))
    random.Random(demo.DRIFT_SPLIT_SEED).shuffle(order)
    half = len(order) // 2
    reference_half = [reference_rows[i] for i in sorted(order[:half])]
    control_half = [reference_rows[i] for i in sorted(order[half:])]

    reference = derive_reference_from_rows(
        reference_half,
        names,
        source_kind="committed_panel",
        description=(
            f"REAL NYC MTA Access-A-Ride borough-hour trips, {demo.DRIFT_BOROUGH}, "
            f"{demo.DRIFT_REFERENCE_WINDOW[0]}..{demo.DRIFT_REFERENCE_WINDOW[1]}"
        ),
        derivation=(
            "borough-hour trip counts with calendar features and committed NOAA weather; "
            "a seeded random half of the window retained, the other half kept as the "
            "exchangeable control"
        ),
        panel_path=demo._citable(demo.AAR_PANEL),
        max_sample=None,
    )
    control = assess_drift(
        reference, control_half, target_coverage=demo.DRIFT_TARGET_COVERAGE
    )
    serving = assess_drift(
        reference, serving_rows, target_coverage=demo.DRIFT_TARGET_COVERAGE
    )

    panel_source = _corpus_source(
        demo.AAR_PANEL,
        "REAL NYC MTA Access-A-Ride borough-hour trips; public aggregate data",
    )
    monitor_source = Source(
        origin="metis",
        citation="metis.forecast.serve_drift.assess_drift",
        detail=(
            "PSI and two-sample KS per feature against the derived reference, "
            f"target coverage {demo.DRIFT_TARGET_COVERAGE:.0%}"
        ),
    )

    ledger.emit(
        "drift_reference_rows",
        "Reference rows the monitor calibrated on",
        f"{reference.n_rows:,}",
        panel_source,
        note=(
            "The registered model artifact was asked for its own training reference "
            "distribution first and returned nothing -- ModelVersion records a manifest "
            "hash, a schema version and an evaluation window, but no per-feature "
            "distribution. The reference is therefore DERIVED, and its provenance records "
            "the panel path, its SHA-256, the window and the seed."
        ),
        value=reference.n_rows,
    )
    ledger.emit(
        "drift_control",
        "Control window (an exchangeable half of the same window)",
        f"{control.status} / interval guarantee {control.interval_guarantee}",
        monitor_source,
        note=(
            "The control is exchangeable by construction, so the monitor should say "
            "nothing is wrong -- and does. This is what makes the verdict below a test "
            "that can come back either way rather than a warning that is always on."
        ),
        value=control.status,
    )
    ledger.emit(
        "drift_serving",
        f"Real serving window {demo.DRIFT_SERVING_WINDOW[0]}..{demo.DRIFT_SERVING_WINDOW[1]}",
        f"{serving.status} / interval guarantee {serving.interval_guarantee}",
        monitor_source,
        note=(
            f"Drift on {len(serving.drifted_features)} of {len(serving.features)} monitored "
            f"features: {', '.join(serving.drifted_features)}."
        ),
        value=serving.status,
    )
    picture.table_sources["drift_features"] = monitor_source
    for feature in serving.features:
        picture.drift_features.append(
            {
                "feature": feature.feature,
                "psi": None if feature.psi is None else round(feature.psi, 4),
                "psi_band": feature.psi_band,
                "ks_p_value": None if feature.ks_p_value is None else feature.ks_p_value,
                "flagged": feature.flagged,
                "note": feature.note,
            }
        )

    if serving.interval_caveat:
        picture.refusals.append(
            Refusal(
                key="interval_guarantee",
                headline="A conformal interval withdraws its own coverage guarantee",
                refused=serving.interval_caveat,
                why=(
                    "The forecast would still be served and the interval reported "
                    "UNCHANGED -- the monitor annotates, it does not decide. What it "
                    "withdraws is the CLAIM. A split-conformal interval is "
                    "distribution-free only under exchangeability, and measured input "
                    "drift is direct evidence against that premise."
                ),
                source=Source(
                    origin="metis",
                    citation="metis.forecast.serve_drift.DriftVerdict.interval_caveat",
                    detail="the withdrawal text the monitor produced on this run",
                ),
            )
        )
    picture.limitations.append(
        "The drift evidence is about the real Access-A-Ride panel, NOT about the synthetic "
        "operator whose day this page shows. It is here because it is the only real "
        "measurement available of the condition that would invalidate a forecast-derived "
        "recommendation. It is not a verdict on the scenario above."
    )


# --------------------------------------------------------------------------
# 8. what the day actually cost, and what the model refuses to call a saving
# --------------------------------------------------------------------------


def _teardown_outcome(picture, result, teardown) -> None:
    """Read the teardown OBJECT, not the walkthrough's transcription of it.

    The two carry identical values, and reading the object is the difference
    between a figure that cites `aletheia.replay.teardown` and a figure that
    genuinely came from it. Only the NTD cost basis is taken from `result`,
    because that is where the walkthrough puts what it read out of the committed
    corpus and the corpus is cited directly.
    """
    ledger = picture.ledger
    cost = teardown.cost
    measured = teardown.total_revenue_minutes + teardown.total_deadhead_minutes
    unattributable = (
        0.0 if teardown.unattributable is None else teardown.unattributable.deadhead_minutes
    )
    attributed = sum(run.deadhead_minutes for run in teardown.top_runs)
    reconciles = abs(attributed + unattributable - teardown.total_deadhead_minutes) < 1e-6
    teardown_source = Source(
        origin="aletheia",
        citation="aletheia.evidence.capture_teardown / aletheia.replay.teardown",
        detail="the deadhead teardown object this run produced, read field by field",
    )
    ntd_source = _corpus_source(
        demo.NTD_ECONOMICS,
        "REAL 2024 FTA National Transit Database demand-response filings",
    )

    ledger.emit(
        "deadhead_minutes",
        "Empty vehicle minutes on the day",
        f"{teardown.total_deadhead_minutes:,.1f} min of {measured:,.1f} measured",
        teardown_source,
        value=teardown.total_deadhead_minutes,
    )
    ledger.emit(
        "deadhead_share",
        "Empty share of measured vehicle time",
        f"{teardown.deadhead_share_of_vehicle_time:.1%}",
        teardown_source,
        note="SYNTHETIC data: this is a property of the fixture, not a finding about anyone.",
        value=teardown.deadhead_share_of_vehicle_time,
    )
    ledger.emit(
        "ntd_peer_deadhead",
        "REAL peer distribution, 2024 NTD demand-response filings",
        f"median {result.ntd_deadhead_median:.1%}, p90 {result.ntd_deadhead_p90:.1%}",
        ntd_source,
        note=(
            f"Across {result.ntd_agency_count} agencies. The peer numbers are real and "
            "public; the share above them is synthetic. They are shown together because "
            "the comparison is the product and nobody computes it for an operator."
        ),
        value=[result.ntd_deadhead_median, result.ntd_deadhead_p90],
    )
    ledger.emit(
        "cost_per_vrh",
        "Cost per vehicle-revenue-hour used to value empty time",
        f"${result.ntd_cost_per_vrh:,.2f}",
        ntd_source,
        note=(
            f"REAL: the median across {result.ntd_agency_count} demand-response agencies. "
            "A national stand-in rate, not this (synthetic) operator's own books."
        ),
        value=result.ntd_cost_per_vrh,
    )
    ledger.emit(
        "value_at_full_cost",
        "Accounting value of the empty time",
        f"${cost.value_at_full_cost:,.2f}",
        teardown_source,
        note=(
            "An accounting value at a published national rate. NOT a saving, not an "
            "opportunity and not a forecast of cash."
        ),
        value=cost.value_at_full_cost,
    )
    ledger.emit(
        "unattributable_minutes",
        "Empty minutes that cannot be attributed to a run",
        f"{unattributable:,.1f} min",
        teardown_source,
        note=(
            f"Attribution reconciles exactly: {attributed:,.1f} attributed + "
            f"{unattributable:,.1f} unattributable = {teardown.total_deadhead_minutes:,.1f}, "
            f"the total ({reconciles}). Recomputed here from the teardown's own run rows."
        ),
        value=unattributable,
    )

    picture.refusals.append(
        Refusal(
            key="no_savings_envelope",
            headline="No savings figure without the operator's own cost split",
            refused=(
                "Asked for a savings envelope with no fixed-versus-variable split of the "
                "cost per vehicle-hour, the teardown returned none: "
                f"{result.envelope_without_split}"
            ),
            why=(
                "There is no default for that split because nobody outside an operator's "
                "finance office knows it. Given an explicitly illustrative "
                f"{demo.ILLUSTRATIVE_AVOIDABLE_SHARE[0]:.0%}-"
                f"{demo.ILLUSTRATIVE_AVOIDABLE_SHARE[1]:.0%} share the teardown returns an "
                f"envelope of ${cost.modelled_envelope_low:,.2f}.."
                f"${cost.modelled_envelope_high:,.2f} and still refuses to call it "
                f"guaranteed (is_guaranteed_saving={cost.is_guaranteed_saving}; setting that field "
                "True raises)."
            ),
            source=Source(
                origin="aletheia",
                citation="aletheia.replay.teardown.CostBasis",
                detail="the envelope basis string the model returned when given no split",
            ),
        )
    )
    picture.refusals.append(
        Refusal(
            key="unattributable",
            headline="Empty time that cannot be attributed stays unattributed",
            refused=(
                f"{unattributable:,.1f} empty minutes sit in their "
                "own row, outside the ranking, because one vehicle's rows name no run."
            ),
            why=(
                "Never merged into a run that did not incur it, never dropped, and reported "
                "outside the ranking so a top-N truncation cannot bury it. A fabricated run "
                "id would have made the ranking look complete and been wrong."
            ),
            source=Source(
                origin="aletheia",
                citation="aletheia.replay.teardown unattributable bucket",
                detail="the run-level attribution this run produced",
            ),
        )
    )


# --------------------------------------------------------------------------
# 9. human authorisation
# --------------------------------------------------------------------------


def _authorisation(picture, client, decision) -> None:
    ledger = picture.ledger
    packet = client.evidence_for(decision.aggregate_id)
    chain_source = Source(
        origin="themis",
        citation="themis.core append-only hash-chained event log via MilexiumClient.evidence_for",
        detail="the raw ledger rows for this decision, re-read after they were written",
    )

    picture.table_sources["ledger_events"] = chain_source
    for event in list(packet.proposed) + list(packet.approved_or_overridden):
        picture.ledger_events.append(
            {
                "sequence": event.sequence,
                "event_type": event.event_type.value,
                "actor_type": event.actor_type,
                "actor_id": event.actor_id,
                "occurred_at": event.occurred_at.isoformat(),
                "hash": event.hash[:16] + "…",
                "prev_hash": (event.prev_hash[:16] + "…") if event.prev_hash else "",
                "reason_codes": [code.value for code in event.reason_codes],
            }
        )

    ledger.emit(
        "ledger_events",
        "Events on the chain for this decision",
        str(len(picture.ledger_events)),
        chain_source,
        value=len(picture.ledger_events),
    )
    ledger.emit(
        "authorisation",
        "The decision that stood",
        f"{packet.executed.event_type.value.upper()} by "
        f"{packet.executed.actor_type}:{packet.executed.actor_id}",
        chain_source,
        note=(
            "The reviewer did not change the outcome and the record says so. The actor is "
            "a SYNTHETIC actor; no person has reviewed anything in this repository."
        ),
        value=packet.executed.event_type.value,
    )
    ledger.emit(
        "chain_integrity",
        "Hash chain and schema verified",
        f"{packet.integrity_verified} ({len(packet.chain_violations)} chain violations)",
        Source(
            origin="aletheia",
            citation="aletheia.evidence packet verification",
            detail="hash chain recomputed from the raw rows and schema re-checked",
        ),
        value=packet.integrity_verified,
    )
    ledger.emit(
        "alternatives_on_the_record",
        "Alternatives parsed back out of the recorded payload",
        str(len(packet.alternatives_considered)),
        Source(
            origin="themis",
            citation="themis.canonical.DecisionAlternative (validated on read)",
            detail=(
                "the alternatives travel in the recommendation payload and are validated "
                "against the canonical shape when read back"
            ),
        ),
        note=(
            "GAP, reported not worked around: `decision_alternatives` is a real canonical "
            "table with a store writer, but no public store method creates the parent "
            "`schedule_runs` row it foreign-keys to, so the table cannot be written through "
            "the supported API and the payload convention stands."
        ),
        value=len(packet.alternatives_considered),
    )


# --------------------------------------------------------------------------
# 10. the later actual outcome, against what was expected
# --------------------------------------------------------------------------


def _outcome_against_expectation(picture, result, pairs) -> None:
    ledger = picture.ledger
    denied = [
        (record, row) for record, row in pairs if record.request.status.value == "denied"
    ]
    record, row = denied[0]
    ref = row["BookingRef"].strip()

    ledger.emit(
        "expected_outcome",
        "What Milexium decided, at decision time",
        f"DENY {ref} — {', '.join(result.denial_reason_codes)}",
        Source(
            origin="metis",
            citation="metis.decide.solve, recorded on the ledger before the outcome was known",
            detail="the recommendation and its reason codes as written to the chain",
        ),
        value=ref,
    )
    ledger.emit(
        "actual_outcome",
        "What the operator's export later recorded",
        f"{record.request.status.value.upper()} — reason: not carried by the export",
        Source(
            origin="themis",
            citation="canonical ServiceRequest.status from the operator export",
            detail="the operator's own terminal status for the same trip",
        ),
        value=record.request.status.value,
    )
    agreement = record.request.status.value == "denied" and result.decision_denied == 1
    ledger.emit(
        "outcome_agreement",
        "Did the recommendation match the outcome?",
        "The outcome matched. The REASON is still unknown, and stays unknown."
        if agreement
        else "The outcome did not match.",
        Source(
            origin="themis",
            citation="canonical status + metis.decide denial, compared",
            detail="a comparison of two recorded facts, neither of which this layer produced",
        ),
        note=(
            "Agreement on the WHAT is not agreement on the WHY. Milexium does not copy the "
            "reason it just computed onto the operator's denial: what the operator's system "
            "decided (reason unknown) and what Milexium's solver decided when posed the "
            "same problem (reason recorded) are two different facts."
        ),
        value=agreement,
    )
    ledger.emit(
        "on_time_flag",
        "On-time performance",
        "not computed",
        Source(
            origin="themis",
            citation="canonical Outcome.on_time (left None on purpose)",
            detail="the field the adapter deliberately does not fill",
        ),
        note=(
            "On-time depends on the agency's own window, commonly -0/+30 minutes, which is "
            "a policy parameter no export carries. Computing it would be a guess dressed as "
            "a measurement."
        ),
    )

    picture.refusals.append(
        Refusal(
            key="denial_reason",
            headline="The operator's own denial keeps its own (missing) reason",
            refused=(
                f"The export's DENIED row {ref} carries no reason, and Milexium does not "
                "copy the reason it just computed onto it."
            ),
            why=(
                "Back-filling the first from the second would manufacture an audit trail "
                "for a decision nobody at Milexium made. Related, and stated rather than "
                "papered over: the intake column list carries no ADA-mandate flag, so an "
                "ADA complementary-paratransit trip that cannot be scheduled — an "
                "INFEASIBLE instance, not a denial — is indistinguishable here from a "
                "discretionary one."
            ),
            source=Source(
                origin="themis",
                citation="canonical ServiceRequest / the operator export column list",
                detail="the absence of a denial-reason column, carried as an absence",
            ),
        )
    )


# --------------------------------------------------------------------------
# 11. everything the picture rests on
# --------------------------------------------------------------------------


def _scenario_disclosure(picture, projection: Projection) -> None:
    picture.table_sources["scenario_inputs"] = _scenario_source(
        "the module constants listed in this table",
        "declared here and nowhere else; no layer produced any of them",
    )
    picture.table_sources["attribution_summary"] = Source(
        origin="argus",
        citation="argus/command_centre/attribution.py::FigureLedger.by_origin",
        detail="a count over this build's own figure ledger, written beside the page",
    )
    picture.scenario_inputs.extend(
        [
            ScenarioInput(
                "Pickup window",
                f"{PICKUP_WINDOW_MINUTES:.0f} minutes after the scheduled pickup",
                "The export carries no promised window. The walkthrough already declares "
                "this figure for its late booking; the projection applies the SAME window "
                "to every request so the late booking is not advantaged.",
            ),
            ScenarioInput(
                "Maximum ride time",
                f"{MAX_RIDE_MINUTES:.0f} minutes",
                "The walkthrough's own drop-off bound for the late booking, applied "
                "uniformly. No policy in the export constrains ride time.",
            ),
            ScenarioInput(
                "Vehicle seats",
                str(VEHICLE_SEATS),
                "The export carries no vehicle configuration at all — no seat count, no "
                "position count, no make or model.",
            ),
            ScenarioInput(
                "Wheelchair positions per accessible vehicle",
                str(WHEELCHAIR_POSITIONS),
                "Declared. Metis owns what a position means and what it costs the floor; "
                "the count cannot come from the export.",
            ),
            ScenarioInput(
                "Wheelchair station footprint",
                f"{WHEELCHAIR_FOOTPRINT} seat-equivalents",
                "A deployed station consumes shared floor. This is the number that lets "
                "the floor refuse a group the seat count would allow.",
            ),
            ScenarioInput(
                "Assigned wheelchair share / accessible vehicles",
                f"{WHEELCHAIR_SHARE:.0%} of requests / {ACCESSIBLE_VEHICLES} of "
                f"{len(projection.vehicle_labels)} vehicles",
                "ASSIGNED by metis.decide.compatibility.assign_accessibility at seed "
                f"{projection.assignment_seed} — the smallest seed at which the operator's "
                "own completed day is itself equipment-feasible. Not observed. Every "
                "stratified figure on this page demonstrates that the METHOD discriminates "
                "between cohorts and is not evidence about any real disabled rider.",
            ),
            ScenarioInput(
                "Zone geometry",
                f"regular {len(projection.zone_coords)}-gon, scaled so mean pairwise travel "
                f"time = {projection.mean_observed_minutes:.1f} min",
                "The export carries zone identifiers and no coordinates, and this "
                "repository holds no centroid for them. The SHAPE is an assumption; the "
                "SCALE is measured from the export's own observed trip durations. Travel "
                "times in the projection are therefore approximate and do not reproduce "
                "any individual trip.",
            ),
            ScenarioInput(
                "Scenario draw",
                f"{CAPACITY_DRAWS} draws x {CAPACITY_SCENARIOS} hypothetical trips, "
                f"seed {CAPACITY_SEED}",
                "Enough draws for the standard error to be a real error bar rather than "
                "zero by construction, and cheap enough to run at page-build time.",
            ),
        ]
    )

    picture.limitations.extend(
        [
            "Everything on this page is Demonstrated at most. Under ADR-0001, Validated "
            "requires consented operator data against a declared baseline, and Milexium has "
            "none — no customers, no pilots, no operator data.",
            "The scenario is one synthetic service day: three vehicles, "
            f"{len(picture.requests)} imported trips, one denial. Nothing here generalises "
            "to a fleet, a week, or an agency.",
            "Accessibility labels are ASSIGNED, not observed (ADR-0065). Every stratified "
            "figure demonstrates that the method discriminates between cohorts; none is "
            "evidence about the exposure any real fleet's wheelchair users face.",
            "The reachability count is MARGINAL, not simultaneous: each hypothetical trip "
            "is asked about on its own against the fleet as it stands, so it is an upper "
            "bound on what a draw could actually carry.",
            "No page element is interactive and no state is stored. This is a rendered "
            "picture of one build, not a console.",
        ]
    )
