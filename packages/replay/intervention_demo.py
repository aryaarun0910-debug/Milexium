"""Demonstration harness: the intervention evaluator on real NTD monthly filings.

NOT a library surface -- deliberately not re-exported from
``packages.replay.__init__``. It exists so the claims in
``packages.replay.intervention`` can be exercised end to end on real, public,
commercially-usable numbers instead of only on fixtures, and so the numbers in
the packet can be re-derived by anyone with the panel.

WHAT THE DEMONSTRATION IS
-------------------------
``realdata/panels/ntd_monthly_dr.csv.gz`` is the FTA National Transit Database
"Complete Monthly Ridership" table filtered to demand-response service (the
governed dataset described in ``data/catalog/ntd-monthly-ridership-all-modes.
manifest.json``, public domain, 17 U.S.C. Sec. 105). It gives, per agency, per
month: unlinked passenger trips, vehicle revenue hours and vehicles operated in
max service. From those come one of the four metrics the packet names --
**trips per vehicle revenue hour** -- plus a real exposure column and a real
fleet-size column.

WHAT THE DEMONSTRATION IS NOT
-----------------------------
**No scheduling-software intervention is recorded in NTD, so every cut date here
is a PLACEBO.** Nothing in this file claims any agency installed anything. The
cut dates are chosen dates on real series; the point is to show what the
evaluator says when it is pointed at a real before/after where, as far as anyone
knows, nothing happened -- and specifically to show that it does not manufacture
a finding out of one.

**The agency in the regression-to-the-mean demonstration was selected because it
illustrates the diagnostic.** A deterministic scan over every NTD demand-response
reporter with complete monthly coverage picked the case with the most adverse
pre-window relative to its own long-run mean. That selection is exactly the
retrospective shopping this module exists to prevent, done on purpose, in the
open, and it is why these figures are a demonstration of a method and not a
finding about that agency. ``scan_for_reversion_candidates`` is public so the
selection can be re-run and disputed.

Status: **Demonstrated**, method claims only. Nothing here is Validated -- see
the module docstring of ``packages.replay.intervention``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from packages.replay.intervention import (
    InterventionEvaluation,
    MetricSeries,
    MetricSpec,
    PreRegistration,
    SeriesPoint,
    Window,
    evaluate_intervention,
    pre_register,
    pre_register_family,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
NTD_MONTHLY_DR_PANEL = REPO_ROOT / "realdata" / "panels" / "ntd_monthly_dr.csv.gz"

TRIPS_PER_VEHICLE_REVENUE_HOUR = MetricSpec(
    name="trips_per_vehicle_revenue_hour",
    unit="trips/hour",
    higher_is_better=True,
    definition=(
        "Unlinked passenger trips (UPT) divided by vehicle revenue hours (VRH), "
        "per agency per month, demand-response modes only, as filed by the agency "
        "to the FTA National Transit Database monthly ridership table. Both "
        "numerator and denominator are self-reported by the agency being "
        "evaluated and are subject to later revision."
    ),
)

# The peer rule is part of the pre-registration text, not a later choice.
PEER_RULE = (
    "control = the unweighted monthly mean of trips_per_vehicle_revenue_hour "
    "across every OTHER NTD demand-response reporter that (a) files the same "
    "type of service, (b) has a complete monthly filing for every month of the "
    "history, pre and post windows, and (c) operates a mean fleet within a "
    "factor of two of the treated agency's. Fixed before the post window is "
    "read; peers were not randomly assigned and this is not an experiment."
)


def _utc(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=timezone.utc)


def panel_sha256(panel_path: Path = NTD_MONTHLY_DR_PANEL) -> str:
    """Checksum of the panel these figures were derived from, so a rerun on a
    different vintage is visible rather than silent."""
    digest = hashlib.sha256()
    with panel_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ReversionCandidate:
    """One agency/type-of-service whose pre window sat below its own long-run
    mean -- the shape a procurement-triggering bad period leaves behind."""

    ntd_id: str
    type_of_service: str
    agency: str
    state: str
    long_run_mean: float
    pre_mean: float
    post_mean: float
    pre_window_z_score: float
    observed_change: float
    share_explained_by_reversion: float
    mean_fleet_size: float


@lru_cache(maxsize=2)
def _load_frame(panel_path: Path):
    """Read and derive the metric once per process; the panel is read-only and
    a demonstration run touches it half a dozen times."""
    import pandas as pd

    frame = pd.read_csv(panel_path, parse_dates=["date"])
    # NTD publishes a naive month stamp; the repo's canonical contract is
    # UTC-aware, so it is labelled UTC here. These are calendar months in the
    # agency's own reporting clock wearing a UTC label -- the same caveat
    # ADR-0039 recorded for the TLC hour buckets.
    frame["date"] = frame["date"].dt.tz_localize(timezone.utc)
    frame = frame[(frame["vrh"] > 0) & (frame["upt"] > 0)].copy()
    frame["trips_per_vehicle_revenue_hour"] = frame["upt"] / frame["vrh"]
    frame["ntd_id"] = frame["ntd_id"].astype(str)
    return frame


def scan_for_reversion_candidates(
    *,
    panel_path: Path = NTD_MONTHLY_DR_PANEL,
    history_start: datetime,
    pre_start: datetime,
    post_start: datetime,
    post_end: datetime,
    minimum_fleet: float = 40.0,
) -> list[ReversionCandidate]:
    """Deterministic scan for the regression-to-the-mean demonstration case.

    Returns every complete-coverage reporter of at least ``minimum_fleet`` whose
    metric ROSE across the cut, sorted by how far its pre window sat below its
    own history -- most adverse first, so the head of the list is the case where
    mean-reversion is most likely to be the whole story. Reporters whose pre
    window was normal or good are kept in the list (with a non-negative z) rather
    than filtered out, so the reader can see the whole distribution the winner
    was picked from.

    Published rather than hidden because running this scan and then presenting
    the winner IS the retrospective metric-shopping the evaluator is built to
    make expensive; a reader is entitled to see it happen.
    """
    frame = _load_frame(panel_path)
    window = frame[(frame["date"] >= history_start) & (frame["date"] < post_end)]
    expected_months = _month_count(history_start, post_end)

    candidates: list[ReversionCandidate] = []
    for (ntd_id, tos), group in window.groupby(["ntd_id", "tos"]):
        if len(group) != expected_months:
            continue
        history = group[group["date"] < pre_start]["trips_per_vehicle_revenue_hour"]
        pre = group[(group["date"] >= pre_start) & (group["date"] < post_start)][
            "trips_per_vehicle_revenue_hour"
        ]
        post = group[group["date"] >= post_start]["trips_per_vehicle_revenue_hour"]
        if history.std() <= 0 or pre.empty or post.empty:
            continue
        fleet = float(group["voms"].mean())
        if fleet < minimum_fleet:
            continue
        long_run, pre_mean, post_mean = float(history.mean()), float(pre.mean()), float(post.mean())
        change = post_mean - pre_mean
        if change <= 0:
            continue
        candidates.append(
            ReversionCandidate(
                ntd_id=str(ntd_id),
                type_of_service=str(tos),
                agency=str(group["agency"].iloc[0]),
                state=str(group["state"].iloc[0]),
                long_run_mean=long_run,
                pre_mean=pre_mean,
                post_mean=post_mean,
                pre_window_z_score=(pre_mean - long_run) / float(history.std()),
                observed_change=change,
                share_explained_by_reversion=(long_run - pre_mean) / change,
                mean_fleet_size=fleet,
            )
        )
    candidates.sort(key=lambda c: (c.pre_window_z_score, c.ntd_id, c.type_of_service))
    return candidates


def _month_count(start: datetime, end: datetime) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


def load_agency_series(
    *,
    ntd_id: str,
    type_of_service: str,
    history_start: datetime,
    post_end: datetime,
    panel_path: Path = NTD_MONTHLY_DR_PANEL,
) -> MetricSeries:
    """One agency's monthly trips-per-vehicle-revenue-hour series.

    ``exposure`` is vehicle revenue hours (the metric's own denominator, carried
    as a demand-volume diagnostic and NOT used to weight anything) and
    ``fleet_size`` is vehicles operated in max service, so the fleet-change
    confounder is answered from the filing rather than left unresolved.
    """
    frame = _load_frame(panel_path)
    rows = frame[
        (frame["ntd_id"] == str(ntd_id))
        & (frame["tos"] == type_of_service)
        & (frame["date"] >= history_start)
        & (frame["date"] < post_end)
    ].sort_values("date")
    if rows.empty:
        raise ValueError(f"no NTD demand-response rows for {ntd_id}/{type_of_service}")
    return MetricSeries(
        label=f"{rows['agency'].iloc[0]} ({rows['state'].iloc[0]}), NTD {ntd_id} {type_of_service}",
        metric_name=TRIPS_PER_VEHICLE_REVENUE_HOUR.name,
        provenance="real_public",
        points=tuple(
            SeriesPoint(
                period_start=row.date.to_pydatetime(),
                value=float(row.trips_per_vehicle_revenue_hour),
                exposure=float(row.vrh),
                fleet_size=None if row.voms != row.voms else float(row.voms),
            )
            for row in rows.itertuples()
        ),
    )


def load_peer_control_series(
    *,
    treated_ntd_id: str,
    type_of_service: str,
    history_start: datetime,
    post_end: datetime,
    panel_path: Path = NTD_MONTHLY_DR_PANEL,
) -> tuple[MetricSeries, int]:
    """The peer control panel defined by ``PEER_RULE``, and how many peers it has."""
    frame = _load_frame(panel_path)
    window = frame[(frame["date"] >= history_start) & (frame["date"] < post_end)]
    expected_months = _month_count(history_start, post_end)

    treated = window[
        (window["ntd_id"] == str(treated_ntd_id)) & (window["tos"] == type_of_service)
    ]
    if treated.empty:
        raise ValueError(f"treated agency {treated_ntd_id}/{type_of_service} not in the window")
    treated_fleet = float(treated["voms"].mean())

    keys = []
    for (ntd_id, tos), group in window.groupby(["ntd_id", "tos"]):
        if tos != type_of_service or str(ntd_id) == str(treated_ntd_id):
            continue
        if len(group) != expected_months:
            continue
        fleet = float(group["voms"].mean())
        if treated_fleet / 2.0 <= fleet <= treated_fleet * 2.0:
            keys.append((str(ntd_id), tos))
    if not keys:
        raise ValueError("no peers satisfy the registered peer rule")

    peers = window[window.set_index(["ntd_id", "tos"]).index.isin(keys)]
    monthly = peers.groupby("date")["trips_per_vehicle_revenue_hour"].mean().sort_index()
    return (
        MetricSeries(
            label=f"peer panel of {len(keys)} NTD {type_of_service} demand-response reporters",
            metric_name=TRIPS_PER_VEHICLE_REVENUE_HOUR.name,
            provenance="real_public",
            points=tuple(
                SeriesPoint(period_start=stamp.to_pydatetime(), value=float(value))
                for stamp, value in monthly.items()
            ),
        ),
        len(keys),
    )


# The demonstration's own registration constants, fixed here so a rerun cannot
# quietly move the goalposts. HISTORY_START..PRE_START is the pre-window history
# the reversion diagnostic reads; the intervention date is a PLACEBO.
HISTORY_START = _utc(2008, 1)
PRE_START = _utc(2014, 1)
PLACEBO_INTERVENTION_AT = _utc(2016, 1)
POST_END = _utc(2017, 1)


def register_demo(
    *, design: str, registered_at: datetime | None = None, control_plan: str | None = None
) -> PreRegistration:
    """The demonstration's pre-registration, stamped BEFORE the post window."""
    return pre_register(
        registered_at=registered_at or PLACEBO_INTERVENTION_AT,
        intervention_label=(
            "PLACEBO cut at 2016-01: no scheduling-system change is recorded in NTD for "
            "this or any agency. The date is a chosen cut on a real series"
        ),
        intervention_at=PLACEBO_INTERVENTION_AT,
        metric=TRIPS_PER_VEHICLE_REVENUE_HOUR,
        expected_direction="increase",
        pre_window=Window(starts_at=PRE_START, ends_at=PLACEBO_INTERVENTION_AT),
        post_window=Window(starts_at=PLACEBO_INTERVENTION_AT, ends_at=POST_END),
        design=design,  # type: ignore[arg-type]
        control_plan=control_plan
        or "none: this arm is deliberately uncontrolled, to show what that costs",
    )


