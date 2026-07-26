"""Capacity-backtest artifact conformance (packet MX-E-CAPACITY-FORECAST-010).

Proves the emitted report is a faithful, third-party-checkable projection of the
per-series records rather than a hand-written summary, and that the discipline
the packet requires is present in the artifact itself:

1. The generator runs and produces BOTH files.
2. Every headline in the summary is RECOMPUTED from the per-series records and
   must agree -- win counts, medians, cost reductions, guarantee counts.
3. The panel is pinned: the report's SHA-256 matches the file on disk AND the
   committed governance manifest.
4. The loss to seasonal naive is PRESENT, non-zero, and quantified. A report
   that silently dropped its losses would pass a weaker test; this one fails.
5. The leaderboard's recorded NTD temporal loss is explicitly not overturned.
6. The interval guarantee reaches every recommendation: no recommendation may
   claim an evidenced service level while its guarantee is withdrawn, checked
   over the real emitted records rather than a fixture.
7. Nothing in the artifact claims Validated status.

The generator is slow (it reads a 152k-row panel and runs a Monte-Carlo PSI
calibration), so it is run ONCE per session via a module-scoped fixture and only
if the artifact is missing or stale relative to its inputs.
"""

from __future__ import annotations

import json
import math
import statistics
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_PANEL = _REPO / "data" / "curated" / "panels" / "ntd_monthly_dr.csv.gz"
_MANIFEST = _REPO / "data" / "curated" / "manifests" / "ntd_monthly_dr.csv.gz.json"
_GENERATOR = _REPO / "aletheia" / "benchmarks" / "quality" / "capacity_backtest.py"
_JSON_OUT = _REPO / "aletheia" / "benchmarks" / "quality" / "capacity_backtest.json"
_MD_OUT = _REPO / "aletheia" / "benchmarks" / "quality" / "capacity_backtest.md"

pytestmark = pytest.mark.skipif(
    not _PANEL.exists(),
    reason="governed NTD demand-response panel absent -- nothing to backtest",
)


