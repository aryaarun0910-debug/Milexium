"""Real `ModelVersion` fixtures for the model registry (themis/core), one
per model documented in forge/knowledge/docs/MODEL_CARDS.md as of the 2026-07-22 model-card
generation. Every value below is either read from a committed file (cited
per field) or mechanically derived from one -- never an invented placeholder
except where a field is explicitly marked NOT_COMPUTED (see `ntd_monthly`).

`ModelVersion.tenant_id` is mandatory in the canonical contract (Program A),
but none of these models is tenant-specific: they are trained once on public
aggregate data and evaluated with no consented-operator tenant attached yet
(forge/knowledge/docs/MODEL_CARDS.md: "external validity to a specific operator's own
bookings is unproven until a pilot"). `reference_tenant_id()` mints one
shared placeholder tenant to satisfy that mandatory field rather than
attaching these models to a fictional real customer -- see this packet's
report for why this is flagged as a design decision rather than a contract
change.
"""

from __future__ import annotations

from themis.canonical import ModelVersion, ModelVersionId, TenantId, new_id

from conformance.fixtures.builders import utc

ZONE_HOUR_DEMAND_SCHEMA = "zone_hour_demand_v1"
"""16-feature schema shared by aar/chicago_tnp/mta_bus/mta_subway: hour,
hour_sin, hour_cos, dow, month, is_weekend, is_holiday, tmax_c, tmin_c,
precip_mm, snow_cm, lag1, lag7, lag14, roll28, <zone column> -- exactly the
`features` list in data/curated/train_real_models.py, confirmed against each
committed booster's own `num_feature: "16"` (data/curated/output/*_model.json)."""

AGENCY_MONTH_DEMAND_SCHEMA = "agency_month_demand_v1"
"""14/13-feature schema (13 for cold-start, no ntd_id_cat) used only by
ntd_monthly: month, year, month_sin, month_cos, lag1, lag2, lag3, lag12,
roll12, yoy_ratio, vrh_lag1, vrm_lag1, voms_lag1, [ntd_id_cat] -- exactly
`FEATURES_FULL` in data/curated/model_ntd_monthly.py."""

NTD_ARTIFACT_HASH_PLACEHOLDER = (
    "NOT_COMPUTED:data/curated/model_ntd_monthly.py never calls "
    "model.save_model(), so no trained-booster artifact file is committed "
    "for this model version -- unlike the other four, which each have a "
    "data/curated/output/*_model.json this fixture hashes for real."
)


def reference_tenant_id() -> TenantId:
    return new_id(TenantId)


