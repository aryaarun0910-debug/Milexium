"""Program E conformance: serve-time split-conformal prediction intervals.

Exercises app.forecast.conformal end-to-end and through the runtime:

- Under exchangeability the calibrated interval reaches ~target coverage and is
  marginally conservative (the finite-sample +1 correction).
- Under the winter-calibration / spring-validation distribution shift the repo
  actually observed, the interval OVERcovers -- the honest finding carried from
  realdata/train_real_models.py + knowledge/docs/RND_QUESTIONS.md (Q4), not a bug.
- The interval widens with higher target coverage and with a smaller (thus more
  conservatively corrected) calibration sample.
- A fitted calibration brackets the point estimate, both as a value object and
  through ForecastRuntime.forecast(calibration=...), while the original manual
  interval_half_width path keeps working and the two are mutually exclusive.

These are Demonstrated properties on synthetic-but-realistic residuals; a
conformal interval is distribution-free ONLY under exchangeability and is a
marginal coverage property, never a per-forecast probability or a guarantee.
Does not edit any existing conformance file.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from app.canonical import ModelVersion, ModelVersionId, TenantId, new_id
from app.core import ModelRegistry
from app.forecast import (
    ConformalCalibration,
    ForecastRuntime,
    empirical_coverage,
    fit_conformal_from_predictions,
    fit_symmetric_conformal,
    fit_two_sided_conformal,
)
from app.forecast.features import feature_names_for

TARGET = 0.90


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Coverage properties
# --------------------------------------------------------------------------- #
def test_conformal_reaches_target_coverage_on_exchangeable_holdout() -> None:
    """Calibration and holdout drawn i.i.d. (exchangeable): achieved coverage
    sits within a tight band of the 0.90 target. Averaged over seeds so the
    assertion is about the method, not one lucky draw."""
    coverages = []
    for seed in range(20):
        rng = np.random.default_rng(seed)
        resid = rng.normal(0.0, 10.0, size=8000)
        cal, hold = resid[:3000], resid[3000:]
        # abstract residuals centred at 0 (not demand counts) -> no 0-clip,
        # so the interval is the true two-sided [-q, +q].
        calib = fit_symmetric_conformal(cal, target_coverage=TARGET, clip_nonnegative=False)
        # holdout residuals are (y - pred); apply against a zero prediction so
        # empirical_coverage checks |resid| <= q directly.
        coverages.append(empirical_coverage(calib, hold, np.zeros_like(hold)))
    mean_cov = float(np.mean(coverages))
    # within a tolerance band of the target...
    assert abs(mean_cov - TARGET) <= 0.03, mean_cov
    # ...and marginally conservative on average (the +1 finite-sample correction)
    assert mean_cov >= TARGET - 0.01, mean_cov


def test_conformal_overcovers_under_calibration_validation_shift() -> None:
    """The honest finding: when the calibration window is modestly wider than
    the serving window (the repo's winter-cal -> spring-valid shift), conformal
    OVERcovers -- achieved > target -- mirroring the committed model-card
    coverage (AAR 98.1%, Chicago 92.6%, MTA 92.0/91.7%). Overcoverage means the
    intervals are wider than nominal, never a false sense of tightness."""
    coverages = []
    for seed in range(6):
        rng = np.random.default_rng(100 + seed)
        cal = rng.normal(0.0, 11.0, size=4000)   # winter: more variable
        hold = rng.normal(0.0, 10.0, size=8000)  # spring: tamer
        calib = fit_symmetric_conformal(cal, target_coverage=TARGET, clip_nonnegative=False)
        cov = empirical_coverage(calib, hold, np.zeros_like(hold))
        coverages.append(cov)
        assert cov >= TARGET, cov  # strictly the overcoverage direction
    # overcovers, but not absurdly -- still a usable interval
    assert TARGET <= float(np.mean(coverages)) <= TARGET + 0.08


# --------------------------------------------------------------------------- #
# Width monotonicity
# --------------------------------------------------------------------------- #
def test_interval_widens_with_higher_target_coverage() -> None:
    resid = np.linspace(0.0, 100.0, 1000)  # deterministic |resid| spread
    q80 = fit_symmetric_conformal(resid, target_coverage=0.80).upper_offset
    q90 = fit_symmetric_conformal(resid, target_coverage=0.90).upper_offset
    q95 = fit_symmetric_conformal(resid, target_coverage=0.95).upper_offset
    assert q80 < q90 < q95


def test_interval_widens_with_smaller_calibration_sample() -> None:
    """Same residual range, fewer calibration points -> the finite-sample
    correction picks a higher relative order statistic, so the interval is
    wider (more conservative). Deterministic arrays, no flakiness."""
    small = np.arange(0.0, 10.0)          # n=10  -> k=ceil(11*0.9)=10 -> max=9.0
    large = np.linspace(0.0, 9.0, 1000)   # n=1000 -> ~8.1
    q_small = fit_symmetric_conformal(small, target_coverage=TARGET).upper_offset
    q_large = fit_symmetric_conformal(large, target_coverage=TARGET).upper_offset
    assert q_small > q_large


# --------------------------------------------------------------------------- #
# Consistency with the training pipeline's quantile
# --------------------------------------------------------------------------- #
def test_matches_training_pipeline_finite_sample_quantile() -> None:
    """fit_symmetric_conformal reproduces realdata/train_real_models.py's
    `conformal` single-dim quantile: k = ceil((n+1)*(1-alpha))."""
    rng = np.random.default_rng(3)
    y = rng.poisson(20, size=500).astype(float)
    pred = y + rng.normal(0, 4, size=500)
    resid = np.abs(y - pred)
    n = len(resid)
    k = min(len(resid), int(np.ceil((n + 1) * TARGET)))
    expected_q = float(np.sort(resid)[k - 1])
    calib = fit_conformal_from_predictions(y, pred, target_coverage=TARGET)
    assert calib.upper_offset == pytest.approx(expected_q)


# --------------------------------------------------------------------------- #
# Value object behaviour
# --------------------------------------------------------------------------- #
def test_fitted_calibration_brackets_the_point_estimate() -> None:
    calib = fit_symmetric_conformal(
        np.random.default_rng(0).normal(0, 2, 1000),
        target_coverage=TARGET,
        clip_nonnegative=False,
    )
    low, high = calib.apply(50.0)
    assert low < 50.0 < high
    assert calib.is_symmetric
    assert high - low == pytest.approx(calib.interval_width)


def test_symmetric_and_two_sided_shapes_differ_on_skewed_residuals() -> None:
    skewed = np.random.default_rng(1).gamma(2.0, 5.0, size=4000) - 10.0
    sym = fit_symmetric_conformal(skewed, target_coverage=TARGET)
    two = fit_two_sided_conformal(skewed, target_coverage=TARGET)
    assert sym.is_symmetric
    assert not two.is_symmetric  # asymmetric residuals -> asymmetric interval


def test_low_bound_clips_at_zero_when_requested() -> None:
    calib = fit_symmetric_conformal([5.0, 5.0, 5.0, 5.0], target_coverage=TARGET)
    low, high = calib.apply(2.0)  # 2 - 5 = -3 -> clipped
    assert low == 0.0
    assert high == pytest.approx(7.0)


def test_calibration_validation_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        fit_symmetric_conformal([], target_coverage=TARGET)
    with pytest.raises(ValueError):
        ConformalCalibration(target_coverage=1.5, lower_offset=-1, upper_offset=1, n_calibration=1)
    with pytest.raises(ValueError):  # upper < lower
        ConformalCalibration(target_coverage=0.9, lower_offset=1.0, upper_offset=-1.0, n_calibration=1)


# --------------------------------------------------------------------------- #
# Runtime integration (in-process tiny booster, no real artifacts needed)
# --------------------------------------------------------------------------- #
def _train_tiny_zone_hour_model(path: Path) -> None:
    import pandas as pd
    import xgboost as xgb

    names = list(feature_names_for("zone_hour_demand_v1"))
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(200, len(names))), columns=names)
    y = X["lag1"] * 2 + X["roll28"] + 20 + rng.normal(size=200)
    booster = xgb.train(
        {"max_depth": 2, "objective": "reg:squarederror"},
        xgb.DMatrix(X, label=y),
        num_boost_round=5,
    )
    booster.save_model(str(path))


def _register_champion(registry: ModelRegistry, artifact_path: Path) -> ModelVersion:
    mv = ModelVersion(
        model_version_id=new_id(ModelVersionId),
        tenant_id=new_id(TenantId),
        task="forecast.demand",
        training_data_manifest_hash="0" * 64,
        feature_schema_version="zone_hour_demand_v1",
        evaluation_window_start=_utc(2026, 3, 2),
        evaluation_window_end=_utc(2026, 5, 31),
        artifact_hash=hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
    )
    registry.register(mv)
    registry.promote(mv.model_version_id)
    return mv


def _feature_row() -> dict:
    return {name: 1.0 for name in feature_names_for("zone_hour_demand_v1")}


def _runtime(tmp_path: Path) -> ForecastRuntime:
    artifact = tmp_path / "tiny_model.json"
    _train_tiny_zone_hour_model(artifact)
    registry = ModelRegistry()
    _register_champion(registry, artifact)
    return ForecastRuntime(registry, artifact_resolver=lambda _mv: artifact)


def test_runtime_emits_a_conformal_interval_that_brackets_the_point(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    calib = fit_symmetric_conformal(
        np.random.default_rng(0).normal(0, 3, 1000),
        target_coverage=TARGET,
        clip_nonnegative=False,
    )
    vintage = runtime.forecast(
        "forecast.demand",
        _feature_row(),
        horizon_start=_utc(2026, 7, 24, 8),
        horizon_end=_utc(2026, 7, 24, 9),
        issued_at=_utc(2026, 7, 23, 20),
        calibration=calib,
    )
    assert vintage.interval_low < vintage.point_estimate < vintage.interval_high
    assert vintage.interval_high - vintage.interval_low == pytest.approx(calib.interval_width)


def test_runtime_manual_half_width_path_still_works(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    vintage = runtime.forecast(
        "forecast.demand",
        _feature_row(),
        horizon_start=_utc(2026, 7, 24, 8),
        horizon_end=_utc(2026, 7, 24, 9),
        issued_at=_utc(2026, 7, 23, 20),
        interval_half_width=5.0,
    )
    assert vintage.interval_low == pytest.approx(vintage.point_estimate - 5.0)
    assert vintage.interval_high == pytest.approx(vintage.point_estimate + 5.0)


def test_runtime_rejects_both_interval_paths_at_once(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    calib = fit_symmetric_conformal([1.0, 2.0, 3.0], target_coverage=TARGET)
    with pytest.raises(ValueError, match="not both"):
        runtime.forecast(
            "forecast.demand",
            _feature_row(),
            horizon_start=_utc(2026, 7, 24, 8),
            horizon_end=_utc(2026, 7, 24, 9),
            issued_at=_utc(2026, 7, 23, 20),
            interval_half_width=5.0,
            calibration=calib,
        )