def evaluate_demo_agency(
    *,
    ntd_id: str,
    type_of_service: str,
    controlled: bool,
    panel_path: Path = NTD_MONTHLY_DR_PANEL,
) -> InterventionEvaluation:
    """Run one demonstration arm end to end on the real panel."""
    treated = load_agency_series(
        ntd_id=ntd_id,
        type_of_service=type_of_service,
        history_start=HISTORY_START,
        post_end=POST_END,
        panel_path=panel_path,
    )
    control = None
    registration = register_demo(design="uncontrolled_pre_post")
    if controlled:
        control, peer_count = load_peer_control_series(
            treated_ntd_id=ntd_id,
            type_of_service=type_of_service,
            history_start=HISTORY_START,
            post_end=POST_END,
            panel_path=panel_path,
        )
        registration = register_demo(
            design="difference_in_differences",
            control_plan=f"{PEER_RULE} This run resolved to {peer_count} peers.",
        )

    return evaluate_intervention(
        registration,
        treated,
        control=control,
        dataset_label=(
            "FTA NTD Complete Monthly Ridership, demand-response slice "
            f"(realdata/panels/ntd_monthly_dr.csv.gz, sha256 {panel_sha256(panel_path)[:16]}...)"
        ),
        data_provenance="real_public",
        # NTD is filed by the agency, but it is not produced by any scheduling
        # system under evaluation here -- there is no such system. Declared, as
        # the three-state vocabulary requires, and unverified.
        metric_measured_by="independent_of_intervention",
        # Nobody surveyed this agency's concurrent service changes. `None` is
        # the honest value and it costs the evaluation a confounder.
        known_service_changes=None,
        demand_mix=None,
    )


