"""Program E conformance: every real model serves a forecast, and serve-time
conformal reproduces the repo's honest coverage findings on real artifacts.

The original runtime conformance test only drove the Access-A-Ride booster.
This file registers and serves ALL FOUR real committed zone-hour models (AAR,
Chicago TNP, MTA bus, MTA subway), each with its OWN feature schema -- the 15
shared calendar/weather/lag features plus that feed's distinct trailing zone
column (borough / area / route / station_id). Each model is hash-verified and
served through ForecastRuntime exactly as in production.

It also validates serve-time split-conformal against the committed
realdata/output/*_valid.csv.gz predictions:
- The committed intervals OVERcover their 0.90 target (AAR ~0.98, the others
  ~0.92) -- the honest model-card finding, reproduced directly from the
  artifacts, driven by the winter-cal -> spring-valid distribution shift.
- Refitting conformal on a random (exchangeable) split of the same validation
  window lands back near the 0.90 target -- isolating that shift as the cause
  of overcoverage, consistent with docs/RND_QUESTIONS.md Q4.

All real-artifact tests skip cleanly when the gitignored local files are
absent, mirroring test_forecast_runtime.py. Demonstrated on real aggregate
public data -- not operator-Validated. Does not edit any existing conformance file.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from packages.canonical import ModelVersion, ModelVersionId, TenantId, new_id
from packages.core import ModelRegistry
from packages.forecast import (
    ForecastRuntime,
    empirical_coverage,
    fit_conformal_from_predictions,
)

_REALDATA = Path(__file__).resolve().parents[2] / "realdata" / "output"
TARGET = 0.90

# (metric name, model file, valid file, feature schema, zone column)
MODELS = [
    ("nyc_access_a_ride", "aar_model.json", "aar_valid.csv.gz", "zone_hour_demand_v1", "borough"),
    ("chicago_tnp", "chicago_model.json", "chicago_valid.csv.gz", "zone_hour_demand_area_v1", "area"),
    ("mta_bus", "mta_bus_model.json", "mta_bus_valid.csv.gz", "zone_hour_demand_route_v1", "route"),
    ("mta_subway", "mta_subway_model.json", "mta_subway_valid.csv.gz", "zone_hour_demand_station_v1", "station_id"),
]


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _serve(model_file: str, schema: str) -> tuple[ForecastRuntime, ModelVersion]:
    """Register the real booster with its true file hash and correct schema,
    promote it, and return a runtime that resolves to it."""
    path = _REALDATA / model_file
    registry = ModelRegistry()
    mv = ModelVersion(
        model_version_id=new_id(ModelVersionId),
        tenant_id=new_id(TenantId),
        task="forecast.demand",
        training_data_manifest_hash="0" * 64,
        feature_schema_version=schema,
        evaluation_window_start=_utc(2026, 3, 2),
        evaluation_window_end=_utc(2026, 5, 31),
        artifact_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    registry.register(mv)
    registry.promote(mv.model_version_id)
    return ForecastRuntime(registry, artifact_resolver=lambda _mv: path), mv


def _real_row(zone_col: str) -> dict:
    """A plausible weekday-8am summer feature row with healthy demand lags, so
    every model returns a solidly positive point estimate."""
    return {
        "hour": 8, "hour_sin": 0.87, "hour_cos": -0.5, "dow": 1, "month": 7,
        "is_weekend": 0, "is_holiday": 0, "tmax_c": 28, "tmin_c": 20,
        "precip_mm": 0, "snow_cm": 0, "lag1": 45, "lag7": 50, "lag14": 48,
        "roll28": 47, zone_col: 1,
    }


@pytest.mark.parametrize("metric, model_file, valid_file, schema, zone_col", MODELS)
def test_each_real_model_serves_a_point_forecast(
    metric, model_file, valid_file, schema, zone_col
) -> None:
    if not (_REALDATA / model_file).exists():
        pytest.skip(f"real booster {model_file} not present (gitignored local artifact)")
    runtime, mv = _serve(model_file, schema)
    vintage = runtime.forecast(
        "forecast.demand",
        _real_row(zone_col),
        horizon_start=_utc(2026, 7, 24, 8),
        horizon_end=_utc(2026, 7, 24, 9),
        issued_at=_utc(2026, 7, 23, 20),
    )
    assert vintage.model_version_id == mv.model_version_id
    assert math.isfinite(vintage.point_estimate)
    assert vintage.point_estimate > 0  # a plausible positive demand count


@pytest.mark.parametrize("metric, model_file, valid_file, schema, zone_col", MODELS)
def test_each_real_model_serves_a_conformal_interval(
    metric, model_file, valid_file, schema, zone_col
) -> None:
    """Fit serve-time conformal from the model's committed validation residuals
    and serve an interval that brackets the point estimate."""
    if not (_REALDATA / model_file).exists() or not (_REALDATA / valid_file).exists():
        pytest.skip(f"real artifacts for {metric} not present")
    import pandas as pd

    v = pd.read_csv(_REALDATA / valid_file)
    calib = fit_conformal_from_predictions(v["y"].to_numpy(), v["pred"].to_numpy(), target_coverage=TARGET)
    runtime, _ = _serve(model_file, schema)
    vintage = runtime.forecast(
        "forecast.demand",
        _real_row(zone_col),
        horizon_start=_utc(2026, 7, 24, 8),
        horizon_end=_utc(2026, 7, 24, 9),
        issued_at=_utc(2026, 7, 23, 20),
        calibration=calib,
    )
    assert vintage.interval_low < vintage.point_estimate < vintage.interval_high
    assert vintage.interval_high > vintage.interval_low


@pytest.mark.parametrize("metric, model_file, valid_file, schema, zone_col", MODELS)
def test_committed_intervals_overcover_their_target(
    metric, model_file, valid_file, schema, zone_col
) -> None:
    """Honest finding reproduced from the artifact: the committed lo/hi columns
    (calibrated on the winter window) OVERcover the 0.90 target on the spring
    validation window -- wider than nominal, never a false-tightness."""
    if not (_REALDATA / valid_file).exists():
        pytest.skip(f"validation set for {metric} not present")
    import pandas as pd

    v = pd.read_csv(_REALDATA / valid_file)
    covered = ((v["y"] >= v["lo"]) & (v["y"] <= v["hi"])).mean()
    assert covered >= TARGET, f"{metric}: committed coverage {covered:.4f} below target"
    assert covered <= 0.995, f"{metric}: committed coverage {covered:.4f} implausibly high"


@pytest.mark.parametrize("metric, model_file, valid_file, schema, zone_col", MODELS)
def test_exchangeable_split_recovers_target_coverage(
    metric, model_file, valid_file, schema, zone_col
) -> None:
    """Refitting conformal on a RANDOM (exchangeable) split of the same
    validation window recovers ~target coverage -- isolating the winter/spring
    distribution shift, not the method, as the source of the overcoverage
    above (docs/RND_QUESTIONS.md Q4)."""
    if not (_REALDATA / valid_file).exists():
        pytest.skip(f"validation set for {metric} not present")
    import pandas as pd

    v = pd.read_csv(_REALDATA / valid_file)
    y = v["y"].to_numpy(dtype=float)
    pred = v["pred"].to_numpy(dtype=float)
    idx = np.random.default_rng(0).permutation(len(y))
    half = len(idx) // 2
    cal_i, hold_i = idx[:half], idx[half:]
    calib = fit_conformal_from_predictions(y[cal_i], pred[cal_i], target_coverage=TARGET)
    cov = empirical_coverage(calib, y[hold_i], pred[hold_i])
    assert 0.86 <= cov <= 0.98, f"{metric}: exchangeable-split coverage {cov:.4f} off target"
