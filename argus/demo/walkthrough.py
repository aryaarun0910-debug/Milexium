"""The Milexium evidence walkthrough: one command, the whole chain, end to end.

    py -3 -m argus.demo

WHAT THIS IS. A single self-contained run that takes a messy operator-style
trip export, repairs what is unambiguously repairable, quarantines what is not,
turns the survivors into canonical records, poses one real scheduling decision
and records its reasons at decision time, measures where the empty vehicle time
actually sat, and exports an evidence bundle that a third party re-derives from
its own bytes without trusting the process that wrote it. The last step is the
point: the bundle recomputes its own claims.

RELATIONSHIP TO argus/demo/golden_path.py. `golden_path.py` is NOT superseded and is
not modified. It is the *real-data* demo: it needs the gitignored Access-A-Ride
XGBoost booster and a ~0.5 GB NYC TLC parquet, so on a fresh clone it prints a
skip. This walkthrough is the *primary* demo precisely because it runs on a
fresh clone: every input is either committed public data or a synthetic file
that says so in its own filename. The two overlap on ingest/decide/evidence and
differ on everything else -- golden_path serves a real forecast and runs a
modelled baseline comparison; this one runs the repair/quarantine intake, the
deadhead teardown, the serve-time drift refusal, and the re-derivation.

REAL VERSUS SYNTHETIC, stated once here and again on every line that carries a
number:

  REAL, committed, in this repository:
    * forge/business/ntd/agency_economics.csv -- FTA National Transit Database 2024 demand-
      response filings. Source of the cost per vehicle-revenue-hour the teardown
      values empty time at, and of the peer deadhead distribution.
    * data/curated/panels/aar_hourly_borough.csv.gz -- NYC MTA Access-A-Ride
      borough-hour trips, 2024-01-01..2026-05-31. Source of the drift reference
      and the serving window.
    * data/curated/panels/weather_daily.csv -- NOAA daily weather for NYC, joined to
      the AAR panel to build the real feature columns of zone_hour_demand_v1.

  SYNTHETIC, and labelled in the filename itself:
    * argus/demo/data/SYNTHETIC_operator_export_part1_first_send.csv
    * argus/demo/data/SYNTHETIC_operator_export_part2_resend.csv
      No operator has ever sent this repository an export. These two files are
      what a vendor extract LOOKS like -- the column names, the defects and the
      shape are modelled on forge/knowledge/docs/OPERATOR_DATA_INTAKE.md -- and nothing derived
      from them is evidence about any real agency.

STATUS. Everything here is **Demonstrated**. Nothing is Validated: validation
requires consented operator data against a declared baseline, and there is none.
Milexium has zero customers and zero pilots.

INFRASTRUCTURE. None required. The canonical store is in-memory SQLite. If
PostgreSQL or MinIO happen to be configured they are still not used, and the
preflight says so rather than letting a reader assume a database was involved.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import json
import math
import random
import statistics
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from themis.canonical import (
    DecisionEventType,
    PolicyId,
    ReasonCode,
    ScheduleRunId,
    VehicleId,
    new_id,
)
from themis.connect import (
    OperatorExportAdapter,
    build_ingest_report,
    repair_rule_of,
)
from themis.connect.operator_export import REDACTION_MARKER
from metis.decide import (
    DecisionPolicy,
    DecisionProblem,
    DecisionVehicle,
    RideRequest,
    check_feasibility,
    solve,
)
from aletheia.evidence import build_evidence_pack, capture_teardown
from aletheia.replay.teardown import CostBasis, VehicleSegment
from argus.sdk import MilexiumClient

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = Path(__file__).resolve().parent / "data"
_DEFAULT_OUTPUT_DIR = _REPO_ROOT / "aletheia" / "artifacts" / "demo-walkthrough"

# --- real, committed inputs ------------------------------------------------
NTD_ECONOMICS = _REPO_ROOT / "forge" / "business" / "ntd" / "agency_economics.csv"
AAR_PANEL = _REPO_ROOT / "data" / "curated" / "panels" / "aar_hourly_borough.csv.gz"
WEATHER_PANEL = _REPO_ROOT / "data" / "curated" / "panels" / "weather_daily.csv"

# --- synthetic, labelled inputs -------------------------------------------
EXPORT_PART1 = _DATA_DIR / "SYNTHETIC_operator_export_part1_first_send.csv"
EXPORT_PART2 = _DATA_DIR / "SYNTHETIC_operator_export_part2_resend.csv"

# The operator's own header mapped onto the published intake column list
# (forge/knowledge/docs/OPERATOR_DATA_INTAKE.md). ActualDO, OnTimeFlagVendor and contact_1 have
# no canonical target and are deliberately left unmapped -- the adapter records
# each by NAME ONLY and never retains its value.
COLUMN_MAP = {
    "BookingRef": "trip_ref",
    "ReqDateTime": "requested_at",
    "SchedPU": "scheduled_pickup_at",
    "ActualPU": "actual_pickup_at",
    "PU Zone": "pickup_zone",
    "DO Zone": "dropoff_zone",
    "VehicleNo": "vehicle_ref",
    "RunID": "run_ref",
    "TripStatus": "outcome",
}

# A gap between one trip's end and the same vehicle's next trip is only counted
# as empty RUNNING time up to this length. Longer gaps are break, layover or
# idle time that a trip export cannot distinguish from deadhead; counting them
# would inflate the very number the teardown exists to measure, so they are
# excluded and reported as unmeasured. A demo modelling choice, stated here and
# on screen -- not a fact about any operator.
MAX_CHAINED_GAP_MINUTES = 45.0

# The fixed-versus-variable split of an operator's cost per vehicle-hour. NOT a
# measured figure and NOT a Milexium default: `CostBasis` has no default for it
# precisely because only an operator's finance office knows it. Supplied here as
# an explicitly-labelled illustrative range so the second teardown can show what
# an envelope looks like; the first teardown supplies nothing and gets no
# envelope at all.
ILLUSTRATIVE_AVOIDABLE_SHARE = (0.30, 0.60)

# Drift windows over the real committed AAR panel. Reference is winter 2024;
# the serving window is spring 2026, two years later. The control is a seeded
# random half of the SAME reference window, which is exchangeable by
# construction -- included so the monitor is seen saying "no drift" as well.
DRIFT_BOROUGH = "Brooklyn"
DRIFT_REFERENCE_WINDOW = ("2024-01-01", "2024-02-29")
DRIFT_SERVING_WINDOW = ("2026-03-01", "2026-05-31")
DRIFT_SPLIT_SEED = 20260725
DRIFT_TARGET_COVERAGE = 0.90

_RULE = "=" * 78
_THIN = "-" * 78


class WalkthroughInputMissing(RuntimeError):
    """A committed input this walkthrough needs is not on disk."""


@dataclass
class WalkthroughResult:
    """Everything the conformance test asserts on. Every field is computed by
    the run; nothing here is a constant copied from a document."""

    # step 1-2: intake
    part1_rows: int = 0
    part1_accepted: int = 0
    part1_quarantined: int = 0
    part1_pii_quarantines: int = 0
    part1_redaction_leaked: bool = True
    part2_rows: int = 0
    part2_accepted: int = 0
    part2_quarantined: int = 0
    part2_repair_rules: dict[str, int] = field(default_factory=dict)
    part2_quarantine_codes: dict[str, int] = field(default_factory=dict)
    ambiguous_date_quarantined: bool = False
    unambiguous_date_repaired: bool = False
    semantic_loss_records: int = 0
    # step 3: canonical
    canonical_requests: int = 0
    canonical_denied: int = 0
    canonical_no_show: int = 0
    conservation_holds: bool = False
    # step 4: decide
    decision_status: str = ""
    decision_proven_optimal: bool = False
    decision_served: int = 0
    decision_denied: int = 0
    denial_reason_codes: tuple[str, ...] = ()
    feasibility_violations: int = 0
    alternatives_probed: int = 0
    infeasible_alternatives: int = 0
    ledger_events: int = 0
    ledger_integrity_verified: bool = False
    ledger_chain_violations: int = 1
    # step 5: teardown
    segments: int = 0
    revenue_segments: int = 0
    deadhead_segments: int = 0
    unmeasured_segments: int = 0
    total_deadhead_minutes: float = 0.0
    total_revenue_minutes: float = 0.0
    deadhead_share: float = 0.0
    unattributable_deadhead_minutes: float = 0.0
    attributed_run_count: int = 0
    attribution_reconciles: bool = False
    ntd_cost_per_vrh: float = 0.0
    ntd_agency_count: int = 0
    ntd_deadhead_median: float = 0.0
    ntd_deadhead_p90: float = 0.0
    envelope_without_split: str = ""
    envelope_low: float | None = None
    envelope_high: float | None = None
    value_at_full_cost: float | None = None
    is_guaranteed_saving: bool = True
    # step 6: drift
    drift_assessed: bool = False
    drift_reference_rows: int = 0
    drift_control_status: str = ""
    drift_control_guarantee: str = ""
    drift_serving_status: str = ""
    drift_serving_guarantee: str = ""
    drifted_features: tuple[str, ...] = ()
    drift_skipped_features: tuple[str, ...] = ()
    artifact_carried_reference: bool = True
    # step 7-8: evidence
    pack_path: Path | None = None
    manifest_path: Path | None = None
    pack_reverified: bool = False
    chain_reverified: bool = False
    manifest_consistent: bool = False
    narrative_consistent: bool = False
    teardown_figures_rederived: bool = False
    teardown_fingerprint_rederived: bool | None = None
    teardown_checks: int = 0
    teardown_mismatches: tuple[str, ...] = ()
    runtime_seconds: float = 0.0


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _utc(text: str) -> datetime:
    """A demo-side timestamp read.

    Applied ONLY to the export's unmapped `ActualDO` column (see step 5 for why
    the canonical path cannot carry it). The naive value is read as UTC, which
    is the same assumption the adapter makes for the mapped columns -- and it
    records that assumption as a semantic loss on every affected row, which is
    where a reader should look for it.
    """
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def _citable(path: Path) -> Path:
    """The repo-relative path when this process can still open it from the
    working directory, else the absolute one. A provenance record that cites
    `data/curated/panels/...` travels; one that cites a home directory does not."""
    relative = Path(_rel(path))
    return relative if (Path.cwd() / relative).exists() else path


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(_REPO_ROOT)).replace("\\", "/")
    except ValueError:  # pragma: no cover -- output dir outside the repo
        return str(path)


# --------------------------------------------------------------------------
# the walkthrough
# --------------------------------------------------------------------------


def run_walkthrough(
    output_dir: Path | str | None = None, *, quiet: bool = False
) -> WalkthroughResult:
    """Run every step and write the evidence bundle. Returns the computed result."""

    started = time.perf_counter()
    say = (lambda *a, **k: None) if quiet else print
    result = WalkthroughResult()

    out = Path(output_dir) if output_dir is not None else _DEFAULT_OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    for required in (EXPORT_PART1, EXPORT_PART2, NTD_ECONOMICS):
        if not required.exists():
            raise WalkthroughInputMissing(f"required input missing: {_rel(required)}")

    say(_RULE)
    say("MILEXIUM EVIDENCE WALKTHROUGH")
    say(_RULE)
    say("A messy operator-style export arrives -> what can be repaired is repaired and")
    say("recorded, what cannot is quarantined -> the survivors become canonical records")
    say("-> one scheduling decision is made and its reasons are recorded at decision")
    say("time -> the deadhead teardown measures what actually happened -> an evidence")
    say("bundle is exported and then RE-DERIVED from its own bytes.")
    say("")
    say("Status: Demonstrated. Nothing here is Validated -- that needs consented")
    say("operator data against a declared baseline, and Milexium has none. Zero")
    say("customers, zero pilots. Every number below is computed by this run.")
    say("")

    _preflight(say, result)
    client, adapter_ts = _new_client()
    _step_1_pii(say, result, adapter_ts)
    summary, rows2, accepted_rows = _step_2_intake(say, result, client, adapter_ts)
    canonical = _step_3_canonical(say, result, summary, rows2)
    decision = _step_4_decide(say, result, client, accepted_rows)
    teardown, segments = _step_5_teardown(say, result, accepted_rows)
    _step_6_drift(say, result)
    pack_path = _step_7_export(
        say, result, client, decision, teardown, segments, out, canonical
    )
    _step_8_rederive(say, result, pack_path)

    result.runtime_seconds = time.perf_counter() - started
    _summary(say, result)
    return result


def _new_client() -> tuple[MilexiumClient, datetime]:
    client = MilexiumClient.in_memory(
        tenant_name="Walkthrough tenant (synthetic export; not a real agency)"
    )
    return client, datetime.now(timezone.utc)


# --- 0. preflight ----------------------------------------------------------


def _preflight(say, result: WalkthroughResult) -> None:
    say(_RULE)
    say("STEP 0  PREFLIGHT  --  what this run does and does not depend on")
    say(_RULE)
    have_pg = importlib.util.find_spec("psycopg") is not None
    have_minio = importlib.util.find_spec("minio") is not None
    say("canonical store: in-memory SQLite (themis.canonical.SqliteCanonicalStore)")
    say(
        f"PostgreSQL driver installed: {'yes' if have_pg else 'no'}  |  "
        f"MinIO client installed: {'yes' if have_minio else 'no'}"
    )
    say("  Neither is used. The multi-tenant PostgreSQL path (ADR-0048) and the MinIO-")
    say("  backed estate (ADR-0032) exist and are tested elsewhere; this walkthrough")
    say("  deliberately exercises neither, so nothing below depends on infrastructure")
    say("  a viewer has not installed.")
    say("")
    say("REAL committed inputs (hashed now, from this checkout):")
    for path in (NTD_ECONOMICS, AAR_PANEL, WEATHER_PANEL):
        if path.exists():
            say(f"  REAL  {_rel(path)}  sha256={_sha256(path)[:16]}...  "
                f"{path.stat().st_size / 1e6:.1f} MB")
        else:
            say(f"  MISSING  {_rel(path)}  (step 6 will degrade and say so)")
    say("SYNTHETIC inputs (the filename carries the label):")
    for path in (EXPORT_PART1, EXPORT_PART2):
        say(f"  SYNTHETIC  {_rel(path)}  sha256={_sha256(path)[:16]}...")
    say("")


# --- 1. the first send is refused in full ---------------------------------


def _step_1_pii(say, result: WalkthroughResult, recorded_at: datetime) -> None:
    say(_RULE)
    say("STEP 1  INTAKE, FIRST SEND  --  REFUSAL #1: PII fails closed, ahead of")
    say("        everything else")
    say(_RULE)
    rows = _read_csv(EXPORT_PART1)
    # A separate in-memory client: the first send imports nothing, so nothing
    # from it may reach the tenant the rest of the walkthrough records against.
    client = MilexiumClient.in_memory(tenant_name="first send (nothing imported)")
    adapter = OperatorExportAdapter(
        client.tenant_id, recorded_at=recorded_at, column_map=COLUMN_MAP
    )
    summary = client.ingest(adapter, rows)

    result.part1_rows = len(rows)
    result.part1_accepted = summary.accepted
    result.part1_quarantined = summary.quarantined
    result.part1_pii_quarantines = sum(
        1 for q in summary.quarantined_rows if "direct rider/staff identifiers" in q.reason
    )

    say(f"source (SYNTHETIC): {EXPORT_PART1.name}")
    say(f"header: {', '.join(rows[0].keys())}")
    say("")
    say(f"rows submitted: {len(rows)}   imported: {summary.accepted}   "
        f"quarantined: {summary.quarantined}")
    say(f"of which quarantined on PII grounds: {result.part1_pii_quarantines}")
    say("")
    say("The whole file is refused, including the row whose RiderName cell is BLANK.")
    say("That is deliberate: the presence of the COLUMN means the export shape carries")
    say("personal data, and an all-blank column in a sample would hide a populated one")
    say("in the full extract. The check runs before parsing, before repair, before")
    say("every other validation -- a row carrying a direct identifier is rejected on")
    say("that ground even when everything else about it is clean.")
    say("")
    example = summary.quarantined_rows[0]
    say(f"quarantine reason (row {example.raw_row.get('BookingRef')}):")
    for line in _wrap(example.reason, 74):
        say(f"  {line}")
    say("")

    # The value must not survive into the quarantine record. Checked, not asserted.
    names = [r["RiderName"] for r in rows if r["RiderName"].strip()]
    phones = [r["RiderPhone"] for r in rows if r["RiderPhone"].strip()]
    serialized = json.dumps([q.raw_row for q in summary.quarantined_rows], default=str)
    leaked = [v for v in names + phones if v in serialized]
    result.part1_redaction_leaked = bool(leaked)
    say(f"redaction check, computed on the quarantine records this run produced:")
    say(f"  {len(names)} rider names and {len(phones)} phone numbers appeared in the file")
    say(f"  occurrences of those values inside the quarantine records: {len(leaked)}")
    say(f"  the marker written in their place: {REDACTION_MARKER!r}")
    say("  Every other column is preserved verbatim, so the operator can still see")
    say("  which rows were refused and re-send them once the columns are dropped.")
    say("")


# --- 2. the corrected re-send ---------------------------------------------


def _step_2_intake(say, result: WalkthroughResult, client: MilexiumClient, recorded_at: datetime):
    say(_RULE)
    say("STEP 2  INTAKE, CORRECTED RE-SEND  --  repair what is unambiguous,")
    say("        quarantine what is not")
    say(_RULE)
    rows = _read_csv(EXPORT_PART2)
    adapter = OperatorExportAdapter(
        client.tenant_id, recorded_at=recorded_at, column_map=COLUMN_MAP
    )
    summary = client.ingest(adapter, rows)
    report = build_ingest_report(adapter, rows)

    result.part2_rows = len(rows)
    result.part2_accepted = summary.accepted
    result.part2_quarantined = summary.quarantined
    result.semantic_loss_records = len(summary.semantic_loss)

    rules: dict[str, int] = {}
    for loss in summary.semantic_loss:
        rule = repair_rule_of(loss)
        if rule is not None:
            rules[rule] = rules.get(rule, 0) + 1
    result.part2_repair_rules = dict(sorted(rules.items()))
    result.part2_quarantine_codes = {r.code: r.count for r in report.quarantine_reasons}

    say(f"source (SYNTHETIC): {EXPORT_PART2.name}  --  the same operator's corrected")
    say("re-send with the two identifier columns dropped at source.")
    say("")
    say(f"HEADLINE (themis.connect.ingest_report, computed this run):")
    for line in _wrap(report.headline, 74):
        say(f"  {line}")
    say("")
    say(f"{'repair rule':<28}{'rows':>5}{'records':>8}   columns touched")
    for rule in report.repair_rules:
        say(f"{rule.rule:<28}{rule.rows:>5}{rule.records:>8}   "
            f"{', '.join(rule.columns)[:32]}")
    say("")
    say(f"{'quarantine reason':<30}{'rows':>6}   structural?")
    for reason in report.quarantine_reasons:
        say(f"{reason.code:<30}{reason.count:>6}   {'file artefact' if reason.structural else 'data defect'}")
    say("")
    say(f"semantic-loss records written: {len(summary.semantic_loss)} across "
        f"{summary.accepted} imported rows")
    say("  Every repair is one of them. Nothing was silently altered: each record names")
    say("  the rule, the original value and the repaired value, so a reviewer can undo")
    say("  any of them. Unmapped columns are recorded by NAME ONLY -- their values are")
    say("  never retained, because an unrecognised column is exactly where unanticipated")
    say("  personal data hides.")
    say("")

    say(_THIN)
    say("REFUSAL #2: the same column, two dates, two different verdicts.")
    say(_THIN)
    ambiguous = next(
        (q for q in summary.quarantined_rows if "both valid readings" in q.reason), None
    )
    result.ambiguous_date_quarantined = ambiguous is not None
    if ambiguous is not None:
        say(f"  QUARANTINED  {ambiguous.raw_row.get('BookingRef')}  "
            f"ReqDateTime={ambiguous.raw_row.get('ReqDateTime')!r}")
        for line in _wrap(ambiguous.reason.split(". Milexium repairs")[0], 72):
            say(f"    {line}")
    repaired = [
        loss for loss in summary.semantic_loss if repair_rule_of(loss) == "date_order_ddmm"
    ]
    result.unambiguous_date_repaired = bool(repaired)
    if repaired:
        say(f"  REPAIRED     ReqDateTime={repaired[0].source_value!r}")
        for line in _wrap(repaired[0].reason, 72):
            say(f"    {line}")
    say("  There is no thirteenth month, so 13/04/2026 has exactly one reading and is")
    say("  repaired with the rule recorded. 03/04/2026 has two, and nothing in the file")
    say("  says which. Picking one silently is the failure this refuses: it would move")
    say("  a trip a month and no downstream number would look wrong.")
    say("")

    quarantined_refs = {q.raw_row.get("BookingRef") for q in summary.quarantined_rows}
    accepted_rows = [r for r in rows if r["BookingRef"] not in quarantined_refs]
    return summary, rows, accepted_rows


# --- 3. canonical ----------------------------------------------------------


def _step_3_canonical(say, result: WalkthroughResult, summary, rows: list[dict]):
    say(_RULE)
    say("STEP 3  CANONICAL  --  the survivors become records, and the count closes")
    say(_RULE)
    records = summary.records
    denied = [r for r in records if r.request.status.value == "denied"]
    no_show = [r for r in records if r.request.status.value == "no_show"]
    result.canonical_requests = len(records)
    result.canonical_denied = len(denied)
    result.canonical_no_show = len(no_show)
    result.conservation_holds = (summary.accepted + summary.quarantined) == len(rows)

    say(f"rows submitted {len(rows)} = imported {summary.accepted} + quarantined "
        f"{summary.quarantined}  ->  conservation holds: {result.conservation_holds}")
    say("  No row is dropped. A row is either a canonical record or a quarantine record")
    say("  carrying its own reason; there is no third outcome and no silent discard.")
    say("")
    say(f"canonical ServiceRequest + Outcome pairs: {len(records)}")
    say(f"  of which terminal status DENIED:  {len(denied)}   NO_SHOW: {len(no_show)}")
    say("  A denial is a record, not an absence. That is the whole reason a denial can")
    say("  be counted, explained and audited later.")
    say("")
    sample = records[0]
    say("one record, in full (SYNTHETIC source row, real canonical mapping):")
    say(f"  request_id     {sample.request.request_id}")
    say(f"  rider_ref      {sample.request.rider_ref}")
    say("                 (no rider column was sent, so this is a deterministic")
    say("                  per-trip placeholder -- never a joinable identity)")
    say(f"  zones          {sample.request.pickup_zone} -> {sample.request.dropoff_zone}")
    say(f"  requested_at   {sample.request.times.requested_at.isoformat()}")
    say(f"  scheduled_at   {sample.request.times.scheduled_pickup_at.isoformat()}")
    say(f"  actual_pickup  {sample.request.times.actual_pickup_at}")
    say(f"  status         {sample.request.status.value}")
    say(f"  outcome.vehicle_ref/run_ref  {sample.outcome.vehicle_ref} / {sample.outcome.run_ref}")
    say(f"  outcome.on_time              {sample.outcome.on_time}  <- left None on purpose:")
    say("       on-time depends on the agency's own window (commonly -0/+30 min), which")
    say("       is a policy parameter no export carries. Computing it would be a guess")
    say("       dressed as a measurement.")
    say("")
    return records


# --- 4. one decision, with its reasons ------------------------------------


@dataclass(frozen=True)
class _Decision:
    aggregate_id: str
    solution: object
    problem: object
    alternatives: tuple[dict, ...]
    denial_reason_codes: tuple[str, ...]


def _step_4_decide(say, result: WalkthroughResult, client: MilexiumClient, accepted_rows):
    say(_RULE)
    say("STEP 4  DECIDE  --  one real scheduling question, with the reasons recorded")
    say("        at decision time")
    say(_RULE)

    denied_row = next(r for r in accepted_rows if r["TripStatus"].strip().lower() == "denied")
    run_rows = [
        r
        for r in accepted_rows
        if r["RunID"] == denied_row["RunID"] and r["ActualPU"] and r["ActualDO"]
    ]

    say(f"The export says trip {denied_row['BookingRef']} was DENIED on run "
        f"{denied_row['RunID']}.")
    say("It does not say why -- the intake column list carries no denial reason at all.")
    say("So we pose the decision the dispatcher faced and let the")
    say("shipped solver answer it, recording what it decided AND why at the moment it")
    say("decided.")
    say("")
    say("REAL (from the export): every performed trip's observed pickup and dropoff")
    say("  time, pinned exactly -- each becomes a request whose pickup window is the")
    say("  single minute it actually happened and whose ride time is the duration it")
    say("  actually took. The denied trip's requested pickup time is likewise the")
    say("  export's own.")
    say("SYNTHETIC (labelled): a 20-minute pickup window and a 35-minute ride on the")
    say("  denied request, one ambulatory seat per vehicle, and must_serve=False on")
    say("  that request. The last one matters -- see the refusal below.")
    say("Each vehicle's shift is the envelope of its own observed activity plus five")
    say("  minutes; the export carries no pull-out or pull-in, so that is a FLOOR on")
    say("  the real shift, not the shift. The problem carries the denied trip's own run")
    say("  and all three vehicles: the other two are in it so the solver, not this")
    say("  narration, gets to say whether they could have taken it.")
    say("")

    policy = DecisionPolicy(
        policy_id=new_id(PolicyId),
        name="walkthrough-late-booking",
        time_granularity_minutes=1,
        max_search_nodes=500_000,
    )
    # Every performed trip becomes a MUST-SERVE request pinned to the minute it
    # actually happened: it is not a candidate the solver may trade away, it is
    # a fact. The only open question is whether the late booking fits on top.
    performed: dict[str, list[RideRequest]] = {}
    for row in run_rows:
        pu, do = _utc(row["ActualPU"]), _utc(row["ActualDO"])
        duration = (do - pu).total_seconds() / 60.0
        performed.setdefault(row["VehicleNo"], []).append(
            RideRequest(
                request_id=_fresh_request_id(),
                pickup_window_start=pu,
                pickup_window_end=pu,
                dropoff_window_end=do,
                nominal_ride_time_minutes=duration,
                max_ride_time_minutes=duration,
                must_serve=True,
            )
        )
    pinned = [request for requests in performed.values() for request in requests]
    late_pickup = _utc(denied_row["SchedPU"])
    late = RideRequest(
        request_id=_fresh_request_id(),
        pickup_window_start=late_pickup,
        pickup_window_end=late_pickup + timedelta(minutes=20),
        dropoff_window_end=late_pickup + timedelta(minutes=75),
        nominal_ride_time_minutes=35.0,
        max_ride_time_minutes=52.5,
        must_serve=False,
    )
    requests = tuple(pinned) + (late,)

    shifts = _vehicle_shifts(accepted_rows)
    vehicles = tuple(
        DecisionVehicle(
            vehicle_id=new_id(VehicleId),
            capacity_ambulatory=1,
            capacity_wheelchair=1,
            shift_start=start,
            shift_end=end,
        )
        for _, (start, end) in shifts
    )
    vehicle_labels = [label for label, _ in shifts]
    committed_for = {
        label: tuple(performed.get(label, ())) for label in vehicle_labels
    }
    problem = DecisionProblem(
        tenant_id=client.tenant_id, policy=policy, vehicles=vehicles, requests=requests
    )
    solution = solve(problem)
    violations = check_feasibility(problem, solution)

    result.decision_status = solution.status.value
    result.decision_proven_optimal = solution.proven_optimal
    result.decision_served = len(solution.assignments)
    result.decision_denied = len(solution.unserved)
    result.feasibility_violations = len(violations)

    say(f"requests: {len(requests)} ({len(pinned)} pinned to what actually happened + "
        f"1 late booking)  vehicles: {len(vehicles)}")
    say(f"solver: {solution.solver_name} {solution.solver_version}  status "
        f"{solution.status.value.upper()}  proven_optimal={solution.proven_optimal}")
    say(f"served {len(solution.assignments)}/{len(requests)}, denied {len(solution.unserved)}")
    say(f"independent feasibility check (metis.decide.feasibility -- it never imports")
    say(f"  the solver): {len(violations)} violations -> "
        f"{'PASS' if not violations else 'FAIL'}")
    say("")

    denial_codes: tuple[str, ...] = ()
    if solution.unserved:
        denial = solution.unserved[0]
        denial_codes = tuple(code.value for code in denial.reason_codes)
        say(f"DENIED at decision time, with the solver's own hard-constraint codes:")
        say(f"  {', '.join(denial_codes)}")
        say("  These are enum reason codes from the constraint that actually bound --")
        say("  not SHAP output, not generated prose, not a post-hoc explanation.")
    result.denial_reason_codes = denial_codes
    say("")

    say(_THIN)
    say("WHY NOT THE OTHER VEHICLES -- each candidate probed, not asserted.")
    say(_THIN)
    # The alternatives travel in the RECOMMENDATION payload and are validated
    # against the canonical `DecisionAlternative` shape by the evidence builder
    # (ADR-0009). GAP, reported not fixed: `decision_alternatives` is a real
    # canonical table with a store writer, but no public store method creates
    # the parent `schedule_runs` row it foreign-keys to, so the table cannot be
    # written through the supported API and the payload convention stands.
    schedule_run_id = new_id(ScheduleRunId)
    alternatives: list[dict] = []
    for label, vehicle in zip(vehicle_labels, vehicles):
        theirs = committed_for[label]
        probe = DecisionProblem(
            tenant_id=client.tenant_id,
            policy=policy,
            vehicles=(vehicle,),
            requests=theirs + (late,),
        )
        probe_solution = solve(probe)
        served = any(a.request_id == late.request_id for a in probe_solution.assignments)
        codes = tuple(
            code.value
            for denial in probe_solution.unserved
            if denial.request_id == late.request_id
            for code in denial.reason_codes
        )
        alternatives.append(
            {
                "schedule_run_id": str(schedule_run_id),
                "request_id": str(late.request_id),
                "candidate_vehicle_id": str(vehicle.vehicle_id),
                "feasible": served,
                "failed_constraints": list(codes),
                "objective_delta": probe_solution.objective_value,
            }
        )
        say(f"  {label} (observed shift {vehicle.shift_start.strftime('%H:%M')}-"
            f"{vehicle.shift_end.strftime('%H:%M')} UTC, {len(theirs)} committed trip(s))"
            f"  feasible={served}  {', '.join(codes) if codes else ''}")
    result.alternatives_probed = len(alternatives)
    result.infeasible_alternatives = sum(1 for a in alternatives if not a["feasible"])
    say("  Each line is a separate solve of a one-vehicle problem, run now. The reason")
    say("  codes are what that solve returned -- and they carry more than the aggregate")
    say("  denial above: the whole-problem denial reports SHIFT_END, which is true of")
    say("  two vehicles and silent about the third, whose actual obstacle was capacity.")
    say("  That is why the alternatives are recorded separately rather than being")
    say("  summarised into the denial's own codes.")
    say("")

    say(_THIN)
    say("REFUSAL #3: the operator's denial keeps its own (missing) reason.")
    say(_THIN)
    say("  The export's DENIED row carries no reason, and Milexium does NOT copy the")
    say("  reason it just computed onto it. Two different facts: what the operator's")
    say("  system decided (reason unknown, and it stays unknown) and what Milexium's")
    say("  solver decided when posed the same problem (reason recorded). Back-filling")
    say("  the first from the second would manufacture an audit trail for a decision")
    say("  nobody at Milexium made.")
    say("  Related, and stated rather than papered over: the intake column list carries")
    say("  no ADA-mandate flag, so this demo assumes must_serve=False. An ADA")
    say("  complementary-paratransit trip that cannot be scheduled is an INFEASIBLE")
    say("  instance, not a denial -- and the export cannot tell us which this was.")
    say("")

    aggregate_id = f"walkthrough-late-booking-{denied_row['BookingRef']}"
    client.record_decision(
        aggregate_id=aggregate_id,
        actor_id="milexium-decide@0.1",
        reason_codes=tuple(ReasonCode(code) for code in denial_codes),
        payload={
            "policy_version": policy.name,
            "solver_status": solution.status.value,
            "solver_proven_optimal": solution.proven_optimal,
            "requests_considered": len(requests),
            "vehicles_considered": len(vehicles),
            "alternatives_method": (
                "each candidate vehicle was solved as its own one-vehicle problem "
                "carrying that vehicle's already-committed trips; failed_constraints "
                "are the reason codes that probe returned"
            ),
            "alternatives": alternatives,
        },
    )
    client.store.append_event(
        tenant_id=client.tenant_id,
        aggregate_id=aggregate_id,
        aggregate_type="ServiceRequest",
        occurred_at=datetime.now(timezone.utc),
        actor_type="system",
        actor_id="milexium-decide@0.1",
        event_type=DecisionEventType.REJECTION,
        payload={
            "denied_request": str(late.request_id),
            "pickup_window": [
                late.pickup_window_start.isoformat(),
                late.pickup_window_end.isoformat(),
            ],
            "source_export_row": denied_row["BookingRef"],
            "note": (
                "Milexium's own denial of the posed problem. The operator export's "
                "denial reason is unknown and is NOT recorded here as if it were this one."
            ),
        },
        reason_codes=tuple(ReasonCode(code) for code in denial_codes),
    )
    client.record_override(
        aggregate_id=aggregate_id,
        actor_id="demo-dispatcher (synthetic actor)",
        payload={
            "decision": "denial upheld",
            "note": (
                "human review recorded verbatim; the reviewer did not change the "
                "outcome and the record says so"
            ),
        },
    )
    packet = client.evidence_for(aggregate_id)
    result.ledger_events = len(packet.proposed) + len(packet.approved_or_overridden)
    result.ledger_integrity_verified = packet.integrity_verified
    result.ledger_chain_violations = len(packet.chain_violations)

    say("recorded on the append-only, hash-chained ledger:")
    say(f"  aggregate {aggregate_id}")
    say("  RECOMMENDATION (system, carrying every probed alternative)")
    say("  REJECTION      (system, carrying the solver's reason codes)")
    say("  OVERRIDE       (human, denial upheld, recorded verbatim)")
    say(f"  events on the chain: {result.ledger_events}")
    say(f"  alternatives parsed back out of the payload as canonical "
        f"DecisionAlternatives: {len(packet.alternatives_considered)}")
    say(f"  the decision that stood: "
        f"{packet.executed.event_type.value} by "
        f"{packet.executed.actor_type}:{packet.executed.actor_id}")
    say(f"  integrity_verified (hash chain + schema): {packet.integrity_verified}")
    say(f"  chain violations: {len(packet.chain_violations)}")
    say("")

    return _Decision(
        aggregate_id=aggregate_id,
        solution=solution,
        problem=problem,
        alternatives=tuple(alternatives),
        denial_reason_codes=denial_codes,
    )


def _fresh_request_id():
    from themis.canonical import RequestId

    return new_id(RequestId)


def _vehicle_shifts(accepted_rows) -> list[tuple[str, tuple[datetime, datetime]]]:
    """One shift envelope per vehicle in the export, from its own observed first
    and last activity plus a five-minute pad. REAL boundaries, SYNTHETIC pad --
    the export carries no pull-out or pull-in time, so a run's real shift is
    wider than this by an unknown amount, and this envelope is a floor on it."""
    by_vehicle: dict[str, list[datetime]] = {}
    for row in accepted_rows:
        if not (row["ActualPU"] and row["ActualDO"]):
            continue
        by_vehicle.setdefault(row["VehicleNo"], []).extend(
            [_utc(row["ActualPU"]), _utc(row["ActualDO"])]
        )
    return [
        (label, (min(stamps) - timedelta(minutes=5), max(stamps) + timedelta(minutes=5)))
        for label, stamps in sorted(by_vehicle.items())
    ]


# --- 5. the teardown ------------------------------------------------------


def _step_5_teardown(say, result: WalkthroughResult, accepted_rows):
    say(_RULE)
    say("STEP 5  TEARDOWN  --  where the empty vehicle time actually sat, valued at a")
    say("        REAL published rate")
    say(_RULE)

    say("GAP FOUND WHILE WIRING THIS UP, reported rather than worked around: the")
    say("canonical intake column list has no trip END time, and neither does Outcome.")
    say("The deadhead teardown chains one vehicle's consecutive trips, so it needs one.")
    say("This step therefore reads the export's unmapped ActualDO column DIRECTLY,")
    say("outside the canonical path. Milexium's own canonical records cannot currently")
    say("drive its own teardown. Nothing in app/ was changed to hide that.")
    say("")

    segments, revenue_n, deadhead_n, unmeasured, unmeasured_reason = _build_segments(accepted_rows)
    result.segments = len(segments)
    result.revenue_segments = revenue_n
    result.deadhead_segments = deadhead_n
    result.unmeasured_segments = unmeasured

    cost_per_vrh, agency_count, dh_median, dh_p90 = _ntd_cost_basis()
    result.ntd_cost_per_vrh = cost_per_vrh
    result.ntd_agency_count = agency_count
    result.ntd_deadhead_median = dh_median
    result.ntd_deadhead_p90 = dh_p90

    say(f"segments built: {len(segments)}  ({revenue_n} revenue, {deadhead_n} empty)")
    say(f"segments NOT measured: {unmeasured}")
    for line in _wrap(unmeasured_reason, 74):
        say(f"  {line}")
    say("")

    dataset_label = (
        f"SYNTHETIC operator export {EXPORT_PART2.name} "
        f"(sha256 {_sha256(EXPORT_PART2)[:16]}...), one service day"
    )

    # First: no fixed-versus-variable split supplied.
    bare_basis = CostBasis(
        cost_per_vehicle_hour=cost_per_vrh,
        source=(
            f"REAL: median cost_per_vrh across {agency_count} demand-response agencies in "
            f"the 2024 FTA National Transit Database (forge/business/ntd/agency_economics.csv, "
            f"sha256 {_sha256(NTD_ECONOMICS)[:16]}...). A national stand-in rate, not this "
            "(synthetic) operator's own books"
        ),
    )
    bare = _run_teardown(segments, dataset_label, bare_basis, unmeasured, unmeasured_reason)
    result.envelope_without_split = bare.cost.envelope_basis

    say(_THIN)
    say("REFUSAL #4: no savings number without the operator's own cost split.")
    say(_THIN)
    say(f"  cost per vehicle-hour used: ${cost_per_vrh:,.2f}  (REAL, NTD 2024 median "
        f"across {agency_count} DR agencies)")
    say(f"  accounting value of the empty time: ${bare.cost.value_at_full_cost:,.2f}")
    say(f"  modelled envelope: {bare.cost.modelled_envelope_low} .. "
        f"{bare.cost.modelled_envelope_high}")
    for line in _wrap(bare.cost.envelope_basis, 72):
        say(f"    {line}")
    say("  Asked for a savings envelope with no fixed-versus-variable split, the")
    say("  teardown returns none and says why. There is no default for that split")
    say("  because nobody outside an operator's finance office knows it.")
    say("")

    # Second: an explicitly-labelled illustrative split.
    low, high = ILLUSTRATIVE_AVOIDABLE_SHARE
    basis = CostBasis(
        cost_per_vehicle_hour=cost_per_vrh,
        source=bare_basis.source,
        avoidable_share_low=low,
        avoidable_share_high=high,
    )
    teardown = _run_teardown(segments, dataset_label, basis, unmeasured, unmeasured_reason)
    cost = teardown.cost
    result.value_at_full_cost = cost.value_at_full_cost
    result.envelope_low = cost.modelled_envelope_low
    result.envelope_high = cost.modelled_envelope_high
    result.is_guaranteed_saving = cost.is_guaranteed_saving
    result.total_deadhead_minutes = teardown.total_deadhead_minutes
    result.total_revenue_minutes = teardown.total_revenue_minutes
    result.deadhead_share = teardown.deadhead_share_of_vehicle_time
    result.attributed_run_count = teardown.attributed_run_count
    result.unattributable_deadhead_minutes = (
        0.0 if teardown.unattributable is None else teardown.unattributable.deadhead_minutes
    )

    say("WHAT HAPPENED (all figures computed from the SYNTHETIC export just parsed):")
    say(f"  empty vehicle minutes:   {teardown.total_deadhead_minutes:,.1f}")
    say(f"  revenue vehicle minutes: {teardown.total_revenue_minutes:,.1f}")
    say(f"  empty share of measured vehicle time: "
        f"{teardown.deadhead_share_of_vehicle_time:.1%}  (SYNTHETIC data)")
    say(f"  REAL peer distribution, 2024 NTD demand-response filings: median "
        f"{dh_median:.1%}, p90 {dh_p90:.1%}")
    say("  The peer numbers are real and public. The share above them is synthetic and")
    say("  is evidence about this file only. The two are printed together because the")
    say("  comparison is the product -- the peer distribution is public and nobody")
    say("  computes it for an operator.")
    say("")
    say("WHICH HOURS (top 3 by empty minutes, of 24 hour-of-day buckets):")
    for bucket in sorted(
        teardown.by_hour_of_day, key=lambda b: b.deadhead_minutes, reverse=True
    )[:3]:
        say(f"  {bucket.hour_of_day:02d}:00   empty {bucket.deadhead_minutes:6.1f} min   "
            f"{bucket.share_of_total_deadhead:.1%} of all empty time")
    say("")
    say("WHICH RUNS:")
    for run in teardown.top_runs:
        say(f"  {run.run_ref:<12} empty {run.deadhead_minutes:6.1f} min   "
            f"{run.share_of_total_deadhead:.1%}   segments {run.segment_count}")
    say("")
    say(_THIN)
    say("REFUSAL #5: the unattributable empty time stays unattributable.")
    say(_THIN)
    if teardown.unattributable is not None:
        u = teardown.unattributable
        say(f"  run_ref = {u.run_ref}   empty {u.deadhead_minutes:.1f} min   "
            f"{u.share_of_total_deadhead:.1%} of all empty time   segments {u.segment_count}")
    attributed = sum(r.deadhead_minutes for r in teardown.top_runs)
    total_check = attributed + result.unattributable_deadhead_minutes
    result.attribution_reconciles = abs(total_check - teardown.total_deadhead_minutes) < 1e-6
    say(f"  attributed {attributed:.1f} + unattributable "
        f"{result.unattributable_deadhead_minutes:.1f} = {total_check:.1f} minutes, "
        f"equals the total {teardown.total_deadhead_minutes:.1f}: "
        f"{result.attribution_reconciles}")
    say("  One vehicle's rows name no run. Its empty time is real and measurable but")
    say("  cannot be attributed, so it sits in its own row -- never merged into a run")
    say("  that did not incur it, never dropped, and reported OUTSIDE the ranking so a")
    say("  top-N truncation cannot bury it. A fabricated run id would have made the")
    say("  ranking look complete and been wrong.")
    say("")
    say("HOW MUCH -- and how much of it is not a promise:")
    say(f"  empty hours: {cost.deadhead_hours:,.2f}")
    say(f"  accounting value at the REAL NTD rate: ${cost.value_at_full_cost:,.2f}")
    say(f"  modelled envelope: ${cost.modelled_envelope_low:,.2f} .. "
        f"${cost.modelled_envelope_high:,.2f}")
    say(f"    using a {low:.0%}-{high:.0%} avoidable share, ILLUSTRATIVE and labelled --")
    say("    not measured, not a Milexium default, and the model refuses to have one")
    say(f"  is_guaranteed_saving: {cost.is_guaranteed_saving}")
    say("    -- and it cannot be anything else: setting that field True raises.")
    for line in _wrap(cost.hedge, 72):
        say(f"    {line}")
    say("")
    return teardown, segments


def _build_segments(accepted_rows):
    """Chain each vehicle's consecutive trips into revenue and empty segments."""
    by_vehicle: dict[str, list[dict]] = {}
    unmeasurable_trips = 0
    for row in accepted_rows:
        if row["ActualPU"] and row["ActualDO"]:
            by_vehicle.setdefault(row["VehicleNo"], []).append(row)
        else:
            unmeasurable_trips += 1

    segments: list[VehicleSegment] = []
    revenue_n = deadhead_n = 0
    long_gaps = 0
    for _, rows in sorted(by_vehicle.items()):
        rows = sorted(rows, key=lambda r: r["ActualPU"])
        previous_end: datetime | None = None
        for row in rows:
            start, end = _utc(row["ActualPU"]), _utc(row["ActualDO"])
            run_ref = row["RunID"].strip() or None
            if previous_end is not None:
                gap = (start - previous_end).total_seconds() / 60.0
                if 0 < gap <= MAX_CHAINED_GAP_MINUTES:
                    segments.append(
                        VehicleSegment(
                            started_at=previous_end,
                            ended_at=start,
                            kind="deadhead",
                            run_ref=run_ref,
                        )
                    )
                    deadhead_n += 1
                elif gap > MAX_CHAINED_GAP_MINUTES:
                    long_gaps += 1
            segments.append(
                VehicleSegment(started_at=start, ended_at=end, kind="revenue", run_ref=run_ref)
            )
            revenue_n += 1
            previous_end = end

    reason = (
        f"{unmeasurable_trips} imported trip(s) carry no observed pickup/dropoff pair "
        f"(a no-show and a denial still consumed vehicle time that this export cannot "
        f"measure), and {long_gaps} gap(s) longer than {MAX_CHAINED_GAP_MINUTES:.0f} "
        "minutes were excluded because a trip export cannot distinguish empty running "
        "from a break or a layover. Both are excluded and counted here rather than "
        "counted as zero empty time. Pull-out before the first trip and pull-in after "
        "the last are invisible to this source entirely."
    )
    return segments, revenue_n, deadhead_n, unmeasurable_trips + long_gaps, reason


