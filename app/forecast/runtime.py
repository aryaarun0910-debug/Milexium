"""ForecastRuntime: serve a forecast from a registered real model.

The runtime is the join between Program D (app.core.ModelRegistry, which
knows *which* model is champion for a task and its expected artifact hash) and
the real XGBoost boosters on disk (realdata/output/*_model.json, gitignored
local artifacts). It never trusts an artifact by path alone: it hashes the
loaded file and refuses to predict if the hash doesn't match the registered
ModelVersion.artifact_hash (ArtifactIntegrityError). This is the same
"generator vs. independent check" stance as app.verify -- a stale, swapped,
or corrupted model file is caught before it can produce a forecast.

xgboost is a declared dependency (pyproject); it is imported lazily inside the
methods that need it so importing this module (e.g. for its types/errors) does
not require xgboost to be installed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.canonical.entities import ForecastVintage, ModelVersion
from app.canonical.ids import ModelVersionId
from app.canonical.time import _require_utc
from app.core.model_registry import ModelRegistry
from app.forecast.conformal import ConformalCalibration
from app.forecast.features import feature_names_for
from app.forecast.serve_drift import (
    DriftReference,
    MonitoredForecast,
    assess_drift,
)


class NoChampionError(LookupError):
    """Raised when a task has no promoted champion model to serve."""


class ArtifactIntegrityError(ValueError):
    """Raised when a loaded model artifact's hash does not match the registered
    ModelVersion.artifact_hash -- the runtime refuses to serve it."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ModelArtifact:
    """A loaded, hash-verified booster plus the ModelVersion it belongs to."""

    model_version: ModelVersion
    feature_names: tuple[str, ...]
    booster: object  # xgboost.Booster; typed as object to avoid an import-time xgboost dependency