@pytest.fixture(scope="module")
def report() -> dict:
    """Generate the artifact if it is missing or older than its generator."""
    stale = (
        not _JSON_OUT.exists()
        or not _MD_OUT.exists()
        or _JSON_OUT.stat().st_mtime < _GENERATOR.stat().st_mtime
    )
    if stale:
        result = subprocess.run(
            [sys.executable, str(_GENERATOR)],
            capture_output=True,
            text=True,
            cwd=str(_REPO),
            timeout=1800,
        )
        assert result.returncode == 0, result.stderr[-4000:]
    assert _JSON_OUT.exists() and _MD_OUT.exists()
    return json.loads(_JSON_OUT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def markdown(report: dict) -> str:
    return _MD_OUT.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1-3. The artifact is real, pinned, and non-trivial
# --------------------------------------------------------------------------- #
def test_the_backtest_covers_a_substantial_number_of_real_series(report: dict):
    records = report["series"]
    assert len(records) >= 100, f"only {len(records)} series -- too thin to conclude anything"
    assert report["summary"]["n_series"] == len(records)
    assert len({(r["ntd_id"], r["tos"]) for r in records}) == len(records), "duplicate series"
    for r in records:
        assert r["n_validation_months"] >= 15
        assert r["trips_per_vehicle_hour"] > 0
        assert 0.0 < r["critical_ratio"] < 1.0


def test_the_panel_is_pinned_to_its_governance_manifest(report: dict):
    """A backtest that cites a filename rather than content-addressed bytes is
    not reproducible. The report's hash must match the file AND the manifest."""
    from metis.forecast.serve_drift import sha256_of_file

    panel = report["panel"]
    assert panel["sha256"] == sha256_of_file(_PANEL)
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert panel["manifest_sha256"] == manifest["sha256"]
    assert panel["manifest_matches_file"] is True


def test_the_cost_asymmetry_is_stated_and_declared_a_placeholder(report: dict):
    """The packet's requirement 2 as it reaches the artifact: the numbers are on
    the page, attributed, and honest about being illustrative."""
    cost = report["cost_asymmetry"]
    assert cost["cost_per_unserved_trip"] > 0
    assert cost["cost_per_idle_vehicle_hour"] > 0
    assert cost["is_illustrative_placeholder"] is True
    assert "NOT AN OPERATOR STATEMENT" in cost["basis"].upper()
    assert cost["stated_by"]


# --------------------------------------------------------------------------- #
# 4. Every headline recomputes from the per-series records
# --------------------------------------------------------------------------- #
def test_demand_accuracy_headlines_recompute_from_the_records(report: dict):
    records = report["series"]
    acc = report["summary"]["demand_accuracy"]
    mae_wins = sum(1 for r in records if r["demand_mae"]["model"] < r["demand_mae"]["naive"])
    mape_wins = sum(
        1
        for r in records
        if r["demand_mape"]["model"] is not None
        and r["demand_mape"]["naive"] is not None
        and r["demand_mape"]["model"] < r["demand_mape"]["naive"]
    )
    assert acc["series_where_model_beats_naive_mae"] == mae_wins
    assert acc["series_where_model_beats_naive_mape"] == mape_wins
    assert acc["share_model_beats_naive_mae"] == pytest.approx(mae_wins / len(records))
    assert acc["median_mae_model"] == pytest.approx(
        statistics.median(r["demand_mae"]["model"] for r in records)
    )
    assert acc["median_mae_naive"] == pytest.approx(
        statistics.median(r["demand_mae"]["naive"] for r in records)
    )


@pytest.mark.parametrize(
    ("key", "plan_a", "plan_b"),
    [
        ("model_cost_aware_vs_naive_mean", "model_cost_aware", "naive_mean"),
        ("model_cost_aware_vs_naive_cost_aware", "model_cost_aware", "naive_cost_aware"),
        ("model_cost_aware_vs_model_mean", "model_cost_aware", "model_mean"),
        ("naive_cost_aware_vs_naive_mean", "naive_cost_aware", "naive_mean"),
        ("model_mean_vs_naive_mean", "model_mean", "naive_mean"),
    ],
)
def test_capacity_cost_comparisons_recompute_from_the_records(
    report: dict, key: str, plan_a: str, plan_b: str
):
    records = report["series"]
    block = report["summary"]["capacity_decision"][key]
    wins = sum(
        1 for r in records if r["asymmetric_cost"][plan_a] < r["asymmetric_cost"][plan_b]
    )
    deltas = [
        100.0 * (r["asymmetric_cost"][plan_b] - r["asymmetric_cost"][plan_a])
        / r["asymmetric_cost"][plan_b]
        for r in records
        if r["asymmetric_cost"][plan_b] > 0
    ]
    assert block["series_where_a_better"] == wins
    assert block["series_total"] == len(records)
    assert block["median_pct_reduction"] == pytest.approx(statistics.median(deltas))


def test_guarantee_counts_recompute_and_sum_to_the_series_total(report: dict):
    records = report["series"]
    g = report["summary"]["guarantee"]
    for field, counts in (
        ("interval_guarantee", g["interval_guarantee_counts"]),
        ("drift_status", g["drift_status_counts"]),
    ):
        recomputed: dict[str, int] = {}
        for r in records:
            recomputed[r[field]] = recomputed.get(r[field], 0) + 1
        assert counts == recomputed
        assert sum(counts.values()) == len(records)


def test_achieved_service_level_is_recomputed_and_below_one(report: dict):
    records = report["series"]
    cap = report["summary"]["capacity_decision"]
    for plan, value in cap["median_achieved_service_level"].items():
        assert value == pytest.approx(
            statistics.median(r["achieved_service_level"][plan] for r in records)
        )
        assert 0.0 <= value <= 1.0
    share = cap["share_of_series_achieving_target_service_level"]
    for plan, value in share.items():
        expected = sum(
            1 for r in records if r["achieved_service_level"][plan] >= r["critical_ratio"]
        ) / len(records)
        assert value == pytest.approx(expected)
        assert value < 1.0, (
            "if every series hit its target the stated level would be evidenced and the "
            "withdrawal machinery would be unnecessary -- check the target, not the claim"
        )


# --------------------------------------------------------------------------- #
# 5. The losses are present, quantified, and not quietly dropped
# --------------------------------------------------------------------------- #
def test_the_report_records_where_the_model_loses_to_seasonal_naive(report: dict):
    """The discipline test. `forecast_leaderboard.md` already keeps one loss to
    naive on purpose; a capacity report that showed only wins would be a
    regression in honesty, not an improvement in results."""
    loss = report["summary"]["where_the_model_loses"]
    n = report["summary"]["n_series"]
    assert loss["demand_mape"]["series_lost"] > 0, (
        "zero losses across hundreds of real series is not a result, it is a bug or a "
        "filtered sample"
    )
    assert loss["capacity_cost"]["series_lost"] > 0
    assert loss["demand_mape"]["series_lost"] < n / 2
    assert loss["demand_mape"]["median_pct_worse_when_losing"] > 0
    assert loss["demand_mape"]["worst_pct_worse"] >= loss["demand_mape"][
        "median_pct_worse_when_losing"
    ]
    assert loss["largest_mape_losses"], "the worst losses must be named, not aggregated away"
    for item in loss["largest_mape_losses"]:
        assert item["model_mape"] > item["naive_mape"], "a 'loss' row that is actually a win"
        assert item["agency"]


def test_loss_counts_recompute_from_the_records(report: dict):
    records = report["series"]
    loss = report["summary"]["where_the_model_loses"]
    lost = sum(
        1
        for r in records
        if r["demand_mape"]["model"] is not None
        and r["demand_mape"]["naive"] is not None
        and r["demand_mape"]["model"] > r["demand_mape"]["naive"]
    )
    assert loss["demand_mape"]["series_lost"] == lost
    cost_lost = sum(
        1
        for r in records
        if r["asymmetric_cost"]["model_cost_aware"] > r["asymmetric_cost"]["naive_mean"]
    )
    assert loss["capacity_cost"]["series_lost"] == cost_lost


def test_the_markdown_reports_the_losses_and_does_not_overturn_the_leaderboard(markdown: str):
    assert "Where we LOSE to seasonal naive" in markdown
    assert "nothing here overturns" in markdown
    assert "0.8854" in markdown and "0.9715" in markdown, (
        "the leaderboard's recorded NTD temporal loss must be cited with its actual numbers"
    )
    leaderboard = (_REPO / "aletheia" / "benchmarks" / "quality" / "forecast_leaderboard.md").read_text(
        encoding="utf-8"
    )
    assert "0.8854 / 0.9715" in leaderboard, (
        "the leaderboard's deliberate loss row was removed; this packet must not have "
        "caused that"
    )


# --------------------------------------------------------------------------- #
# 6. The guarantee reaches every emitted recommendation
# --------------------------------------------------------------------------- #
def test_no_emitted_recommendation_claims_a_level_its_guarantee_cannot_carry(report: dict):
    """The packet's central requirement, checked over every recommendation the
    backtest actually built on real data."""
    built = [
        r["final_month_recommendation"]
        for r in report["series"]
        if r["final_month_recommendation"] is not None
    ]
    assert built, "no recommendations were constructed -- the propagation is untested"
    for rec in built:
        if rec["interval_guarantee"] != "unqualified":
            assert rec["service_level_is_evidenced"] is False
            assert rec["evidenced_service_level"] is None
            assert rec["has_guarantee_caveat"] is True
        assert rec["required_vehicle_hours"] > 0, (
            "the withdrawal must remove the CLAIM, never the number"
        )
        assert rec["demand_at_service_level"] >= 0
        assert 0.0 < rec["service_level"] < 1.0


def test_the_guarantee_summary_counts_match_the_emitted_recommendations(report: dict):
    g = report["summary"]["guarantee"]
    built = [
        r["final_month_recommendation"]
        for r in report["series"]
        if r["final_month_recommendation"] is not None
    ]
    assert g["recommendations_built"] == len(built)
    assert g["recommendations_with_evidenced_service_level"] == sum(
        1 for r in built if r["service_level_is_evidenced"]
    )
    assert g["recommendations_carrying_a_caveat"] == sum(
        1 for r in built if r["has_guarantee_caveat"]
    )
    assert (
        g["recommendations_with_evidenced_service_level"]
        + g["recommendations_carrying_a_caveat"]
        == len(built)
    ), "every recommendation is exactly one of: evidenced, or caveated"


# --------------------------------------------------------------------------- #
# 7. The drift measurement, and its controls
# --------------------------------------------------------------------------- #
def test_the_psi_calibration_shows_the_small_sample_defect_it_claims(report: dict):
    """The measurement that justifies raising `min_rows` above the module
    default. If PSI were well behaved at 30 rows this table would say so, and
    the backtest's protocol choice would be unjustified."""
    table = report["summary"]["guarantee"]["psi_null_calibration"]
    by_n = {row["n_per_sample"]: row for row in table}
    assert by_n[30]["psi_false_positive_rate"] > 0.8, (
        "the claimed PSI defect at n=30 is not reproduced"
    )
    assert by_n[400]["psi_false_positive_rate"] < 0.05
    rates = [by_n[n]["psi_false_positive_rate"] for n in sorted(by_n)]
    assert rates == sorted(rates, reverse=True), "PSI false positives must fall with n"
    for row in table:
        assert row["ks_false_positive_rate_alpha_0.01"] < 0.10, (
            "KS is a properly calibrated test at every n; if this fails the diagnosis "
            "'PSI specifically, not the monitor's design' is wrong"
        )


def test_the_small_n_control_is_reported_rather_than_deleted(report: dict):
    """The control that found the defect is kept in the artifact. If it ever
    stops reporting drift on a random split, the defect is fixed and the
    protocol should be revisited -- which is exactly what this test forces."""
    control = report["summary"]["guarantee"]["small_n_exchangeable_control_at_module_default"]
    assert sum(control.values()) > 0
    assert control["drift"] > 0, (
        "the small-n control no longer reports false drift; PSI may have been fixed "
        "upstream, in which case MIN_ROWS_FOR_TRUSTWORTHY_PSI should be revisited"
    )


def test_the_panel_level_verdict_has_a_passing_control(report: dict):
    """A drift verdict without a passing exchangeability control is not
    evidence. This is ADR-0049's own discipline, applied to the pooled test."""
    panel = report["summary"]["guarantee"]["panel_level_drift"]
    if not panel.get("available"):
        pytest.skip("pooled windows unavailable")
    assert panel["n_calibration_rows"] >= 400 and panel["n_validation_rows"] >= 400
    assert panel["control_status"] == "no_drift", (
        f"the exchangeable control at the pooled size reported {panel['control_status']}; "
        f"the panel verdict {panel['status']!r} is therefore not evidence"
    )
    assert panel["control_drifted_features"] == []
    assert panel["control_interval_guarantee"] == "unqualified"
    if panel["status"] == "drift":
        assert panel["interval_guarantee"] == "unsupported"
        assert panel["drifted_features"]
        assert max(panel["feature_psi"].values()) >= 0.2, (
            "a drift verdict flagged only by KS at 20k rows is statistical significance "
            "without effect size; the report must not lead with it"
        )


def test_per_series_min_rows_is_raised_above_the_module_default(report: dict):
    from metis.forecast.serve_drift import MIN_ROWS_FOR_STABLE_STATISTIC

    applied = report["summary"]["guarantee"]["per_series_min_rows_applied"]
    assert applied > MIN_ROWS_FOR_STABLE_STATISTIC
    table = {row["n_per_sample"]: row for row in report["summary"]["guarantee"]["psi_null_calibration"]}
    assert applied in table and table[applied]["psi_false_positive_rate"] < 0.05, (
        "the applied threshold must be one the calibration table actually justifies"
    )


# --------------------------------------------------------------------------- #
# 8. Status discipline
# --------------------------------------------------------------------------- #
def test_nothing_in_the_artifact_claims_validated_status(report: dict, markdown: str):
    assert "NOT Validated" in report["status"]
    assert "NOT Validated" in markdown
    blob = json.dumps(report)
    assert "Validated" in blob  # present only in the negated form
    for fragment in ("status: Validated", "operator-validated", "is Validated"):
        assert fragment.lower() not in blob.lower()


def test_the_censored_demand_limitation_travels_with_the_numbers(report: dict, markdown: str):
    """The limitation that keeps this a method claim: NTD records delivered
    service, never denied trips, so under-provisioning is unobservable."""
    from metis.forecast.capacity import CENSORED_DEMAND_LIMITATION

    assert CENSORED_DEMAND_LIMITATION in report["limitations"]
    assert "DENIED trips" in markdown
    assert len(report["limitations"]) >= 4


def test_the_markdown_and_json_agree_on_the_headline_counts(report: dict, markdown: str):
    n = report["summary"]["n_series"]
    acc = report["summary"]["demand_accuracy"]
    assert f"{acc['series_where_model_beats_naive_mape']} / {n}" in markdown
    cap = report["summary"]["capacity_decision"]["model_cost_aware_vs_naive_mean"]
    assert f"{cap['series_where_a_better']} / {n}" in markdown
    assert math.isfinite(report["summary"]["critical_ratio_median"])
    assert f"{report['summary']['critical_ratio_median']:.3f}" in markdown