def _run_teardown(segments, dataset_label, cost_basis, unmeasured, unmeasured_reason):
    from aletheia.replay.teardown import teardown_deadhead

    return teardown_deadhead(
        segments,
        dataset_label=dataset_label,
        data_provenance="synthetic",
        run_ref_source=(
            "RunID as the (synthetic) export writes it; rows naming only a vehicle "
            "unit number carry no run and land in the unattributable row"
        ),
        cost_basis=cost_basis,
        unmeasured_segments=unmeasured,
        unmeasured_reason=unmeasured_reason,
    )


def _ntd_cost_basis() -> tuple[float, int, float, float]:
    """Median cost per vehicle-revenue-hour and the deadhead-share distribution,
    computed now from the committed 2024 NTD demand-response filings."""
    rates: list[float] = []
    shares: list[float] = []
    with NTD_ECONOMICS.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("report_year") != "2024":
                continue
            try:
                rate = float(row["cost_per_vrh"])
            except (TypeError, ValueError):
                rate = 0.0
            if rate > 0:
                rates.append(rate)
            try:
                share = float(row["deadhead_pct_hours"])
            except (TypeError, ValueError):
                share = -1.0
            if 0.0 <= share < 1.0:
                shares.append(share)
    shares.sort()
    p90 = shares[min(len(shares) - 1, int(round(0.9 * (len(shares) - 1))))]
    return (
        round(statistics.median(rates), 3),
        len(rates),
        statistics.median(shares),
        p90,
    )