class ForecastRuntime:
    """Serves point-in-time forecasts from registered, hash-verified models.

    `artifact_resolver` maps a ModelVersion to the filesystem path of its
    committed booster. It is injected (not hardcoded) so the same runtime works
    for the real realdata/output/*_model.json artifacts, a test's temp models,
    or a future object-store-backed resolver -- the runtime does not assume
    where artifacts live.
    """

    def __init__(self, registry: ModelRegistry, artifact_resolver) -> None:
        self._registry = registry
        self._resolve_artifact_path = artifact_resolver
        self._cache: dict[ModelVersionId, ModelArtifact] = {}

    def load(self, model_version: ModelVersion) -> ModelArtifact:
        """Load a booster and verify its bytes against the registered hash.

        Skips the hash check only if the ModelVersion recorded a non-hash
        placeholder (e.g. the NTD model's NOT_COMPUTED artifact_hash, ADR-0010)
        -- in that case there is no committed artifact to verify against, and
        attempting to serve it is a caller error surfaced as ArtifactIntegrityError.
        """
        cached = self._cache.get(model_version.model_version_id)
        if cached is not None:
            return cached

        if not model_version.artifact_hash or ":" in model_version.artifact_hash:
            raise ArtifactIntegrityError(
                f"model {model_version.model_version_id} has no verifiable artifact_hash "
                f"({model_version.artifact_hash!r}); refusing to serve it"
            )

        path = Path(self._resolve_artifact_path(model_version))
        if not path.exists():
            raise ArtifactIntegrityError(
                f"artifact for model {model_version.model_version_id} not found at {path}"
            )
        actual = _sha256_file(path)
        if actual != model_version.artifact_hash:
            raise ArtifactIntegrityError(
                f"artifact hash mismatch for model {model_version.model_version_id}: "
                f"registered {model_version.artifact_hash}, file at {path} is {actual}"
            )

        import xgboost as xgb

        booster = xgb.Booster()
        booster.load_model(str(path))
        artifact = ModelArtifact(
            model_version=model_version,
            feature_names=feature_names_for(model_version.feature_schema_version),
            booster=booster,
        )
        self._cache[model_version.model_version_id] = artifact
        return artifact

    def forecast(
        self,
        task: str,
        feature_row: dict,
        *,
        horizon_start: datetime,
        horizon_end: datetime,
        issued_at: datetime,
        interval_half_width: float | None = None,
        calibration: ConformalCalibration | None = None,
    ) -> ForecastVintage:
        """Serve one forecast for `task` from its champion model.

        `feature_row` is a point-in-time feature dict; every name in the model's
        feature schema must be present (a missing feature raises, rather than
        being silently defaulted to zero and producing a quietly-wrong number).

        Two mutually exclusive interval paths (supplying both raises):
        - `interval_half_width`: the original manual symmetric half-width,
          applied around the point estimate as a declared model interval.
        - `calibration`: a fitted `ConformalCalibration` (app.forecast.
          conformal), yielding a split-conformal interval at a target coverage.
          Distribution-free under exchangeability, NOT a probability or a
          guarantee (blueprint 01); the repo already measured overcoverage.

        None on both means the vintage carries a point estimate only.
        """
        if interval_half_width is not None and calibration is not None:
            raise ValueError(
                "provide either interval_half_width or a conformal calibration, not both"
            )
        for instant in (horizon_start, horizon_end, issued_at):
            _require_utc(instant)

        champion = self._registry.champion(task)
        if champion is None:
            raise NoChampionError(f"no champion model promoted for task {task!r}")

        artifact = self.load(champion)
        missing = [name for name in artifact.feature_names if name not in feature_row]
        if missing:
            raise KeyError(
                f"feature_row is missing required feature(s) for "
                f"{champion.feature_schema_version}: {missing}"
            )

        import pandas as pd
        import xgboost as xgb

        ordered = [{name: feature_row[name] for name in artifact.feature_names}]
        matrix = xgb.DMatrix(pd.DataFrame(ordered)[list(artifact.feature_names)])
        point = float(artifact.booster.predict(matrix)[0])

        low = high = None
        if calibration is not None:
            low, high = calibration.apply(point)
        elif interval_half_width is not None:
            if interval_half_width < 0:
                raise ValueError("interval_half_width must be non-negative")
            low = point - interval_half_width
            high = point + interval_half_width

        return ForecastVintage(
            tenant_id=champion.tenant_id,
            model_version_id=champion.model_version_id,
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            issued_at=issued_at,
            point_estimate=point,
            interval_low=low,
            interval_high=high,
            eventual_actual=None,
        )

    def forecast_monitored(
        self,
        task: str,
        feature_row: dict,
        *,
        horizon_start: datetime,
        horizon_end: datetime,
        issued_at: datetime,
        reference: DriftReference,
        serving_window: list[dict] | None = None,
        interval_half_width: float | None = None,
        calibration: ConformalCalibration | None = None,
    ) -> MonitoredForecast:
        """Serve a forecast with a serve-time drift verdict ATTACHED.

        Identical to `forecast` in what it predicts -- the returned
        `MonitoredForecast.vintage` is exactly the vintage `forecast` would have
        produced -- plus a `DriftVerdict` comparing the incoming feature
        distribution against `reference`, the model's training-window baseline
        (app.forecast.serve_drift).

        REPORT, DO NOT DECIDE. Drift never blocks, suppresses, widens or
        rewrites the forecast; ADR-0034 kept detection separate from action so
        a monitor cannot silently change what serves. Under detected drift the
        result carries `interval_caveat`, an explicit statement that the
        conformal interval's coverage guarantee is NOT supported, because that
        guarantee holds only under exchangeability -- the very assumption
        detected drift contradicts.

        `serving_window` is the batch of recent feature rows the distribution
        test runs on. A single feature row cannot support a PSI or a KS
        statistic, so when it is omitted the window defaults to `[feature_row]`
        and the verdict is honestly `insufficient_data` -- never a confident
        `no_drift` inferred from one point.
        """
        vintage = self.forecast(
            task,
            feature_row,
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            issued_at=issued_at,
            interval_half_width=interval_half_width,
            calibration=calibration,
        )
        verdict = assess_drift(
            reference,
            serving_window if serving_window is not None else [feature_row],
            target_coverage=calibration.target_coverage if calibration is not None else None,
        )
        return MonitoredForecast(vintage=vintage, drift=verdict)
