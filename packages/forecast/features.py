"""Feature-schema contracts for the forecast runtime.

`ModelVersion.feature_schema_version` is an opaque label (ADR-0010,
packages.core.task_registry). This module binds the two real schema labels
this repository's models actually use to their ordered feature-name lists, so
the runtime can build a correctly-ordered, correctly-named feature vector for
a model without guessing. The lists are the exact `features` lists from
realdata/train_real_models.py (zone-hour) and realdata/model_ntd_monthly.py
(agency-month), cross-checked against each committed booster's own feature
names.
"""

from __future__ import annotations


class FeatureSchemaError(KeyError):
    """Raised when a feature_schema_version has no known feature-name list."""


# zone_hour_demand_v1: the 16-feature schema shared by the aar/chicago_tnp/
# mta_bus/mta_subway boosters. Order matters -- XGBoost matches by name here
# (the boosters carry feature names), but the runtime builds columns in this
# order for determinism and so a name typo surfaces as a validation error.
_ZONE_HOUR_DEMAND_V1 = (
    "hour",
    "hour_sin",
    "hour_cos",
    "dow",
    "month",
    "is_weekend",
    "is_holiday",
    "tmax_c",
    "tmin_c",
    "precip_mm",
    "snow_cm",
    "lag1",
    "lag7",
    "lag14",
    "roll28",
    "borough",
)

# agency_month_demand_v1: the NTD monthly schema. The "zone" column for the
# hourly models is `borough`; for NTD the trailing entity column is the agency
# category `ntd_id_cat` (dropped in the cold-start variant). This is the
# FEATURES_FULL list from realdata/model_ntd_monthly.py.
_AGENCY_MONTH_DEMAND_V1 = (
    "month",
    "year",
    "month_sin",
    "month_cos",
    "lag1",
    "lag2",
    "lag3",
    "lag12",
    "roll12",
    "yoy_ratio",
    "vrh_lag1",
    "vrm_lag1",
    "voms_lag1",
    "ntd_id_cat",
)

FEATURE_SCHEMAS: dict[str, tuple[str, ...]] = {
    "zone_hour_demand_v1": _ZONE_HOUR_DEMAND_V1,
    "agency_month_demand_v1": _AGENCY_MONTH_DEMAND_V1,
}


def feature_names_for(feature_schema_version: str) -> tuple[str, ...]:
    try:
        return FEATURE_SCHEMAS[feature_schema_version]
    except KeyError:
        raise FeatureSchemaError(
            f"no feature-name list registered for feature_schema_version "
            f"{feature_schema_version!r}; known: {sorted(FEATURE_SCHEMAS)}"
        ) from None