def _render(title: str, evaluation: InterventionEvaluation) -> str:
    lines = [f"\n=== {title} ===", evaluation.summary(), ""]
    lines.append(f"  registration : {evaluation.manifest.registration_sha256[:16]}... "
                 f"({evaluation.manifest.registration_timing})")
    lines.append(f"  evaluation   : {evaluation.manifest.evaluation_id[:16]}...")
    association = evaluation.association
    lines.append(
        f"  estimate     : {association.estimate} {association.unit} "
        f"[{association.interval_low}, {association.interval_high}] "
        f"p={association.p_value} (alpha={association.corrected_alpha:.4g}, "
        f"family={association.family_size}) rho={association.lag1_autocorrelation}"
    )
    reversion = evaluation.regression_to_the_mean
    lines.append(
        f"  reversion    : long-run {reversion.long_run_mean}, pre {evaluation.pre_window_summary.mean} "
        f"(z={reversion.pre_window_z_score}), reversion alone predicts "
        f"{reversion.predicted_change_from_reversion}, residual "
        f"{reversion.residual_change_beyond_reversion}"
    )
    if evaluation.difference_in_differences is not None:
        did = evaluation.difference_in_differences
        lines.append(
            f"  control      : {did.control_label}; change {did.control_change}; "
            f"parallel trends {did.parallel_trends} (slope {did.pre_period_difference_slope}, "
            f"p={did.pre_period_difference_slope_p_value})"
        )
    lines.append("  confounders  :")
    for confounder in evaluation.confounders:
        lines.append(f"    - {confounder.name}: {confounder.status} [{confounder.direction_of_bias}]")
    return "\n".join(lines)


