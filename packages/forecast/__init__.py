"""Program E (first slice): Milexium Forecast runtime.

Turns the real trained models this repository already has (docs/MODEL_CARDS.md,
catalogued in packages.core.ModelRegistry as ModelVersion entities) into
forecasts the runtime serves through one interface -- rather than a pile of
scripts. The runtime resolves the champion model for a task from the registry,
loads its committed XGBoost artifact, VERIFIES the artifact's hash against the
registered ModelVersion.artifact_hash before trusting it (reusing the
generator/verifier-separation discipline: never run an artifact whose bytes
don't match what was registered), predicts on a point-in-time feature row, and
emits a canonical ForecastVintage.

Honesty (blueprint 05 + architecture/decisions/0001): these are forecasts on
real *aggregate* public mobility data (paratransit/TNP/transit demand), with a
declared uncertainty interval. A ForecastVintage interval is a model interval,
not a probability or a guarantee, and aggregate forecasts do not validate
individual dispatch decisions -- the runtime records the numbers, it does not
upgrade their status. Everything here is Demonstrated on public data; nothing
becomes Validated without consented operator data.

v0.1 scope: batch point-in-time prediction + interval + ForecastVintage
emission, gated on registry resolution and artifact hash verification. Not
built (Specified): online/streaming inference, drift/change-point services,
conformal recalibration at serve time, model routing beyond champion lookup.
"""

from packages.forecast.features import FEATURE_SCHEMAS, FeatureSchemaError, feature_names_for
from packages.forecast.runtime import (
    ArtifactIntegrityError,
    ForecastRuntime,
    ModelArtifact,
    NoChampionError,
)

__all__ = [
    "FEATURE_SCHEMAS",
    "FeatureSchemaError",
    "feature_names_for",
    "ArtifactIntegrityError",
    "ForecastRuntime",
    "ModelArtifact",
    "NoChampionError",
]

CONTRACT_VERSION = "0.1.0"
