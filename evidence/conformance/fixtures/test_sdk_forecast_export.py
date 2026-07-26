"""SDK forecast + evidence-pack export conformance (Program M, Phase-1 slice).

Covers the two `MilexiumClient` methods added for Phase 1:

- `client.export_pack(...)` -- the portable, independently-verifiable sibling of
  `evidence_for`: the pack it returns must re-verify from its own bytes, with no
  live store, via `app.evidence.verify_evidence_pack`.
- `client.forecast(...)` -- a thin wrapper over `app.forecast.ForecastRuntime`.
  A throwaway XGBoost booster with the real `zone_hour_demand_v1` feature names is
  trained in-process (as `evidence/conformance/property-tests/test_forecast_runtime.py`
  does) so the wrapper's registry/resolver plumbing is exercised without the
  gitignored realdata artifacts.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.canonical import ModelVersion, ModelVersionId, TenantId, new_id
from app.connect import ReferenceAgencyTripsAdapter
from app.core import ModelRegistry
from app.evidence import EvidencePack, verify_evidence_pack
from app.forecast import NoChampionError
from app.forecast.features import feature_names_for
from app.sdk import MilexiumClient

_ROWS = [
    {"date": "2026-07-24", "hour": "8", "req_minute": "3", "rider_id": "rider-001",
     "origin_zone": "zone-12", "dest_zone": "zone-04", "wheelchair": "true"},
    {"date": "2026-07-24", "hour": "9", "req_minute": "15", "rider_id": "rider-003",
     "origin_zone": "zone-03", "dest_zone": "zone-09", "wheelchair": "false"},
]


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _driven_client() -> tuple[MilexiumClient, str]:
    client = MilexiumClient.in_memory(tenant_name="Export Co")
    adapter = ReferenceAgencyTripsAdapter(client.tenant_id, recorded_at=datetime.now(timezone.utc))
    summary = client.ingest(adapter, _ROWS)
    aggregate_id = str(summary.records[0].request_id)
    client.record_decision(
        aggregate_id=aggregate_id, actor_id="scheduler-v1",
        payload={"recommended_vehicle_id": "veh-A"},
    )
    client.record_override(
        aggregate_id=aggregate_id, actor_id="dispatcher-7",
        payload={"overridden_to_vehicle_id": "veh-C"},
    )
    return client, aggregate_id


# --- export_pack ------------------------------------------------------------

def test_export_pack_returns_an_independently_verifiable_pack() -> None:
    client, aggregate_id = _driven_client()
    pack = client.export_pack(aggregate_id)

    assert isinstance(pack, EvidencePack)
    assert pack.manifest.aggregate_id == aggregate_id
    assert pack.manifest.independently_verifiable is True
    assert pack.manifest.event_count == 2
    # The strategic claim: a third party re-verifies from the pack's own bytes.
    result = verify_evidence_pack(pack)
    assert result.reverified is True
    assert result.bundle_hash_matches is True
    assert result.chain_reverified is True


def test_export_pack_round_trips_through_json() -> None:
    client, aggregate_id = _driven_client()
    pack = client.export_pack(aggregate_id)

    restored = EvidencePack.from_json(pack.to_json())
    assert restored == pack
    assert verify_evidence_pack(restored).reverified is True


def test_export_pack_rejects_an_unknown_aggregate() -> None:
    client = MilexiumClient.in_memory(tenant_name="Export Co")
    with pytest.raises(ValueError):
        client.export_pack("never-recorded-anything")


# --- forecast ---------------------------------------------------------------

def _train_tiny_zone_hour_model(path: Path) -> None:
    import numpy as np
    import pandas as pd
    import xgboost as xgb

    names = list(feature_names_for("zone_hour_demand_v1"))
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(200, len(names))), columns=names)
    y = X["lag1"] * 2 + X["roll28"] + rng.normal(size=200)
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


def test_forecast_serves_a_vintage_from_a_registered_champion(tmp_path: Path) -> None:
    artifact = tmp_path / "tiny_model.json"
    _train_tiny_zone_hour_model(artifact)
    registry = ModelRegistry()
    mv = _register_champion(registry, artifact)

    client = MilexiumClient.in_memory(tenant_name="Forecast Co")
    vintage = client.forecast(
        "forecast.demand",
        _feature_row(),
        horizon_start=_utc(2026, 7, 24, 8),
        horizon_end=_utc(2026, 7, 24, 9),
        issued_at=_utc(2026, 7, 23, 20),
        interval_half_width=5.0,
        registry=registry,
        artifact_resolver=lambda _mv: artifact,
    )

    assert vintage.model_version_id == mv.model_version_id
    assert isinstance(vintage.point_estimate, float)
    assert vintage.interval_low == pytest.approx(vintage.point_estimate - 5.0)
    assert vintage.interval_high == pytest.approx(vintage.point_estimate + 5.0)
    assert vintage.eventual_actual is None


def test_forecast_raises_when_no_champion_is_promoted(tmp_path: Path) -> None:
    registry = ModelRegistry()  # nothing promoted
    client = MilexiumClient.in_memory(tenant_name="Forecast Co")
    with pytest.raises(NoChampionError):
        client.forecast(
            "forecast.demand",
            _feature_row(),
            horizon_start=_utc(2026, 7, 24, 8),
            horizon_end=_utc(2026, 7, 24, 9),
            issued_at=_utc(2026, 7, 23, 20),
            registry=registry,
            artifact_resolver=lambda _mv: tmp_path / "nope.json",
        )
