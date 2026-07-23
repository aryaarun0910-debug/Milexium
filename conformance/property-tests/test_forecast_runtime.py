"""Program E conformance: the forecast runtime serves a ForecastVintage from a
registered, hash-verified model, and refuses a mismatched/absent artifact.

The portable tests train a tiny XGBoost model in-process (so they don't depend
on the gitignored realdata/output/*_model.json artifacts), register it with
its real file hash, and drive the runtime end-to-end. A separate test runs
against the real committed AAR booster and skips cleanly if it isn't present.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from packages.canonical import ModelVersion, ModelVersionId, TenantId, new_id
from packages.core import ModelRegistry
from packages.forecast import ArtifactIntegrityError, ForecastRuntime, NoChampionError
from packages.forecast.features import feature_names_for


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _train_tiny_zone_hour_model(path: Path) -> None:
    """A throwaway booster with the real zone_hour_demand_v1 feature names, so
    the runtime's schema binding and prediction path are exercised without the
    real (gitignored) artifacts."""
    import numpy as np
    import pandas as pd
    import xgboost as xgb

    names = list(feature_names_for("zone_hour_demand_v1"))
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(200, len(names))), columns=names)
    y = X["lag1"] * 2 + X["roll28"] + rng.normal(size=200)
    booster = xgb.train({"max_depth": 2, "objective": "reg:squarederror"}, xgb.DMatrix(X, label=y), num_boost_round=5)
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
        artifact_hash=_sha256(artifact_path),
    )
    registry.register(mv)
    registry.promote(mv.model_version_id)
    return mv


def _feature_row() -> dict:
    return {name: 1.0 for name in feature_names_for("zone_hour_demand_v1")}


def test_runtime_serves_a_forecast_vintage_from_a_registered_model(tmp_path: Path) -> None:
    artifact = tmp_path / "tiny_model.json"
    _train_tiny_zone_hour_model(artifact)
    registry = ModelRegistry()
    mv = _register_champion(registry, artifact)

    runtime = ForecastRuntime(registry, artifact_resolver=lambda _mv: artifact)
    vintage = runtime.forecast(
        "forecast.demand",
        _feature_row(),
        horizon_start=_utc(2026, 7, 24, 8),
        horizon_end=_utc(2026, 7, 24, 9),
        issued_at=_utc(2026, 7, 23, 20),
        interval_half_width=5.0,
    )

    assert vintage.model_version_id == mv.model_version_id
    assert isinstance(vintage.point_estimate, float)
    assert vintage.interval_low == pytest.approx(vintage.point_estimate - 5.0)
    assert vintage.interval_high == pytest.approx(vintage.point_estimate + 5.0)
    assert vintage.eventual_actual is None


def test_runtime_refuses_an_artifact_whose_hash_does_not_match(tmp_path: Path) -> None:
    artifact = tmp_path / "tiny_model.json"
    _train_tiny_zone_hour_model(artifact)
    registry = ModelRegistry()
    mv = _register_champion(registry, artifact)

    # Corrupt the file after registration -- the registered hash no longer matches.
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    runtime = ForecastRuntime(registry, artifact_resolver=lambda _mv: artifact)

    with pytest.raises(ArtifactIntegrityError, match="hash mismatch"):
        runtime.forecast(
            "forecast.demand",
            _feature_row(),
            horizon_start=_utc(2026, 7, 24, 8),
            horizon_end=_utc(2026, 7, 24, 9),
            issued_at=_utc(2026, 7, 23, 20),
        )


def test_runtime_rejects_a_feature_row_missing_a_required_feature(tmp_path: Path) -> None:
    artifact = tmp_path / "tiny_model.json"
    _train_tiny_zone_hour_model(artifact)
    registry = ModelRegistry()
    _register_champion(registry, artifact)
    runtime = ForecastRuntime(registry, artifact_resolver=lambda _mv: artifact)

    incomplete = _feature_row()
    del incomplete["lag1"]
    with pytest.raises(KeyError, match="lag1"):
        runtime.forecast(
            "forecast.demand",
            incomplete,
            horizon_start=_utc(2026, 7, 24, 8),
            horizon_end=_utc(2026, 7, 24, 9),
            issued_at=_utc(2026, 7, 23, 20),
        )


def test_runtime_raises_when_no_champion_is_promoted(tmp_path: Path) -> None:
    registry = ModelRegistry()  # nothing promoted
    runtime = ForecastRuntime(registry, artifact_resolver=lambda _mv: tmp_path / "nope.json")
    with pytest.raises(NoChampionError):
        runtime.forecast(
            "forecast.demand",
            _feature_row(),
            horizon_start=_utc(2026, 7, 24, 8),
            horizon_end=_utc(2026, 7, 24, 9),
            issued_at=_utc(2026, 7, 23, 20),
        )


_REAL_AAR = Path(__file__).resolve().parents[2] / "realdata" / "output" / "aar_model.json"


@pytest.mark.skipif(not _REAL_AAR.exists(), reason="real AAR booster not present (gitignored local artifact)")
def test_runtime_serves_a_real_forecast_from_the_committed_aar_model() -> None:
    """End-to-end against the actual trained Access-A-Ride booster: proves the
    runtime works on the real artifact, not just a test stand-in. Demonstrated,
    on real aggregate data -- not a validated operational forecast."""
    registry = ModelRegistry()
    mv = ModelVersion(
        model_version_id=new_id(ModelVersionId),
        tenant_id=new_id(TenantId),
        task="forecast.demand",
        training_data_manifest_hash="0" * 64,
        feature_schema_version="zone_hour_demand_v1",
        evaluation_window_start=_utc(2026, 3, 2),
        evaluation_window_end=_utc(2026, 5, 31),
        artifact_hash=_sha256(_REAL_AAR),
    )
    registry.register(mv)
    registry.promote(mv.model_version_id)
    runtime = ForecastRuntime(registry, artifact_resolver=lambda _mv: _REAL_AAR)

    row = {
        "hour": 8, "hour_sin": 0.87, "hour_cos": -0.5, "dow": 1, "month": 7,
        "is_weekend": 0, "is_holiday": 0, "tmax_c": 28, "tmin_c": 20,
        "precip_mm": 0, "snow_cm": 0, "lag1": 45, "lag7": 50, "lag14": 48,
        "roll28": 47, "borough": 2,
    }
    vintage = runtime.forecast(
        "forecast.demand", row,
        horizon_start=_utc(2026, 7, 24, 8),
        horizon_end=_utc(2026, 7, 24, 9),
        issued_at=_utc(2026, 7, 23, 20),
    )
    # a Monday-8am summer borough-hour should be a plausible positive booking count
    assert vintage.point_estimate > 0
