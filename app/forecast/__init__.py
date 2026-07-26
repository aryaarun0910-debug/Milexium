"""Program E (first slice): Milexium Forecast runtime.

Turns the real trained models this repository already has (knowledge/docs/MODEL_CARDS.md,
catalogued in app.core.ModelRegistry as ModelVersion entities) into
forecasts the runtime serves through one interface -- rather than a pile of
scripts. The runtime resolves the champion model for a task from the registry,
loads its committed XGBoost artifact, VERIFIES the artifact's hash against the
registered ModelVersion.artifact_hash before trusting it (reusing the
generator/verifier-separation discipline: never run an artifact whose bytes
don't match what was registered), predicts on a point-in-time feature row, and
emits a canonical ForecastVintage.

Honesty (blueprint 05 + knowledge/architecture/decisions/0001): these are forecasts on
real *aggregate* public mobility data (paratransit/TNP/transit demand), with a
declared uncertainty interval. A ForecastVintage interval is a model interval,
not a probability or a guarantee, and aggregate forecasts do not validate
individual dispatch decisions -- the runtime records the numbers, it does not
upgrade their status. Everything here is Demonstrated on public data; nothing
becomes Validated without consented operator data.

v0.4 adds the CAPACITY DECISION the forecast exists to serve
(app.forecast.capacity): vehicle-revenue-hours and vehicles-in-service at
a service level chosen by an EXPLICITLY STATED cost asymmetry (the newsvendor
critical ratio Cu/(Cu+Co)), rather than a trip count at an implicitly symmetric
squared-error optimum. A `CapacityRecommendation` INHERITS the interval's
guarantee status from the `MonitoredForecast` it was derived from, so a
recommendation built on an `unsupported` interval structurally cannot claim an
evidenced service level -- enforced by a model validator, not a docstring.

v0.3 scope: batch point-in-time prediction + interval + ForecastVintage
emission, gated on registry resolution and artifact hash verification, for
every real model (AAR / Chicago TNP / MTA bus / MTA subway), with serve-time
split-conformal prediction intervals at a target coverage (app.forecast.
conformal), and serve-time DRIFT MONITORING attached to the served forecast
(app.forecast.serve_drift): the incoming feature distribution is compared
against the model's training-window reference using Program D's drift service
(app.core.drift, imported read-only), and a drifted forecast carries an
explicit statement that its conformal interval's coverage guarantee is not
supported -- because that guarantee holds only under exchangeability, which is
precisely what detected drift contradicts. The monitor REPORTS; it never
blocks, suppresses or rewrites a forecast (acting on drift belongs to the
promotion controller and the operator, ADR-0034). Not built (Specified):
online/streaming inference, categorical (zone-column) drift tests, serve-time
recalibration under drift, model routing beyond champion lookup.
"""

from app.forecast.capacity import (
    CENSORED_DEMAND_LIMITATION,
    MARGINAL_COVERAGE_LIMITATION,
    PRODUCTIVITY_POINT_ESTIMATE_LIMITATION,
    CapacityRecommendation,
    CostAsymmetry,
    ProductivityBasis,
    asymmetric_capacity_cost,
    empirical_service_level,
    expected_asymmetric_cost,
    recommend_capacity,
)
from app.forecast.conformal import (
    ConformalCalibration,
    ConformalQuantile,
    empirical_coverage,
    empirical_one_sided_coverage,
    fit_conformal_from_predictions,
    fit_one_sided_conformal,
    fit_symmetric_conformal,
    fit_two_sided_conformal,
)
from app.forecast.features import FEATURE_SCHEMAS, FeatureSchemaError, feature_names_for
from app.forecast.runtime import (
    ArtifactIntegrityError,
    ForecastRuntime,
    ModelArtifact,
    NoChampionError,
)
from app.forecast.serve_drift import (
    ARTIFACT_CARRIES_NO_REFERENCE_REASON,
    DEFAULT_KS_FAMILY_ALPHA,
    DEFAULT_MAX_REFERENCE_SAMPLE,
    MIN_ROWS_FOR_STABLE_STATISTIC,
    DriftReference,
    DriftVerdict,
    FeatureDriftResult,
    MonitoredForecast,
    ReferenceProvenance,
    assess_drift,
    derive_reference_from_frame,
    derive_reference_from_rows,
    reference_from_model_artifact,
    sha256_of_file,
)

__all__ = [
    "FEATURE_SCHEMAS",
    "FeatureSchemaError",
    "feature_names_for",
    "ArtifactIntegrityError",
    "ForecastRuntime",
    "ModelArtifact",
    "NoChampionError",
    "ConformalCalibration",
    "ConformalQuantile",
    "fit_symmetric_conformal",
    "fit_two_sided_conformal",
    "fit_conformal_from_predictions",
    "fit_one_sided_conformal",
    "empirical_coverage",
    "empirical_one_sided_coverage",
    "CENSORED_DEMAND_LIMITATION",
    "MARGINAL_COVERAGE_LIMITATION",
    "PRODUCTIVITY_POINT_ESTIMATE_LIMITATION",
    "CapacityRecommendation",
    "CostAsymmetry",
    "ProductivityBasis",
    "asymmetric_capacity_cost",
    "empirical_service_level",
    "expected_asymmetric_cost",
    "recommend_capacity",
    "ARTIFACT_CARRIES_NO_REFERENCE_REASON",
    "DEFAULT_KS_FAMILY_ALPHA",
    "DEFAULT_MAX_REFERENCE_SAMPLE",
    "MIN_ROWS_FOR_STABLE_STATISTIC",
    "DriftReference",
    "DriftVerdict",
    "FeatureDriftResult",
    "MonitoredForecast",
    "ReferenceProvenance",
    "assess_drift",
    "derive_reference_from_frame",
    "derive_reference_from_rows",
    "reference_from_model_artifact",
    "sha256_of_file",
]

CONTRACT_VERSION = "0.3.0"
