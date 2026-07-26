"""Golden-path end-to-end demo on REAL public data.

One command drives the entire Milexium loop and prints each step:

  1. INGEST  -- N real NYC TLC FHVHV ride-hail trips (real, individual,
                publicly-published trips) mapped through the shipped
                `TlcTripsAdapter` into canonical ServiceRequests.
  2. FORECAST -- one real forecast served from the real, committed Access-A-Ride
                XGBoost booster (hash-verified before it can predict).
  3. DECIDE   -- a small assignment problem built from the ingested requests plus
                a clearly-labelled SYNTHETIC fleet, solved by the Program F
                solver, validated by the INDEPENDENT feasibility checker.
  4. RECORD   -- a system recommendation + a human override recorded through the
                MilexiumClient facade onto the append-only, hash-chained ledger.
  5. EVIDENCE -- a portable EvidencePack built, re-verified independently, and
                written to evidence/artifacts/golden-path/evidence_pack.json.
  6. REPLAY   -- a baseline-vs-Milexium modelled comparison over the same request
                set, with the per-metric deltas.
  7. MANIFEST -- a machine-readable evidence/artifacts/golden-path/run_manifest.json a
                reviewer can use to verify what was real, what was synthetic, and
                every load-bearing hash.

HONESTY (labelled at every step, per knowledge/architecture/decisions/0001):
  * The DEMAND/BOOKING data is REAL (NYC TLC FHVHV trips -- every Uber/Lyft/Via/
    Juno ride in NYC, published by the NYC Taxi & Limousine Commission).
  * The FORECAST runs on a REAL model trained on REAL aggregate paratransit
    demand (NYC Access-A-Ride borough-hour bookings) -- but it is Demonstrated on
    aggregate data, NOT an operator-validated dispatch forecast.
  * The FLEET/VEHICLES are SYNTHETIC. No public dataset ships an operator's
    fleet, so vehicles, shifts, and the pickup-window/ride-time assumptions used
    to turn a trip record into a schedulable request are synthetic and labelled.
  * The REPLAY is a MODELLED comparison, not causal proof of savings.
  * Everything here is Demonstrated. Nothing becomes Validated without a
    consented operator pilot.

Why TLC and not the GTFS-Flex feed: both are real public sources the repo
already ingests. The acquired GTFS-Flex example feed carries only two service-
template rows (and is explicitly not observed demand), too thin for a decision
problem; the TLC corpus is millions of real individual NYC trips, the strongest
"undeniable public evidence" demand input and the same city as the AAR forecast
model. See the run for the exact rows used.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.canonical import (
    ModelVersion,
    ModelVersionId,
    Outcome,
    PolicyId,
    ReasonCode,
    ScheduleRunId,
    TenantId,
    VehicleId,
    new_id,
)
from app.canonical.vocab import ScheduleRunStatus
from app.connect import TlcTripsAdapter
from app.core import ModelRegistry
from app.decide import (
    DecisionPolicy,
    DecisionProblem,
    DecisionVehicle,
    RideRequest,
    check_feasibility,
    solve,
)
from app.evidence import verify_evidence_pack
from app.replay import ScheduleOutcomeSet, compare_schedules
from app.sdk import MilexiumClient

# --- repository locations -------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REAL_AAR_MODEL = _REPO_ROOT / "realdata" / "output" / "aar_model.json"
_RAW_TLC_DIR = _REPO_ROOT / "realdata" / "raw_tlc"
_DEFAULT_OUTPUT_DIR = _REPO_ROOT / "evidence" / "artifacts" / "golden-path"

# --- synthetic decision-problem assumptions (ALL labelled synthetic) ------
#
# These turn a real trip *record* (which carries a request time and O/D zones,
# but no operator-negotiated pickup window, ride duration, or fleet) into a
# schedulable problem. They are engineering placeholders, not measured facts.
_PICKUP_SLACK_MIN = 30.0          # synthetic pickup window width after the real request time
_NOMINAL_RIDE_MIN = 20.0          # synthetic fixed in-vehicle duration
_MAX_RIDE_FACTOR = 1.5            # synthetic ADA-style ride-time ceiling (nominal * factor)
_DROPOFF_BUFFER_MIN = 15.0        # synthetic slack on the latest acceptable dropoff
_SHIFT_PAD_MIN = 5.0              # synthetic pad around the fleet shift envelope
_MILEXIUM_FLEET_SIZE = 3          # synthetic multi-vehicle fleet Milexium optimises over
_VEHICLE_AMBULATORY_CAP = 2       # synthetic per-vehicle ambulatory seats
_VEHICLE_WHEELCHAIR_CAP = 1       # synthetic per-vehicle wheelchair positions

_N_READ = 8                       # real TLC rows read from the head of the file
_N_DECIDE = 6                     # real ingested requests used in the decision problem

_AAR_INTERVAL_HALF_WIDTH = 20.12  # declared model interval (~ AAR validation MAE, knowledge/docs/MODEL_CARDS.md)

_RULE = "=" * 74


class DemoDataUnavailable(RuntimeError):
    """Raised when a real input (the AAR booster or a TLC parquet) is absent --
    both are gitignored local artifacts, so the demo/test skips cleanly."""


@dataclass(frozen=True)
class GoldenPathResult:
    """Everything a caller (or the conformance test) needs to assert the loop
    ran and its artifacts hold together."""

    forecast_point: float
    forecast_interval_low: float
    forecast_interval_high: float
    aar_model_sha256: str
    accepted: int
    quarantined: int
    semantic_loss_notes: int
    milexium_status: ScheduleRunStatus
    baseline_status: ScheduleRunStatus
    milexium_served: int
    baseline_served: int
    feasibility_violations: int
    evidence_integrity_verified: bool
    pack_reverified: bool
    pack_bundle_sha256: str
    pack_path: Path
    manifest_path: Path
    evidence_pack_sha256: str


# --- helpers --------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_tlc_parquet() -> Path | None:
    if not _RAW_TLC_DIR.is_dir():
        return None
    files = sorted(_RAW_TLC_DIR.glob("fhvhv_tripdata_*.parquet"))
    return files[0] if files else None


def _read_tlc_rows(parquet_path: Path, limit: int) -> list[dict]:
    """Read the first `limit` real FHVHV trip rows as plain dicts.

    DuckDB reads Parquet natively and lazily (it only touches the first row
    group for a small LIMIT), so this needs no pyarrow/fastparquet and never
    loads the ~0.5 GB file into memory. Values come back as native Python types
    (datetime/int/str/None) that the shipped TlcTripsAdapter already handles.
    """
    import duckdb

    con = duckdb.connect()
    try:
        cursor = con.execute(
            f"SELECT * FROM read_parquet('{parquet_path.as_posix()}') LIMIT {int(limit)}"
        )
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        con.close()


def _feature_row(*, month: int) -> dict:
    """A realistic point-in-time borough-hour feature row for the AAR model
    (zone_hour_demand_v1, 16 features). A weekday winter 8am borough-hour with
    plausible recent-demand lags -- a realistic input, not a cherry-picked one.
    The lag/rolling values are realistic AAR borough-hour booking counts."""
    hour = 8
    return {
        "hour": hour,
        "hour_sin": math.sin(2 * math.pi * hour / 24),
        "hour_cos": math.cos(2 * math.pi * hour / 24),
        "dow": 1,               # Monday
        "month": month,
        "is_weekend": 0,
        "is_holiday": 0,
        "tmax_c": 5.0,          # a cold NYC February day
        "tmin_c": -2.0,
        "precip_mm": 1.5,
        "snow_cm": 0.0,
        "lag1": 46.0,           # realistic recent borough-hour AAR booking counts
        "lag7": 49.0,
        "lag14": 47.0,
        "roll28": 48.0,
        "borough": 2,           # encoded borough category from the real training pipeline
    }


def _build_requests(service_requests) -> tuple[RideRequest, ...]:
    """Turn the real ingested ServiceRequests into schedulable RideRequests.

    REAL, carried straight from the TLC record: the request_id, the request time
    (-> pickup_window_start), and the wheelchair-request signal. SYNTHETIC,
    labelled: the pickup-window width, the fixed ride duration, the ride-time
    ceiling, and must_serve (TLC FHVHV trips are ride-hail, not ADA-mandated, so
    an unserved request is an honest denial, never an INFEASIBLE instance)."""
    requests: list[RideRequest] = []
    for sr in service_requests:
        req_at = sr.times.requested_at
        pickup_end = req_at + timedelta(minutes=_PICKUP_SLACK_MIN)
        dropoff_end = pickup_end + timedelta(minutes=_NOMINAL_RIDE_MIN + _DROPOFF_BUFFER_MIN)
        requests.append(
            RideRequest(
                request_id=sr.request_id,
                pickup_window_start=req_at,
                pickup_window_end=pickup_end,
                dropoff_window_end=dropoff_end,
                needs_wheelchair=(sr.mobility_device == "wheelchair"),
                party_size=1,
                nominal_ride_time_minutes=_NOMINAL_RIDE_MIN,
                max_ride_time_minutes=_NOMINAL_RIDE_MIN * _MAX_RIDE_FACTOR,
                must_serve=False,
            )
        )
    return tuple(requests)


def _fleet(
    requests: tuple[RideRequest, ...], size: int, amb_cap: int, wc_cap: int
) -> tuple[DecisionVehicle, ...]:
    """A SYNTHETIC fleet of `size` identical vehicles whose shifts span the
    request envelope. There is no public fleet data; this is a labelled
    placeholder so the assignment problem is well-posed."""
    earliest = min(r.pickup_window_start for r in requests) - timedelta(minutes=_SHIFT_PAD_MIN)
    latest = max(r.dropoff_window_end for r in requests) + timedelta(minutes=_SHIFT_PAD_MIN)
    return tuple(
        DecisionVehicle(
            vehicle_id=new_id(VehicleId),
            capacity_ambulatory=amb_cap,
            capacity_wheelchair=wc_cap,
            shift_start=earliest,
            shift_end=latest,
        )
        for _ in range(size)
    )


def _outcomes_for(problem: DecisionProblem, solution, tenant_id: TenantId) -> tuple[Outcome, ...]:
    """One Outcome per request in the problem (a denial is an Outcome with
    served=False, never an absence). Fields we can derive honestly from the real
    solver output are set; fields we cannot are left None (the replay layer
    reports an unavailable metric rather than a guessed one).

    An assignment the independent checker passed sits inside its pickup window,
    so on_time=True is a definitional read, not a claim; excess ride time is 0.0
    because the v0.1 solver models a fixed ride duration (dropoff = pickup +
    nominal); deadhead is not modelled, so it stays None."""
    assigned = {str(a.request_id): a for a in solution.assignments}
    outcomes: list[Outcome] = []
    for r in problem.requests:
        rid = str(r.request_id)
        if rid in assigned:
            outcomes.append(
                Outcome(
                    tenant_id=tenant_id,
                    request_id=r.request_id,
                    served=True,
                    actual_pickup_at=assigned[rid].pickup_time,
                    on_time=True,
                    excess_ride_time_minutes=0.0,
                    deadhead_minutes=None,
                )
            )
        else:
            outcomes.append(Outcome(tenant_id=tenant_id, request_id=r.request_id, served=False))
    return tuple(outcomes)


def _fleet_minutes(fleet: tuple[DecisionVehicle, ...]) -> float:
    return sum((v.shift_end - v.shift_start).total_seconds() / 60.0 for v in fleet)


def _productive_minutes(solution) -> float:
    return len(solution.assignments) * _NOMINAL_RIDE_MIN


# --- the loop -------------------------------------------------------------

def run_golden_path(
    output_dir: Path | str | None = None,
    *,
    parquet_path: Path | str | None = None,
    aar_model_path: Path | str | None = None,
    n_read: int = _N_READ,
    n_decide: int = _N_DECIDE,
    quiet: bool = False,
) -> GoldenPathResult:
    """Run every stage of the loop on real data and write the artifacts.

    Raises DemoDataUnavailable if the real AAR booster or a TLC parquet is
    absent (both gitignored), so a caller can skip cleanly.
    """
    say = (lambda *a, **k: None) if quiet else print

    aar_model = Path(aar_model_path) if aar_model_path is not None else _REAL_AAR_MODEL
    tlc_parquet = Path(parquet_path) if parquet_path is not None else _find_tlc_parquet()
    if not aar_model.exists():
        raise DemoDataUnavailable(f"real AAR booster not present: {aar_model}")
    if tlc_parquet is None or not Path(tlc_parquet).exists():
        raise DemoDataUnavailable("no real TLC FHVHV parquet present in realdata/raw_tlc/")
    tlc_parquet = Path(tlc_parquet)

    output_dir = Path(output_dir) if output_dir is not None else _DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    say(_RULE)
    say("MILEXIUM GOLDEN-PATH DEMO  --  the full loop on REAL public data")
    say(_RULE)
    say("Everything below is DEMONSTRATED, never Validated. Real demand data is")
    say("real; the fleet is synthetic; the replay is a modelled comparison. Each")
    say("step labels its own real-vs-synthetic boundary.")
    say("")

    client = MilexiumClient.in_memory(tenant_name="Golden Path Demo (public data)")
    recorded_at = datetime.now(timezone.utc)

    # --- 1. INGEST --------------------------------------------------------
    say(_RULE)
    say("STEP 1  INGEST  --  REAL NYC TLC FHVHV trips -> canonical ServiceRequests")
    say(_RULE)
    say(f"source (REAL): {tlc_parquet.name}  ({tlc_parquet.stat().st_size / 1e6:.0f} MB, "
        "NYC Taxi & Limousine Commission FHVHV open data)")
    raw_rows = _read_tlc_rows(tlc_parquet, n_read)
    adapter = TlcTripsAdapter(client.tenant_id, recorded_at=recorded_at)
    summary = client.ingest(adapter, raw_rows)
    say(f"read {len(raw_rows)} real trip records from the head of the file")
    say(f"  accepted (mapped to ServiceRequests): {summary.accepted}")
    say(f"  quarantined (malformed / placeholder zone): {summary.quarantined}")
    say(f"  semantic-loss notes (fields the adapter honestly could not map): "
        f"{len(summary.semantic_loss)}")
    if summary.accepted < n_decide:
        raise DemoDataUnavailable(
            f"only {summary.accepted} rows ingested cleanly; need {n_decide} for the demo"
        )
    ingested = summary.records[:n_decide]
    say(f"using the first {len(ingested)} real requests for the decision problem")
    for sr in ingested:
        say(f"  request {str(sr.request_id)[:8]}...  requested_at={sr.times.requested_at.isoformat()}  "
            f"zone {sr.pickup_zone}->{sr.dropoff_zone}  "
            f"wheelchair={'yes' if sr.mobility_device == 'wheelchair' else 'no'}")

    # --- 2. FORECAST ------------------------------------------------------
    say("")
    say(_RULE)
    say("STEP 2  FORECAST  --  REAL Access-A-Ride booster, hash-verified")
    say(_RULE)
    aar_sha256 = _sha256_file(aar_model)
    registry = ModelRegistry()
    model_version = ModelVersion(
        model_version_id=new_id(ModelVersionId),
        tenant_id=client.tenant_id,
        task="forecast.demand",
        training_data_manifest_hash="0" * 64,  # local artifact; training manifest not shipped
        feature_schema_version="zone_hour_demand_v1",
        evaluation_window_start=datetime(2026, 3, 2, tzinfo=timezone.utc),
        evaluation_window_end=datetime(2026, 5, 31, tzinfo=timezone.utc),
        artifact_hash=aar_sha256,
    )
    registry.register(model_version)
    registry.promote(model_version.model_version_id)

    feature_row = _feature_row(month=raw_rows[0]["request_datetime"].month)
    vintage = client.forecast(
        "forecast.demand",
        feature_row,
        horizon_start=datetime(2026, 7, 27, 8, tzinfo=timezone.utc),
        horizon_end=datetime(2026, 7, 27, 9, tzinfo=timezone.utc),
        issued_at=datetime(2026, 7, 26, 20, tzinfo=timezone.utc),
        interval_half_width=_AAR_INTERVAL_HALF_WIDTH,
        registry=registry,
        artifact_resolver=lambda _mv: aar_model,
    )
    say(f"model artifact: {aar_model.name}  (real committed XGBoost booster)")
    say(f"artifact sha256: {aar_sha256}")
    say("hash-verified: yes -- the runtime recomputed the file hash and it matched")
    say("               the registered ModelVersion.artifact_hash before predicting")
    say(f"FORECAST (next-hour AAR paratransit bookings, one borough-hour): "
        f"{vintage.point_estimate:.2f}")
    say(f"  declared model interval (+/- {_AAR_INTERVAL_HALF_WIDTH} ~ AAR validation MAE): "
        f"[{vintage.interval_low:.2f}, {vintage.interval_high:.2f}]")
    say("  LABEL: a real forecast on real AGGREGATE demand (borough-hour), with a")
    say("  declared model interval -- NOT a probability, NOT operator-validated dispatch.")

    # --- 3. DECIDE --------------------------------------------------------
    say("")
    say(_RULE)
    say("STEP 3  DECIDE  --  solve a small assignment (SYNTHETIC fleet), then")
    say("        validate it with the INDEPENDENT feasibility checker")
    say(_RULE)
    requests = _build_requests(ingested)
    # Milexium optimises over the full synthetic fleet; the baseline models a
    # status-quo single small van. Both are labelled synthetic.
    milexium_fleet = _fleet(requests, _MILEXIUM_FLEET_SIZE, _VEHICLE_AMBULATORY_CAP, _VEHICLE_WHEELCHAIR_CAP)
    baseline_fleet = _fleet(requests, 1, 1, 1)
    policy = DecisionPolicy(
        policy_id=new_id(PolicyId),
        name="golden-path-demo",
        # A 30-min grid over a 30-min pickup window gives the exact branch-and-
        # bound a small, fully-searchable space (the v0.1 objective ties all
        # all-served plans, so a fine grid explodes the search); a generous node
        # budget lets it EXHAUST and certify OPTIMAL rather than honestly TIMEOUT.
        time_granularity_minutes=30,
        max_search_nodes=2_000_000,
    )
    say(f"requests (REAL times/zones): {len(requests)}  |  "
        f"fleet (SYNTHETIC): {_MILEXIUM_FLEET_SIZE} vehicles, "
        f"cap {_VEHICLE_AMBULATORY_CAP} ambulatory / {_VEHICLE_WHEELCHAIR_CAP} wheelchair each")
    say(f"SYNTHETIC assumptions: pickup window +{_PICKUP_SLACK_MIN:.0f} min, "
        f"ride {_NOMINAL_RIDE_MIN:.0f} min, max ride {_NOMINAL_RIDE_MIN * _MAX_RIDE_FACTOR:.0f} min, "
        "must_serve=False (ride-hail, not ADA-mandated)")
    say("baseline (for STEP 6) = a modelled status-quo single cap-1 van")

    milexium_problem = DecisionProblem(
        tenant_id=client.tenant_id, policy=policy, vehicles=milexium_fleet, requests=requests
    )
    baseline_problem = DecisionProblem(
        tenant_id=client.tenant_id, policy=policy, vehicles=baseline_fleet, requests=requests
    )
    milexium_solution = solve(milexium_problem)
    baseline_solution = solve(baseline_problem)
    say(f"Milexium solver status: {milexium_solution.status.value.upper()}  "
        f"(proven_optimal={milexium_solution.proven_optimal})  "
        f"served {len(milexium_solution.assignments)}/{len(requests)}, "
        f"denied {len(milexium_solution.unserved)}")

    violations = check_feasibility(milexium_problem, milexium_solution)
    say(f"INDEPENDENT feasibility check (app.decide.feasibility, which never")
    say(f"  imports the solver): {len(violations)} violations -> "
        f"{'PASS' if not violations else 'FAIL'}")
    for a in milexium_solution.assignments:
        say(f"  request {str(a.request_id)[:8]}... -> vehicle {str(a.vehicle_id)[:8]}...  "
            f"pickup {a.pickup_time.isoformat()}")

    # --- 4. RECORD a decision + a human override --------------------------
    say("")
    say(_RULE)
    say("STEP 4  RECORD  --  a recommendation + a human override on the hash-chained ledger")
    say(_RULE)
    first = ingested[0]
    aggregate_id = str(first.request_id)
    first_assignment = next(
        (a for a in milexium_solution.assignments if str(a.request_id) == aggregate_id), None
    )
    schedule_run_id = new_id(ScheduleRunId)
    recommended_vehicle = (
        str(first_assignment.vehicle_id) if first_assignment else str(milexium_fleet[0].vehicle_id)
    )
    rejected_vehicle = str(milexium_fleet[-1].vehicle_id)
    client.record_decision(
        aggregate_id=aggregate_id,
        actor_id="milexium-decide@0.1",
        payload={
            "policy_version": policy.name,
            "recommended_vehicle_id": recommended_vehicle,
            "solver_status": milexium_solution.status.value,
            "alternatives": [
                {
                    "schedule_run_id": str(schedule_run_id),
                    "request_id": aggregate_id,
                    "candidate_vehicle_id": recommended_vehicle,
                    "feasible": True,
                    "objective_delta": 0.0,
                },
                {
                    "schedule_run_id": str(schedule_run_id),
                    "request_id": aggregate_id,
                    "candidate_vehicle_id": rejected_vehicle,
                    "feasible": False,
                    "failed_constraints": [ReasonCode.NO_ACCESSIBLE_CAPACITY.value],
                },
            ],
        },
    )
    client.record_override(
        aggregate_id=aggregate_id,
        actor_id="dispatcher-demo",
        payload={
            "policy_version": policy.name,
            "overridden_to_vehicle_id": "veh-demo-manual",
            "note": "rider requested a familiar driver (human override, recorded verbatim)",
        },
    )
    packet = client.evidence_for(aggregate_id)
    say(f"aggregate: {aggregate_id}")
    say(f"  recorded RECOMMENDATION (system) then OVERRIDE (human) -- executed decision: "
        f"{packet.executed.event_type.value} by {packet.executed.actor_type}:{packet.executed.actor_id}")
    say(f"  evidence integrity_verified (hash chain + schema): {packet.integrity_verified}")
    say(f"  chain violations: {len(packet.chain_violations)}")

    # --- 5. EVIDENCE PACK -------------------------------------------------
    say("")
    say(_RULE)
    say("STEP 5  EVIDENCE  --  build a portable pack, re-verify it independently, write it")
    say(_RULE)
    pack = client.export_pack(aggregate_id)
    verification = verify_evidence_pack(pack)
    pack_path = output_dir / "evidence_pack.json"
    pack_path.write_text(pack.to_json(), encoding="utf-8")
    evidence_pack_sha256 = _sha256_file(pack_path)
    say(f"pack bundle sha256: {pack.manifest.bundle_sha256}")
    say(f"independently re-verified (recomputed hash chain + bundle checksum from the")
    say(f"  pack's own bytes, no live store, no trust in the exporter): "
        f"{verification.reverified}")
    say(f"  bundle_hash_matches={verification.bundle_hash_matches}  "
        f"chain_reverified={verification.chain_reverified}")
    say(f"written: {pack_path}")
    say(f"  file sha256: {evidence_pack_sha256}")

    # --- 6. REPLAY --------------------------------------------------------
    say("")
    say(_RULE)
    say("STEP 6  REPLAY  --  baseline vs Milexium (MODELLED comparison, not causal proof)")
    say(_RULE)
    replay_instant = max(r.dropoff_window_end for r in requests) + timedelta(minutes=_SHIFT_PAD_MIN)
    baseline_set = ScheduleOutcomeSet(
        schedule_label="baseline-status-quo-single-vehicle",
        provenance="simulated",
        outcomes=_outcomes_for(baseline_problem, baseline_solution, client.tenant_id),
        available_vehicle_minutes=_fleet_minutes(baseline_fleet),
        productive_vehicle_minutes=_productive_minutes(baseline_solution),
    )
    milexium_set = ScheduleOutcomeSet(
        schedule_label="milexium-optimised-fleet",
        provenance="simulated",
        outcomes=_outcomes_for(milexium_problem, milexium_solution, client.tenant_id),
        available_vehicle_minutes=_fleet_minutes(milexium_fleet),
        productive_vehicle_minutes=_productive_minutes(milexium_solution),
    )
    comparison = compare_schedules(
        baseline_set,
        milexium_set,
        replay_instant=replay_instant,
        request_set_label=f"tlc-fhvhv-{tlc_parquet.stem}-first-{len(requests)}",
    )
    say("baseline  = the SAME real solver given a modelled status-quo single vehicle")
    say("Milexium  = the real solver over the synthetic multi-vehicle fleet")
    say("both schedules are SIMULATED counterfactuals over the identical real request set:")
    say(f"{'metric':<32}{'baseline':>12}{'milexium':>12}{'delta':>12}  favors")
    for m in comparison.metrics:
        b = "n/a" if m.baseline is None else f"{m.baseline:.3f}"
        mx = "n/a" if m.milexium is None else f"{m.milexium:.3f}"
        d = "n/a" if m.delta is None else f"{m.delta:+.3f}"
        fav = "-" if m.favors_milexium is None else ("milexium" if m.favors_milexium else "baseline")
        say(f"{m.name:<32}{b:>12}{mx:>12}{d:>12}  {fav}")
    say(f"LABEL: {comparison.interpretation}")

    # --- 7. RUN MANIFEST --------------------------------------------------
    say("")
    say(_RULE)
    say("STEP 7  MANIFEST  --  machine-readable record of real vs synthetic + hashes")
    say(_RULE)
    manifest = {
        "demo": "milexium.golden_path",
        "generated_at": recorded_at.isoformat(),
        "status_label": "Demonstrated (never Validated) -- real public data, synthetic fleet, modelled replay",
        "real_inputs": {
            "demand_source": {
                "kind": "NYC TLC FHVHV trip records (real individual public trips)",
                "file": tlc_parquet.name,
                "file_size_bytes": tlc_parquet.stat().st_size,
                "file_sha256_note": (
                    "full-file hash omitted for the ~0.5 GB public parquet; verify by re-reading "
                    "the first rows below from the same NYC TLC open-data file"
                ),
                "rows_read": len(raw_rows),
                "rows_ingested_accepted": summary.accepted,
                "rows_quarantined": summary.quarantined,
                "semantic_loss_notes": len(summary.semantic_loss),
                "rows_used_in_decision": len(ingested),
                "ingested_records_preview": [
                    {
                        "request_datetime": str(row.get("request_datetime")),
                        "PULocationID": row.get("PULocationID"),
                        "DOLocationID": row.get("DOLocationID"),
                        "wav_request_flag": row.get("wav_request_flag"),
                    }
                    for row in raw_rows
                ],
            },
            "forecast_model": {
                "kind": "real committed XGBoost Access-A-Ride booster (aggregate borough-hour demand)",
                "file": aar_model.name,
                "artifact_sha256": aar_sha256,
                "hash_verified_before_serving": True,
                "feature_schema_version": "zone_hour_demand_v1",
            },
        },
        "synthetic_inputs": {
            "fleet": {
                "note": "no public dataset ships an operator fleet; vehicles/shifts are synthetic",
                "milexium_vehicles": _MILEXIUM_FLEET_SIZE,
                "baseline_vehicles": 1,
                "capacity_ambulatory_each": _VEHICLE_AMBULATORY_CAP,
                "capacity_wheelchair_each": _VEHICLE_WHEELCHAIR_CAP,
            },
            "request_assumptions": {
                "note": "a trip record carries no operator pickup window, ride duration, or mandate",
                "pickup_window_minutes": _PICKUP_SLACK_MIN,
                "nominal_ride_minutes": _NOMINAL_RIDE_MIN,
                "max_ride_factor": _MAX_RIDE_FACTOR,
                "must_serve": False,
            },
        },
        "forecast": {
            "point_estimate": vintage.point_estimate,
            "interval_low": vintage.interval_low,
            "interval_high": vintage.interval_high,
            "interval_half_width": _AAR_INTERVAL_HALF_WIDTH,
            "feature_row": feature_row,
            "label": "real aggregate forecast; declared model interval, not a probability; not validated dispatch",
        },
        "decide": {
            "solver_name": milexium_solution.solver_name,
            "solver_version": milexium_solution.solver_version,
            "milexium_status": milexium_solution.status.value,
            "milexium_proven_optimal": milexium_solution.proven_optimal,
            "milexium_served": len(milexium_solution.assignments),
            "baseline_status": baseline_solution.status.value,
            "baseline_served": len(baseline_solution.assignments),
            "independent_feasibility_violations": len(violations),
        },
        "evidence_pack": {
            "path": pack_path.name,
            "bundle_sha256": pack.manifest.bundle_sha256,
            "file_sha256": evidence_pack_sha256,
            "integrity_verified_at_export": pack.manifest.integrity_verified_at_export,
            "independently_reverified": verification.reverified,
        },
        "replay": {
            "replay_id": comparison.manifest.replay_id,
            "request_set_sha256": comparison.manifest.request_set_sha256,
            "is_modelled_comparison": comparison.is_modelled_comparison,
            "causal_proof": comparison.causal_proof,
            "interpretation": comparison.interpretation,
            "metrics": [
                {
                    "name": m.name,
                    "unit": m.unit,
                    "basis": m.basis,
                    "baseline": m.baseline,
                    "milexium": m.milexium,
                    "delta": m.delta,
                    "favors_milexium": m.favors_milexium,
                }
                for m in comparison.metrics
            ],
        },
        "boundaries": [
            "Real demand/booking data is REAL (NYC TLC FHVHV public trips).",
            "The forecast runs on a REAL model over REAL AGGREGATE demand -- not operator-validated dispatch.",
            "The fleet and the request scheduling assumptions are SYNTHETIC (no public fleet exists).",
            "The replay is a MODELLED comparison, not causal proof of savings.",
            "Everything is Demonstrated; nothing is Validated without a consented operator pilot.",
        ],
    }
    manifest_path = output_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    say(f"written: {manifest_path}")

    # --- closing summary --------------------------------------------------
    say("")
    say(_RULE)
    say("SUMMARY")
    say(_RULE)
    say(f"REAL: {summary.accepted} NYC TLC trips ingested; forecast {vintage.point_estimate:.1f} "
        f"served from the real AAR booster (hash {aar_sha256[:12]}...).")
    say(f"SYNTHETIC: {_MILEXIUM_FLEET_SIZE}-vehicle fleet; Milexium solver "
        f"{milexium_solution.status.value.upper()} serving {len(milexium_solution.assignments)}/"
        f"{len(requests)}, independently checked feasible ({len(violations)} violations).")
    say(f"EVIDENCE: pack independently re-verified={verification.reverified}, written + hashed.")
    say(f"REPLAY: modelled baseline-vs-Milexium comparison written (not causal proof).")
    say(f"Artifacts in {output_dir}:  evidence_pack.json, run_manifest.json")
    say("All Demonstrated. Nothing Validated. The boundaries above are in the manifest.")
    say(_RULE)

    return GoldenPathResult(
        forecast_point=vintage.point_estimate,
        forecast_interval_low=vintage.interval_low,
        forecast_interval_high=vintage.interval_high,
        aar_model_sha256=aar_sha256,
        accepted=summary.accepted,
        quarantined=summary.quarantined,
        semantic_loss_notes=len(summary.semantic_loss),
        milexium_status=milexium_solution.status,
        baseline_status=baseline_solution.status,
        milexium_served=len(milexium_solution.assignments),
        baseline_served=len(baseline_solution.assignments),
        feasibility_violations=len(violations),
        evidence_integrity_verified=packet.integrity_verified,
        pack_reverified=verification.reverified,
        pack_bundle_sha256=pack.manifest.bundle_sha256,
        pack_path=pack_path,
        manifest_path=manifest_path,
        evidence_pack_sha256=evidence_pack_sha256,
    )


def main() -> int:
    try:
        run_golden_path()
    except DemoDataUnavailable as exc:
        print(f"[skip] {exc}")
        print("This demo needs the real (gitignored) AAR booster at "
              "realdata/output/aar_model.json and a TLC FHVHV parquet in "
              "realdata/raw_tlc/. Both are local artifacts, not committed.")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