# --- 6. the interval withdraws its own guarantee --------------------------


def _step_6_drift(say, result: WalkthroughResult) -> None:
    say(_RULE)
    say("STEP 6  SERVE-TIME DRIFT  --  REFUSAL #6: the interval withdraws its own")
    say("        coverage guarantee (ADR-0049)")
    say(_RULE)

    if not (AAR_PANEL.exists() and WEATHER_PANEL.exists()):
        say("SKIPPED, cleanly: the committed panels are not on disk in this checkout")
        say(f"  ({_rel(AAR_PANEL)}, {_rel(WEATHER_PANEL)}).")
        say("  Nothing is fabricated in their place and the run continues.")
        say("")
        return
    if importlib.util.find_spec("numpy") is None:  # pragma: no cover -- numpy is a hard dep
        say("SKIPPED, cleanly: numpy is not installed, so PSI/KS cannot be computed.")
        say("")
        return

    from themis.canonical import ModelVersion, ModelVersionId, TenantId
    from metis.forecast.features import feature_names_for
    from metis.forecast.serve_drift import (
        assess_drift,
        derive_reference_from_rows,
        reference_from_model_artifact,
    )

    names = feature_names_for("zone_hour_demand_v1")
    rows = _aar_feature_rows()
    ref_rows = [r for r in rows if DRIFT_REFERENCE_WINDOW[0] <= r["day"] <= DRIFT_REFERENCE_WINDOW[1]]
    serving_rows = [r for r in rows if DRIFT_SERVING_WINDOW[0] <= r["day"] <= DRIFT_SERVING_WINDOW[1]]
    shuffled = list(range(len(ref_rows)))
    random.Random(DRIFT_SPLIT_SEED).shuffle(shuffled)
    half = len(shuffled) // 2
    reference_half = [ref_rows[i] for i in sorted(shuffled[:half])]
    control_half = [ref_rows[i] for i in sorted(shuffled[half:])]

    probe = ModelVersion(
        model_version_id=new_id(ModelVersionId),
        tenant_id=new_id(TenantId),
        task="forecast.demand",
        training_data_manifest_hash="0" * 64,
        feature_schema_version="zone_hour_demand_v1",
        evaluation_window_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        evaluation_window_end=datetime(2024, 2, 29, tzinfo=timezone.utc),
        artifact_hash="0" * 64,
    )
    carried = reference_from_model_artifact(probe)
    result.artifact_carried_reference = carried is not None
    say("First, we ask the registered model artifact for its own training reference")
    say(f"distribution. It returns: {carried}.")
    say("  ModelVersion records a training-data manifest hash, a feature schema version")
    say("  and an evaluation window -- but no per-feature reference distribution. The")
    say("  code says so and returns nothing rather than inventing a plausible baseline.")
    say("  So the reference is DERIVED from a committed panel, and its provenance")
    say("  records the panel path, its sha256, the window and the seed.")
    say("")

    reference = derive_reference_from_rows(
        reference_half,
        names,
        source_kind="committed_panel",
        description=(
            f"REAL NYC MTA Access-A-Ride borough-hour trips, {DRIFT_BOROUGH}, "
            f"{DRIFT_REFERENCE_WINDOW[0]}..{DRIFT_REFERENCE_WINDOW[1]}"
        ),
        derivation=(
            "borough-hour trip counts summed across provider types; calendar features "
            "from the timestamp; tmax_c/tmin_c/precip_mm/snow_cm joined from the "
            "committed NOAA daily panel for NYC; lag1/lag7/lag14/roll28 computed over "
            "the borough-hour series in units of hours; a seeded random half of the "
            "window retained (the other half is the exchangeable control)"
        ),
        panel_path=_citable(AAR_PANEL),
        model_version=probe,
        training_window_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        training_window_end=datetime(2024, 2, 29, tzinfo=timezone.utc),
        max_sample=None,
    )
    result.drift_assessed = True
    result.drift_reference_rows = reference.n_rows
    result.drift_skipped_features = tuple(
        name for name, _ in reference.provenance.skipped_features
    )

    say(f"reference: {reference.provenance.trace()}")
    say(f"features covered: {len(reference.feature_names)} of {len(names)} in the schema")
    for name, why in reference.provenance.skipped_features:
        say(f"  NOT covered: {name} -- {why}")
    say("")

    control = assess_drift(reference, control_half, target_coverage=DRIFT_TARGET_COVERAGE)
    serving = assess_drift(reference, serving_rows, target_coverage=DRIFT_TARGET_COVERAGE)
    result.drift_control_status = control.status
    result.drift_control_guarantee = control.interval_guarantee
    result.drift_serving_status = serving.status
    result.drift_serving_guarantee = serving.interval_guarantee
    result.drifted_features = serving.drifted_features

    say(f"CONTROL  serving window = the other seeded half of the SAME window "
        f"({control.n_serving_rows} rows, REAL)")
    say(f"  status={control.status}  interval_guarantee={control.interval_guarantee}")
    for line in _wrap(control.reason, 72):
        say(f"    {line}")
    say("")
    say(f"REAL SERVE  serving window = {DRIFT_SERVING_WINDOW[0]}..{DRIFT_SERVING_WINDOW[1]}, "
        f"same borough ({serving.n_serving_rows} rows, REAL)")
    say(f"  status={serving.status}  interval_guarantee={serving.interval_guarantee}")
    say(f"  {'feature':<12}{'PSI':>10}{'band':>13}{'KS p':>12}  flagged")
    for feature in serving.features:
        if not feature.computable:
            say(f"  {feature.feature:<12}{'n/a':>10}{'':>13}{'':>12}  {feature.note}")
            continue
        # A feature CAN be computable with no PSI (a constant reference makes the
        # statistic undefined while KS still runs). Rendered as "n/a" with the
        # monitor's own note rather than crashing or printing a zero.
        psi = "n/a" if feature.psi is None else f"{feature.psi:.4f}"
        band = feature.psi_band or (feature.note or "")[:13]
        p_value = "n/a" if feature.ks_p_value is None else f"{feature.ks_p_value:.2e}"
        say(f"  {feature.feature:<12}{psi:>10}{band:>13}{p_value:>12}  "
            f"{'YES' if feature.flagged else ''}")
    say("  Read the table, not just the verdict: `month` is flagged by KS alone, on two")
    say("  windows that are simply different months, while its PSI reads 0.0 because a")
    say("  near-constant calendar column collapses into one quantile bin. The weather")
    say("  and lag features are the ones carrying a real effect size. The monitor")
    say("  publishes both statistics per feature so a reader can see that.")
    say("")
    if serving.interval_caveat:
        for line in _wrap(serving.interval_caveat, 74):
            say(f"  {line}")
    say("")
    say("  This is the refusal. The forecast is still served and the interval is still")
    say("  reported UNCHANGED -- the monitor annotates, it does not decide. What it")
    say("  withdraws is the CLAIM: a split-conformal interval is distribution-free only")
    say("  under exchangeability, and measured input drift is direct evidence against")
    say("  that premise. The control above shows the same monitor saying 'unqualified'")
    say("  when the data is exchangeable, so this is a test that can come back either")
    say("  way, not a warning that is always on.")
    say("")