def build_real_model_versions() -> dict[str, ModelVersion]:
    """One `ModelVersion` per real, trained-and-evaluated model in
    forge/knowledge/docs/MODEL_CARDS.md. Keys match this repository's own model file/metric
    names (data/curated/output/*_model.json, data/curated/metrics_real.json,
    data/curated/metrics_ntd_monthly.json). `aar` is the one MODEL_CARDS.md
    labels "PRODUCT TARGET"; the others are generalization evidence."""
    tenant_id = reference_tenant_id()

    aar = ModelVersion(
        model_version_id=new_id(ModelVersionId),
        tenant_id=tenant_id,
        task="forecast.demand",
        # sha256 of data/curated/panels/aar_hourly_borough.csv.gz, from
        # data/curated/manifests/aar_hourly_borough.csv.gz.json ("sha256").
        training_data_manifest_hash="83141d404e1cbbfd8aa243e5375d36d77288d38e4cfbd423fe6aa7d8f673680e",
        feature_schema_version=ZONE_HOUR_DEMAND_SCHEMA,
        # data/curated/metrics_real.json -> nyc_access_a_ride.valid_span.
        evaluation_window_start=utc(2026, 3, 2),
        evaluation_window_end=utc(2026, 5, 31),
        # sha256 of the committed data/curated/output/aar_model.json booster dump.
        artifact_hash="f8fa4db240e6f892177292100217aa9d968530cc7d8aa3f90fd9d28fb1cb6c0c",
    )

    chicago_tnp = ModelVersion(
        model_version_id=new_id(ModelVersionId),
        tenant_id=tenant_id,
        task="forecast.demand",
        # data/curated/manifests/chicago_tnp_zone_hour.csv.gz.json ("sha256").
        training_data_manifest_hash="5dd24130e6dbfea2fc99e3b4176e529712567a953126e337b0328e1881cd820b",
        feature_schema_version=ZONE_HOUR_DEMAND_SCHEMA,
        # data/curated/metrics_real.json -> chicago_tnp.valid_span.
        evaluation_window_start=utc(2026, 3, 2),
        evaluation_window_end=utc(2026, 5, 31),
        # sha256 of the committed data/curated/output/chicago_model.json booster dump.
        artifact_hash="0fa75ce77c030d4aef985a3be03f5ddcee5f7ebc1815b5789fdc967588353882",
    )

    mta_bus = ModelVersion(
        model_version_id=new_id(ModelVersionId),
        tenant_id=tenant_id,
        task="forecast.demand",
        # data/curated/manifests/mta_bus_route_hour.csv.gz.json ("sha256").
        training_data_manifest_hash="445d361e8dd992b0e97f5eb9fb56ce02a230e44299842d62d94a894ce6d6b11c",
        feature_schema_version=ZONE_HOUR_DEMAND_SCHEMA,
        # data/curated/metrics_real.json -> mta_bus.valid_span.
        evaluation_window_start=utc(2026, 4, 15),
        evaluation_window_end=utc(2026, 7, 14),
        # sha256 of the committed data/curated/output/mta_bus_model.json booster dump.
        artifact_hash="1810b2362369408aedc17f6565191c6e93fd208c42a389377c8c35cde170472e",
    )

    mta_subway = ModelVersion(
        model_version_id=new_id(ModelVersionId),
        tenant_id=tenant_id,
        task="forecast.demand",
        # data/curated/manifests/mta_subway_station_hour.csv.gz.json ("sha256").
        training_data_manifest_hash="fa16e5347ce930f5a421ed5829ab97dc4f6d37594a0aa1c0f031e49bf53b140c",
        feature_schema_version=ZONE_HOUR_DEMAND_SCHEMA,
        # data/curated/metrics_real.json -> mta_subway.valid_span.
        evaluation_window_start=utc(2026, 4, 9),
        evaluation_window_end=utc(2026, 7, 8),
        # sha256 of the committed data/curated/output/mta_subway_model.json booster dump.
        artifact_hash="7d2dbcbbbbf4f7eff839abf36c99bdac39eff1795c9c4f07fdf62237a550af04",
    )

    ntd_monthly = ModelVersion(
        model_version_id=new_id(ModelVersionId),
        tenant_id=tenant_id,
        task="forecast.demand",
        # data/curated/manifests/ntd_monthly_dr.csv.gz.json ("sha256").
        training_data_manifest_hash="72a97da33256f212e9edd2202e505d6286235f1e8999f6e543628b72002cb8ba",
        feature_schema_version=AGENCY_MONTH_DEMAND_SCHEMA,
        # Derived, not directly stated: data/curated/model_ntd_monthly.py's
        # temporal split holds out HORIZON=12 months ending at the panel's
        # own date_max (data/curated/manifests/ntd_monthly_dr.csv.gz.json:
        # "date_max": "2026-05-01"), so the temporal validation window is
        # the 12 months immediately before that date.
        evaluation_window_start=utc(2025, 5, 1),
        evaluation_window_end=utc(2026, 5, 1),
        artifact_hash=NTD_ARTIFACT_HASH_PLACEHOLDER,
    )

    return {
        "aar": aar,
        "chicago_tnp": chicago_tnp,
        "mta_bus": mta_bus,
        "mta_subway": mta_subway,
        "ntd_monthly": ntd_monthly,
    }