def main() -> int:  # pragma: no cover - demonstration entry point
    if not NTD_MONTHLY_DR_PANEL.exists():
        print(f"panel not present at {NTD_MONTHLY_DR_PANEL}; nothing to demonstrate")
        return 1

    print(f"panel sha256: {panel_sha256()}")
    candidates = scan_for_reversion_candidates(
        history_start=HISTORY_START,
        pre_start=PRE_START,
        post_start=PLACEBO_INTERVENTION_AT,
        post_end=POST_END,
    )
    adverse = sum(1 for c in candidates if c.pre_window_z_score < 0)
    print(f"\nreversion scan: {len(candidates)} complete-coverage reporters improved across the "
          f"cut, {adverse} of them from a pre window below their own history. Top 5 by adversity:")
    for candidate in candidates[:5]:
        print(
            f"  {candidate.agency} ({candidate.state}) {candidate.type_of_service}: "
            f"long-run {candidate.long_run_mean:.4f}, pre {candidate.pre_mean:.4f} "
            f"(z={candidate.pre_window_z_score:.2f}), post {candidate.post_mean:.4f}, "
            f"reversion explains {candidate.share_explained_by_reversion:.0%}"
        )
    print(
        "\nSELECTION WARNING: picking the winner of that scan and reporting it is "
        "retrospective shopping. It is done here deliberately and in the open, which "
        "is why what follows is a method demonstration and not a finding."
    )

    chosen = candidates[0]
    for controlled, title in ((False, "uncontrolled before/after"), (True, "difference-in-differences")):
        evaluation = evaluate_demo_agency(
            ntd_id=chosen.ntd_id, type_of_service=chosen.type_of_service, controlled=controlled
        )
        print(_render(f"{chosen.agency} -- {title}", evaluation))

    family = pre_register_family(
        registered_at=PLACEBO_INTERVENTION_AT,
        intervention_label="PLACEBO cut at 2016-01",
        intervention_at=PLACEBO_INTERVENTION_AT,
        metrics=[TRIPS_PER_VEHICLE_REVENUE_HOUR],
        expected_directions={TRIPS_PER_VEHICLE_REVENUE_HOUR.name: "increase"},
        pre_window=Window(starts_at=PRE_START, ends_at=PLACEBO_INTERVENTION_AT),
        post_window=Window(starts_at=PLACEBO_INTERVENTION_AT, ends_at=POST_END),
        design="uncontrolled_pre_post",
        control_plan="none",
    )
    print(
        f"\nfamily of {family[0].family_size} -> corrected alpha {family[0].corrected_alpha:.4g}. "
        "Registering the other three metrics the packet names (on-time performance, cost "
        "per trip, denial rate) would make it 0.0125 each -- which is the point."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