def _aar_feature_rows() -> list[dict]:
    """Build zone_hour_demand_v1-shaped feature rows from the two committed real
    panels. Everything here is REAL: the trip counts are NYC MTA Access-A-Ride
    borough-hour totals, the weather is the committed NOAA daily panel for NYC."""
    weather: dict[str, dict] = {}
    with WEATHER_PANEL.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["city"] == "nyc":
                weather[row["date"]] = row

    totals: dict[tuple[str, int], int] = {}
    with gzip.open(AAR_PANEL, "rt", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["borough"] != DRIFT_BOROUGH:
                continue
            key = (row["day"], int(row["hour"]))
            totals[key] = totals.get(key, 0) + int(row["trips"])

    keys = sorted(totals)
    values = [totals[k] for k in keys]
    rows: list[dict] = []
    for index, (day, hour) in enumerate(keys):
        if index < 28:
            continue
        daily = weather.get(day)
        if daily is None:
            continue
        when = date.fromisoformat(day)
        rows.append(
            {
                "day": day,
                "hour": float(hour),
                "hour_sin": math.sin(2 * math.pi * hour / 24),
                "hour_cos": math.cos(2 * math.pi * hour / 24),
                "dow": float(when.weekday()),
                "month": float(when.month),
                "is_weekend": 1.0 if when.weekday() >= 5 else 0.0,
                "tmax_c": float(daily["tmax_c"]),
                "tmin_c": float(daily["tmin_c"]),
                "precip_mm": float(daily["precip_mm"]),
                "snow_cm": float(daily["snow_cm"]),
                "lag1": float(values[index - 1]),
                "lag7": float(values[index - 7]),
                "lag14": float(values[index - 14]),
                "roll28": sum(values[index - 28 : index]) / 28.0,
                "borough": DRIFT_BOROUGH,
            }
        )
    return rows


# --- 7. export -------------------------------------------------------------


def _step_7_export(say, result, client, decision, teardown, segments, out: Path, canonical):
    say(_RULE)
    say("STEP 7  EXPORT  --  the evidence bundle")
    say(_RULE)

    events = client.store.history(client.tenant_id, decision.aggregate_id)
    raw_rows = client.store.raw_rows_for_tenant(client.tenant_id)
    evidence = capture_teardown(teardown, segments)
    pack = build_evidence_pack(events, raw_rows, teardown=evidence)

    pack_path = out / "evidence_pack.json"
    manifest_path = out / "run_manifest.json"
    pack_path.write_text(pack.to_json(), encoding="utf-8")

    manifest = {
        "demo": "milexium.walkthrough",
        "status_label": "Demonstrated -- never Validated (no consented operator data exists)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "real_inputs": {
            "ntd_agency_economics": {
                "path": _rel(NTD_ECONOMICS),
                "sha256": _sha256(NTD_ECONOMICS),
                "used_for": "cost per vehicle-revenue-hour and the peer deadhead distribution",
                "cost_per_vehicle_hour_median_2024_dr": result.ntd_cost_per_vrh,
                "agencies": result.ntd_agency_count,
            },
            "aar_hourly_borough_panel": {
                "path": _rel(AAR_PANEL),
                "sha256": _sha256(AAR_PANEL) if AAR_PANEL.exists() else None,
                "used_for": "serve-time drift reference and serving window",
            },
            "weather_daily_panel": {
                "path": _rel(WEATHER_PANEL),
                "sha256": _sha256(WEATHER_PANEL) if WEATHER_PANEL.exists() else None,
                "used_for": "the weather features of zone_hour_demand_v1",
            },
        },
        "synthetic_inputs": {
            "operator_export_first_send": {
                "path": _rel(EXPORT_PART1),
                "sha256": _sha256(EXPORT_PART1),
                "note": "no operator has ever sent this repository an export",
            },
            "operator_export_resend": {
                "path": _rel(EXPORT_PART2),
                "sha256": _sha256(EXPORT_PART2),
                "note": "no operator has ever sent this repository an export",
            },
            "modelling_assumptions": {
                "max_chained_gap_minutes": MAX_CHAINED_GAP_MINUTES,
                "illustrative_avoidable_share": list(ILLUSTRATIVE_AVOIDABLE_SHARE),
                "pickup_window_minutes_on_the_late_booking": 20,
                "capacity_ambulatory_per_vehicle": 1,
                "must_serve": False,
            },
        },
        "intake": {
            "first_send_rows": result.part1_rows,
            "first_send_imported": result.part1_accepted,
            "first_send_quarantined_on_pii": result.part1_pii_quarantines,
            "resend_rows": result.part2_rows,
            "resend_imported": result.part2_accepted,
            "resend_quarantined": result.part2_quarantined,
            "repair_rules_fired": result.part2_repair_rules,
            "quarantine_reasons": result.part2_quarantine_codes,
            "semantic_loss_records": result.semantic_loss_records,
        },
        "decision": {
            "aggregate_id": decision.aggregate_id,
            "solver_status": result.decision_status,
            "proven_optimal": result.decision_proven_optimal,
            "served": result.decision_served,
            "denied": result.decision_denied,
            "denial_reason_codes": list(result.denial_reason_codes),
            "independent_feasibility_violations": result.feasibility_violations,
            "alternatives_probed": result.alternatives_probed,
        },
        "teardown": {
            "teardown_id": teardown.manifest.teardown_id,
            "segment_sha256": teardown.manifest.segment_sha256,
            "total_deadhead_minutes": teardown.total_deadhead_minutes,
            "total_revenue_minutes": teardown.total_revenue_minutes,
            "deadhead_share_of_vehicle_time": teardown.deadhead_share_of_vehicle_time,
            "unattributable_deadhead_minutes": result.unattributable_deadhead_minutes,
            "value_at_full_cost": result.value_at_full_cost,
            "modelled_envelope": [result.envelope_low, result.envelope_high],
            "is_guaranteed_saving": result.is_guaranteed_saving,
        },
        "drift": {
            "assessed": result.drift_assessed,
            "control_status": result.drift_control_status,
            "control_interval_guarantee": result.drift_control_guarantee,
            "serving_status": result.drift_serving_status,
            "serving_interval_guarantee": result.drift_serving_guarantee,
            "drifted_features": list(result.drifted_features),
            "artifact_carried_its_own_reference": result.artifact_carried_reference,
        },
        "boundaries": [
            "The operator export is SYNTHETIC. No operator data exists in this repository.",
            "The NTD economics, the AAR panel and the weather panel are REAL public data.",
            "The teardown is a modelled localisation of empty time, never causal proof.",
            "No figure here is a guaranteed saving; the cost envelope refuses to be one.",
            "The conformal interval's coverage guarantee is withdrawn under measured drift.",
            "Everything is Demonstrated. Nothing is Validated: there is no consented "
            "operator data and there are no pilots or customers.",
        ],
        "known_gaps_found_by_this_run": [
            "The canonical intake column list and Outcome carry no trip END time, so the "
            "deadhead teardown cannot be driven from Milexium's own canonical records; "
            "this run reads the export's unmapped ActualDO column directly.",
            "The intake column list requires scheduled_pickup_at on every row, so a real "
            "denial log (which has no scheduled pickup) quarantines in full.",
            "The intake column list carries no ADA-mandate flag, so a denial cannot be "
            "distinguished from an INFEASIBLE mandated trip.",
            "MilexiumClient can record a RECOMMENDATION and an OVERRIDE but has no method "
            "for a REJECTION; this run reaches through the store escape hatch.",
            "decision_alternatives has a store writer but no public method creates the "
            "parent schedule_runs row, so alternatives travel in the event payload.",
            "MilexiumClient.export_pack takes no teardown, so the SDK cannot export the "
            "pack that build_evidence_pack supports; this run calls the builder directly.",
            "AggregateHistory has no teardown field, so build_period_pack cannot carry "
            "the teardown that build_evidence_pack accepts; a multi-aggregate period "
            "bundle therefore cannot carry a deadhead finding at all.",
            "A whole-problem Denial's reason_codes under-report: this run's denial names "
            "SHIFT_END (true of two vehicles) and is silent about the third vehicle, "
            "whose obstacle was NO_ACCESSIBLE_CAPACITY. The per-vehicle probe recovers it.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    result.pack_path = pack_path
    result.manifest_path = manifest_path

    say(f"written to {_rel(out)}/")
    for path in (pack_path, manifest_path):
        say(f"  {path.name:<22} {path.stat().st_size:>7,} bytes  sha256={_sha256(path)[:16]}...")
    say("")
    say("ONE portable file carries the whole claim:")
    say(f"  ledger events embedded verbatim : {pack.manifest.event_count}")
    say(f"  bundle checksum                 : {pack.manifest.bundle_sha256[:32]}...")
    say(f"  teardown included               : {pack.manifest.teardown_included}")
    say(f"  teardown segments embedded      : {pack.manifest.teardown_segment_count}")
    say(f"  independently verifiable        : {pack.manifest.independently_verifiable}")
    say("  The segments are embedded on purpose. A teardown whose inputs were not")
    say("  carried is a number to be taken on trust, and a number taken on trust is not")
    say("  evidence. Same for the events: the pack carries the raw ledger rows, not a")
    say("  summary of them.")
    say("")
    return pack_path


# --- 8. the punchline: re-derivation --------------------------------------


def _step_8_rederive(say, result: WalkthroughResult, pack_path: Path) -> None:
    from argus.demo.verify_pack import verify_pack_file

    say(_RULE)
    say("STEP 8  RE-DERIVATION  --  the pack recomputes its own claims")
    say(_RULE)
    say("Everything below is run by argus/demo/verify_pack.py against the file just written,")
    say("read back from disk as bytes. It holds no reference to anything in memory, and")
    say("the verification path never imports the code that produced the numbers -- so a")
    say("re-derivation cannot be satisfied by the generator agreeing with itself.")
    say("")
    say("  py -3 -m argus.demo.verify_pack aletheia/artifacts/demo-walkthrough")
    say("")

    verification = verify_pack_file(pack_path, say=say)
    result.pack_reverified = verification["reverified"]
    result.chain_reverified = verification["chain_reverified"]
    result.manifest_consistent = verification["manifest_consistent"]
    result.narrative_consistent = verification["narrative_consistent"]
    result.teardown_figures_rederived = verification["teardown_figures_rederived"]
    result.teardown_fingerprint_rederived = verification["teardown_fingerprint_rederived"]
    result.teardown_checks = verification["teardown_checks"]
    result.teardown_mismatches = verification["teardown_mismatches"]
    say("")


# --- summary ---------------------------------------------------------------


def _summary(say, result: WalkthroughResult) -> None:
    say(_RULE)
    say("SUMMARY")
    say(_RULE)
    say(f"INTAKE     first send {result.part1_rows} rows -> {result.part1_accepted} imported "
        f"({result.part1_pii_quarantines} refused on PII, values redacted)")
    say(f"           re-send {result.part2_rows} rows -> {result.part2_accepted} imported, "
        f"{result.part2_quarantined} quarantined, {result.semantic_loss_records} loss records")
    say(f"           repair rules fired: {', '.join(result.part2_repair_rules)}")
    say(f"DECIDE     {result.decision_status.upper()}, served {result.decision_served}, "
        f"denied {result.decision_denied} ({', '.join(result.denial_reason_codes)}), "
        f"{result.feasibility_violations} independent feasibility violations")
    say(f"TEARDOWN   {result.total_deadhead_minutes:.1f} empty min of "
        f"{result.total_deadhead_minutes + result.total_revenue_minutes:.1f} measured "
        f"({result.deadhead_share:.1%}, SYNTHETIC data); "
        f"{result.unattributable_deadhead_minutes:.1f} min unattributable and kept that way")
    say(f"DRIFT      control={result.drift_control_status}/"
        f"{result.drift_control_guarantee}, real serve={result.drift_serving_status}/"
        f"{result.drift_serving_guarantee} on {len(result.drifted_features)} drifted features")
    say(f"EVIDENCE   pack re-verified={result.pack_reverified} (chain "
        f"{result.chain_reverified}, manifest {result.manifest_consistent}, narrative "
        f"{result.narrative_consistent}); teardown figures re-derived="
        f"{result.teardown_figures_rederived} across {result.teardown_checks} checks "
        f"with {len(result.teardown_mismatches)} mismatches")
    say(f"RUNTIME    {result.runtime_seconds:.1f} s")
    say("")
    say("Six refusals were visible: PII quarantined ahead of everything else with the")
    say("values redacted; an ambiguous date declined while its unambiguous twin was")
    say("repaired; the operator's own denial left without a reason rather than")
    say("back-filled; no savings envelope without the operator's own cost split; empty")
    say("time that cannot be attributed left unattributed; and a conformal interval")
    say("withdrawing its own coverage guarantee under measured drift.")
    say("")
    say("Demonstrated. Not Validated. No customers, no pilots, no operator data.")
    say(_RULE)


# --- text helpers ----------------------------------------------------------


def _wrap(text: str, width: int) -> list[str]:
    words = str(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def main() -> int:
    try:
        run_walkthrough()
    except WalkthroughInputMissing as exc:
        print(f"[stop] {exc}")
        print("This walkthrough runs only from a checkout of the Milexium repository.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
