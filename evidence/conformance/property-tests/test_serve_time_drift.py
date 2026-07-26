"""Program E conformance: serve-time drift monitoring attached to the forecast.

Closes the gap between ADR-0034 (a drift/change-point service nobody at serve
time called) and ADR-0030 (serve-time conformal intervals that assume
exchangeability without ever checking it). Before this, a model could drift
arbitrarily far from its training distribution and the runtime would keep
returning confident point estimates wrapped in confident-looking intervals.

The properties asserted here are the four the packet names:

1. An in-distribution serve reports `no_drift` and an UNQUALIFIED interval.
2. A deliberately shifted serve reports `drift` AND marks the interval's
   coverage guarantee `unsupported` -- because a split-conformal interval is
   distribution-free only under EXCHANGEABILITY, which detected drift is direct
   evidence against.
3. REPORT, DO NOT BLOCK: the forecast comes back in BOTH cases, and under drift
   the vintage is byte-identical to the one the unmonitored `forecast` path
   produces. Asserted explicitly, because a monitor that silently changes what
   serves is worse than one that warns.
4. The reference is TRACEABLE to its source -- a committed panel pinned by
   SHA-256 over the model's training window -- not invented. `ModelVersion`
   carries no reference distribution, and that gap is asserted rather than
   papered over.

Plus the edge case: too few rows to compute a stable statistic reports
`insufficient_data`, never a confident `no_drift`.

REAL vs SYNTHETIC is labelled per section. The synthetic block trains a
throwaway booster in-process (no dependency on gitignored artifacts). The REAL
block derives a reference from the committed NYC Access-A-Ride hourly panel
(realdata/panels/aar_hourly_borough.csv.gz + weather_daily.csv, both tracked)
over the real AAR model's training window, and serves against the untouched
spring-2026 validation window -- the exact window whose committed intervals
ADR-0030 measured at 98.1% coverage against a 90% target. The monitor is shown
to flag that window as drifted, which is what makes the overcoverage a
predictable consequence rather than a surprise. The end-to-end serve through
the real committed booster skips cleanly when the gitignored
realdata/output/aar_model.json is absent.

Status: Demonstrated. Never operator-Validated.
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
    ARTIFACT_CARRIES_NO_REFERENCE_REASON,
    MIN_ROWS_FOR_STABLE_STATISTIC,
    ForecastRuntime,
    assess_drift,
    derive_reference_from_frame,
    derive_reference_from_rows,
    fit_symmetric_conformal,
    reference_from_model_artifact,
    sha256_of_file,
)
from app.forecast.features import feature_names_for

_REPO = Path(__file__).resolve().parents[3]
_PANELS = _REPO / "realdata" / "panels"
_AAR_PANEL = _PANELS / "aar_hourly_borough.csv.gz"
_WEATHER = _PANELS / "weather_daily.csv"
_AAR_MODEL = _REPO / "realdata" / "output" / "aar_model.json"

SCHEMA = "zone_hour_demand_v1"
# The 15 continuous features. The trailing zone column (`borough`) is a
# category: PSI/KS are continuous-distribution tests, so it is deliberately not
# monitored (and `derive_reference_from_frame` records the skip with a reason).
NUMERIC_FEATURES = tuple(n for n in feature_names_for(SCHEMA) if n != "borough")
TARGET_COVERAGE = 0.90


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


# =========================================================================== #
# SYNTHETIC fixtures: a throwaway booster + seeded feature distributions
# =========================================================================== #
def _train_tiny_zone_hour_model(path: Path) -> None:
    """Throwaway booster carrying the real zone_hour_demand_v1 feature names,
    so the runtime's schema binding and prediction path are real while the
    artifact is disposable (same device as test_forecast_runtime.py)."""
    import pandas as pd
    import xgboost as xgb

    names = list(feature_names_for(SCHEMA))
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(300, len(names))), columns=names)
    y = X["lag1"] * 2 + X["roll28"] + rng.normal(size=300)
    booster = xgb.train(
        {"max_depth": 2, "objective": "reg:squarederror"},
        xgb.DMatrix(X, label=y),
        num_boost_round=8,
    )
    booster.save_model(str(path))


def _runtime_for(artifact: Path) -> tuple[ForecastRuntime, ModelVersion]:
    registry = ModelRegistry()
    mv = ModelVersion(
        model_version_id=new_id(ModelVersionId),
        tenant_id=new_id(TenantId),
        task="forecast.demand",
        training_data_manifest_hash="0" * 64,
        feature_schema_version=SCHEMA,
        evaluation_window_start=_utc(2026, 3, 2),
        evaluation_window_end=_utc(2026, 5, 31),
        artifact_hash=hashlib.sha256(artifact.read_bytes()).hexdigest(),
    )
    registry.register(mv)
    registry.promote(mv.model_version_id)
    return ForecastRuntime(registry, artifact_resolver=lambda _mv: artifact), mv


def _synthetic_rows(n: int, *, seed: int, shift: float = 0.0) -> list[dict]:
    """SYNTHETIC feature rows. `shift` moves the demand-history and temperature
    features, the ones a real seasonal or regime change actually moves."""
    rng = np.random.default_rng(seed)
    shifted = {"lag1", "lag7", "lag14", "roll28", "tmax_c", "tmin_c"}
    rows = []
    for _ in range(n):
        row = {name: float(rng.normal(shift if name in shifted else 0.0, 1.0)) for name in NUMERIC_FEATURES}
        row["borough"] = 1.0  # the zone column the model needs but the monitor does not test
        rows.append(row)
    return rows


def _synthetic_reference(n: int = 2000, *, seed: int = 0):
    return derive_reference_from_rows(
        _synthetic_rows(n, seed=seed),
        NUMERIC_FEATURES,
        source_kind="synthetic",
        description="SYNTHETIC seeded N(0,1) training-window stand-in",
        derivation=f"numpy default_rng({seed}), {n} rows, 15 continuous zone_hour_demand_v1 features",
    )


@pytest.fixture(scope="module")
def tiny_artifact(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("serve_drift") / "tiny_model.json"
    _train_tiny_zone_hour_model(path)
    return path


# =========================================================================== #
# The artifact carries no reference -- stated, not invented (SYNTHETIC)
# =========================================================================== #
def test_model_artifact_carries_no_drift_reference_and_says_so(tiny_artifact: Path) -> None:
    """Requirement 1's precondition: the reference must come from the model's
    own training window, not be invented. `ModelVersion` has no such field, so
    the lookup honestly returns None with a recorded reason -- rather than
    fabricating a plausible-looking baseline that would make every verdict a
    fiction."""
    _, mv = _runtime_for(tiny_artifact)
    assert reference_from_model_artifact(mv) is None
    assert "no per-feature training reference distribution" in ARTIFACT_CARRIES_NO_REFERENCE_REASON
    assert "committed panel" in ARTIFACT_CARRIES_NO_REFERENCE_REASON


# =========================================================================== #
# Property 1: in-distribution -> no drift, unqualified interval (SYNTHETIC)
# =========================================================================== #
def test_in_distribution_serve_reports_no_drift_and_an_unqualified_interval(
    tiny_artifact: Path,
) -> None:
    runtime, _ = _runtime_for(tiny_artifact)
    reference = _synthetic_reference()
    window = _synthetic_rows(500, seed=99)
    calibration = fit_symmetric_conformal(
        np.random.default_rng(3).normal(0, 1, 400), target_coverage=TARGET_COVERAGE
    )

    served = runtime.forecast_monitored(
        "forecast.demand",
        window[0],
        horizon_start=_utc(2026, 7, 24, 8),
        horizon_end=_utc(2026, 7, 24, 9),
        issued_at=_utc(2026, 7, 23, 20),
        reference=reference,
        serving_window=window,
        calibration=calibration,
    )

    assert served.drift_status == "no_drift"
    assert served.drift.drifted_features == ()
    assert served.interval_guarantee == "unqualified"
    assert served.interval_guarantee_supported is True
    assert served.interval_caveat is None  # UNQUALIFIED: nothing to warn about
    low, high = served.interval
    assert low <= served.point_estimate <= high


# =========================================================================== #
# Property 2: shifted -> drift AND the guarantee flagged unsupported (SYNTHETIC)
# =========================================================================== #
def test_shifted_serve_reports_drift_and_flags_the_interval_guarantee_unsupported(
    tiny_artifact: Path,
) -> None:
    runtime, _ = _runtime_for(tiny_artifact)
    reference = _synthetic_reference()
    shifted = _synthetic_rows(500, seed=99, shift=2.0)
    calibration = fit_symmetric_conformal(
        np.random.default_rng(3).normal(0, 1, 400), target_coverage=TARGET_COVERAGE
    )

    served = runtime.forecast_monitored(
        "forecast.demand",
        shifted[0],
        horizon_start=_utc(2026, 7, 24, 8),
        horizon_end=_utc(2026, 7, 24, 9),
        issued_at=_utc(2026, 7, 23, 20),
        reference=reference,
        serving_window=shifted,
        calibration=calibration,
    )

    assert served.drift_status == "drift"
    assert set(served.drift.drifted_features) >= {"lag1", "lag7", "lag14", "roll28", "tmax_c", "tmin_c"}
    # The single most important honesty property in the packet.
    assert served.interval_guarantee == "unsupported"
    assert served.interval_guarantee_supported is False
    caveat = served.interval_caveat
    assert caveat is not None
    assert "NOT SUPPORTED" in caveat
    assert "EXCHANGEABILITY" in caveat
    assert "90%" in caveat  # the target coverage it is refusing to claim
    # and the caveat rides on the same object as the number
    assert caveat in served.summary()
    assert f"{served.point_estimate:.3f}" in served.summary()


def test_unmonitored_forecast_path_has_no_such_caveat_to_offer(tiny_artifact: Path) -> None:
    """The gap this packet closes, made visible: `forecast` returns a
    ForecastVintage with an interval and no way at all to express that the
    interval's assumption is in question. That is why the verdict has to be
    attached to a wrapping object rather than left in a log."""
    runtime, _ = _runtime_for(tiny_artifact)
    vintage = runtime.forecast(
        "forecast.demand",
        _synthetic_rows(1, seed=5, shift=2.0)[0],
        horizon_start=_utc(2026, 7, 24, 8),
        horizon_end=_utc(2026, 7, 24, 9),
        issued_at=_utc(2026, 7, 23, 20),
        calibration=fit_symmetric_conformal([1.0, 2.0, 3.0], target_coverage=TARGET_COVERAGE),
    )
    assert not hasattr(vintage, "interval_caveat")
    assert not hasattr(vintage, "drift")


# =========================================================================== #
# Property 3: REPORT, DO NOT BLOCK (SYNTHETIC)
# =========================================================================== #
@pytest.mark.parametrize("shift, expected_status", [(0.0, "no_drift"), (2.0, "drift")])
def test_forecast_is_returned_in_both_cases_and_is_never_suppressed(
    tiny_artifact: Path, shift: float, expected_status: str
) -> None:
    """Explicit: drift NEVER blocks, suppresses, or rewrites the forecast."""
    runtime, _ = _runtime_for(tiny_artifact)
    reference = _synthetic_reference()
    window = _synthetic_rows(500, seed=99, shift=shift)
    calibration = fit_symmetric_conformal(
        np.random.default_rng(3).normal(0, 1, 400), target_coverage=TARGET_COVERAGE
    )
    kwargs = dict(
        horizon_start=_utc(2026, 7, 24, 8),
        horizon_end=_utc(2026, 7, 24, 9),
        issued_at=_utc(2026, 7, 23, 20),
        calibration=calibration,
    )

    served = runtime.forecast_monitored(
        "forecast.demand", window[0], reference=reference, serving_window=window, **kwargs
    )
    plain = runtime.forecast("forecast.demand", window[0], **kwargs)

    assert served.drift_status == expected_status
    # the forecast exists and is FINITE in both cases
    assert served.vintage is not None
    assert np.isfinite(served.point_estimate)
    assert served.interval is not None
    # and it is exactly what the unmonitored path produced -- the monitor did
    # not widen the bounds, clamp the point, or refuse to serve.
    assert served.vintage.point_estimate == plain.point_estimate
    assert served.vintage.interval_low == plain.interval_low
    assert served.vintage.interval_high == plain.interval_high
    assert served.vintage.model_version_id == plain.model_version_id


def test_drift_monitoring_raises_nothing_on_a_hostile_serving_window(tiny_artifact: Path) -> None:
    """Report-don't-decide also means report-don't-crash: a serving window full
    of NaNs, missing keys and junk yields a verdict, not an exception, and the
    forecast is still served."""
    runtime, _ = _runtime_for(tiny_artifact)
    reference = _synthetic_reference()
    junk = [{"lag1": float("nan"), "unknown_feature": 1.0} for _ in range(200)]
    served = runtime.forecast_monitored(
        "forecast.demand",
        _synthetic_rows(1, seed=7)[0],
        horizon_start=_utc(2026, 7, 24, 8),
        horizon_end=_utc(2026, 7, 24, 9),
        issued_at=_utc(2026, 7, 23, 20),
        reference=reference,
        serving_window=junk,
    )
    assert served.drift_status == "insufficient_data"
    assert np.isfinite(served.point_estimate)


# =========================================================================== #
# Property 4: the reference is traceable (SYNTHETIC half)
# =========================================================================== #
def test_a_synthetic_reference_is_labelled_and_is_NOT_claimed_traceable() -> None:
    """A synthetic baseline must not be able to masquerade as a real one. It is
    labelled `synthetic` and `is_traceable` is False -- a caller can tell a
    demonstration apart from a derivation off committed data."""
    reference = _synthetic_reference()
    assert reference.provenance.source_kind == "synthetic"
    assert reference.provenance.is_traceable is False
    assert "SYNTHETIC" in reference.provenance.description
    assert "default_rng" in reference.provenance.derivation


# =========================================================================== #
# Edge cases: insufficient data NEVER becomes a confident no-drift (SYNTHETIC)
# =========================================================================== #
def test_a_single_serving_row_reports_insufficient_data_not_no_drift(
    tiny_artifact: Path,
) -> None:
    """The default when a caller supplies no serving window: one feature row
    cannot support a PSI or KS statistic, and the monitor says so."""
    runtime, _ = _runtime_for(tiny_artifact)
    served = runtime.forecast_monitored(
        "forecast.demand",
        _synthetic_rows(1, seed=11)[0],
        horizon_start=_utc(2026, 7, 24, 8),
        horizon_end=_utc(2026, 7, 24, 9),
        issued_at=_utc(2026, 7, 23, 20),
        reference=_synthetic_reference(),
    )
    assert served.drift_status == "insufficient_data"
    assert served.drift_status != "no_drift"
    assert served.interval_guarantee == "not_assessed"
    assert served.interval_guarantee_supported is False  # untested is not supported
    assert "NOT ASSESSED" in served.interval_caveat
    assert "not evidence of no drift" in served.interval_caveat
    assert np.isfinite(served.point_estimate)  # still served


@pytest.mark.parametrize("n_rows", [0, 1, 5, MIN_ROWS_FOR_STABLE_STATISTIC - 1])
def test_every_serving_window_below_the_minimum_reports_insufficient_data(n_rows: int) -> None:
    verdict = assess_drift(_synthetic_reference(), _synthetic_rows(n_rows, seed=1))
    assert verdict.status == "insufficient_data"
    assert verdict.interval_guarantee == "not_assessed"
    assert verdict.drifted_features == ()
    assert str(MIN_ROWS_FOR_STABLE_STATISTIC) in verdict.reason


def test_the_boundary_row_count_is_enough_to_report_a_verdict() -> None:
    """Exactly `MIN_ROWS_FOR_STABLE_STATISTIC` rows is sufficient -- the
    threshold is a floor, not a fence one row wide."""
    verdict = assess_drift(
        _synthetic_reference(), _synthetic_rows(MIN_ROWS_FOR_STABLE_STATISTIC, seed=1)
    )
    assert verdict.status in ("no_drift", "drift")


def test_a_thin_reference_also_reports_insufficient_data() -> None:
    """The floor applies to the baseline too: a reference built from a handful
    of training rows cannot clear a serve, and pretending otherwise would make
    every early-life model look permanently healthy."""
    thin = _synthetic_reference(n=10)
    verdict = assess_drift(thin, _synthetic_rows(500, seed=2))
    assert verdict.status == "insufficient_data"
    assert "reference holds only" in verdict.reason


def test_features_absent_from_the_serving_window_are_not_computable_not_clean() -> None:
    """A feature the serving window never carries is reported `computable=False`
    with a note. It is not silently treated as agreeing with the reference."""
    reference = _synthetic_reference()
    partial = [{k: v for k, v in row.items() if k != "roll28"} for row in _synthetic_rows(500, seed=4)]
    verdict = assess_drift(reference, partial)
    roll28 = next(f for f in verdict.features if f.feature == "roll28")
    assert roll28.computable is False
    assert roll28.flagged is False
    assert roll28.psi is None
    assert "0 serving row(s) carry this feature" in roll28.note


def test_a_constant_reference_feature_is_reported_not_crashed() -> None:
    """PSI's quantile bin edges collapse on a constant reference (Program D
    raises ValueError). The monitor records that as a per-feature note and
    still runs KS -- one degenerate feature does not take down the verdict."""
    rows = _synthetic_rows(500, seed=6)
    for row in rows:
        row["snow_cm"] = 0.0
    reference = derive_reference_from_rows(
        rows,
        NUMERIC_FEATURES,
        source_kind="synthetic",
        description="SYNTHETIC reference with a constant snow_cm column",
        derivation="seeded N(0,1) with snow_cm pinned to 0.0",
    )
    verdict = assess_drift(reference, _synthetic_rows(500, seed=8))
    snow = next(f for f in verdict.features if f.feature == "snow_cm")
    assert snow.computable is True
    assert snow.psi is None
    assert "PSI not computable" in snow.note
    assert snow.ks_p_value is not None  # KS still ran


def test_a_categorical_column_is_skipped_with_a_recorded_reason() -> None:
    """PSI/KS are continuous tests. The zone column is a category, so it is
    skipped and the skip is recorded -- rather than coercing category codes to
    floats and producing a meaningless statistic that looks like evidence."""
    frame = {
        name: [float(v) for v in np.random.default_rng(0).normal(size=200)]
        for name in NUMERIC_FEATURES
    }
    frame["borough"] = ["Bronx"] * 200
    reference = derive_reference_from_frame(
        frame,
        feature_names_for(SCHEMA),
        source_kind="synthetic",
        description="SYNTHETIC frame with a string zone column",
        derivation="seeded normals plus a literal borough column",
    )
    assert "borough" not in reference.feature_names
    skipped = dict(reference.provenance.skipped_features)
    assert "borough" in skipped
    assert "categorical" in skipped["borough"]


def test_ks_multiplicity_correction_keeps_in_distribution_serves_quiet() -> None:
    """The property behind 'in-distribution reports no drift': monitoring 15
    features at an uncorrected alpha=0.05 would flag a healthy serve about half
    the time. With the Bonferroni-corrected per-feature alpha the false-drift
    rate over a batch of independent in-distribution serves stays low."""
    reference = _synthetic_reference()
    verdicts = [assess_drift(reference, _synthetic_rows(300, seed=1000 + s)) for s in range(30)]
    false_drift = sum(v.status == "drift" for v in verdicts)
    assert false_drift <= 3, f"{false_drift}/30 in-distribution serves falsely flagged"
    assert all(v.ks_alpha_per_feature < 0.05 for v in verdicts)


# =========================================================================== #
# REAL DATA: NYC Access-A-Ride, committed panel + committed booster
# =========================================================================== #
# The AAR model's split, from realdata/metrics_real.json (produced by
# realdata/train_real_models.py): train <= 2025-09-03, validation > 2026-03-02.
AAR_TRAIN_END = "2025-09-03"
AAR_VALID_START = "2026-03-02"


def _build_real_aar_feature_panel():
    """REAL DATA. Rebuild the AAR zone-hour feature panel from the committed
    panels using train_real_models.py's exact recipe (full date x hour x borough
    grid with zero cells, calendar features, 1/7/14-day lags and the shifted
    28-day rolling mean, merged with NYC daily weather). This is the derivation
    recorded in the reference's provenance."""
    import pandas as pd
    from pandas.tseries.holiday import USFederalHolidayCalendar

    raw = pd.read_csv(_AAR_PANEL)
    raw = raw[raw.borough.isin(["Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"])]
    g = (
        raw.groupby(["day", "hour", "borough"])
        .trips.sum()
        .rename("y")
        .reset_index()
        .rename(columns={"day": "date"})
    )
    days = pd.date_range(g.date.min(), g.date.max(), freq="D")
    grid = pd.MultiIndex.from_product(
        [days, range(24), sorted(g.borough.unique())], names=["date", "hour", "borough"]
    ).to_frame(index=False)
    grid["date"] = grid.date.dt.strftime("%Y-%m-%d")
    g["date"] = pd.to_datetime(g.date).dt.strftime("%Y-%m-%d")
    panel = grid.merge(g, how="left", on=["date", "hour", "borough"])
    panel["y"] = panel.y.fillna(0)

    holidays = USFederalHolidayCalendar().holidays(start="2018-01-01", end="2027-01-01")
    panel["date"] = pd.to_datetime(panel.date)
    panel["dow"] = panel.date.dt.dayofweek
    panel["month"] = panel.date.dt.month
    panel["is_weekend"] = (panel.dow >= 5).astype(int)
    panel["is_holiday"] = panel.date.isin(holidays).astype(int)
    panel["hour_sin"] = np.sin(2 * np.pi * panel.hour / 24)
    panel["hour_cos"] = np.cos(2 * np.pi * panel.hour / 24)

    panel = panel.sort_values(["borough", "hour", "date"])
    by_slot = panel.groupby(["borough", "hour"], observed=True).y
    panel["lag1"] = by_slot.shift(1)
    panel["lag7"] = by_slot.shift(7)
    panel["lag14"] = by_slot.shift(14)
    panel["roll28"] = panel.groupby(["borough", "hour"], observed=True).y.transform(
        lambda s: s.shift(1).rolling(28, min_periods=7).mean()
    )
    weather = pd.read_csv(_WEATHER, parse_dates=["date"])
    weather = weather[weather.city == "nyc"].drop(columns=["city"])
    return panel.merge(weather, on="date", how="left")


@pytest.fixture(scope="module")
def real_aar_panel():
    if not _AAR_PANEL.exists() or not _WEATHER.exists():
        pytest.skip("committed AAR / weather panels absent")
    return _build_real_aar_feature_panel()


@pytest.fixture(scope="module")
def real_aar_reference(real_aar_panel):
    """REAL DATA. The drift reference derived from the AAR model's TRAINING
    window on the committed panel -- the model's own training distribution, not
    an invented baseline. The artifact carries no reference (see
    `reference_from_model_artifact`), so this derivation is what stands in, and
    it is recorded in full in the provenance."""
    import pandas as pd

    train = real_aar_panel[real_aar_panel.date <= pd.Timestamp(AAR_TRAIN_END)].dropna(
        subset=["lag14", "roll28"]
    )
    return derive_reference_from_frame(
        train,
        feature_names_for(SCHEMA),
        source_kind="committed_panel",
        description="REAL NYC Access-A-Ride borough-hour panel, model training window",
        derivation=(
            "realdata/train_real_models.py recipe: full date x hour x borough grid with "
            "zero cells, calendar + holiday features, 1/7/14-day lags and shifted 28-day "
            f"rolling mean, merged with NYC daily weather; rows with date <= {AAR_TRAIN_END} "
            "(the AAR model's train_span in realdata/metrics_real.json), lag14/roll28 non-null; "
            "subsampled with numpy default_rng(0)"
        ),
        panel_path="realdata/panels/aar_hourly_borough.csv.gz",
        training_window_start=_utc(2024, 1, 1),
        training_window_end=_utc(2025, 9, 3),
        seed=0,
    )


def _real_serving_rows(frame) -> list[dict]:
    """The serving window as the runtime sees it: a batch of feature-row dicts."""
    return frame[list(NUMERIC_FEATURES)].to_dict("records")


def test_real_reference_is_traceable_to_the_committed_panel(real_aar_reference) -> None:
    """REAL DATA. Property 4: the verdict cites a pinned source. The panel path
    AND its SHA-256 are recorded, and the hash matches the file on disk -- so a
    reader can re-derive the baseline, not just take its word."""
    provenance = real_aar_reference.provenance
    assert provenance.source_kind == "committed_panel"
    assert provenance.is_traceable is True
    assert provenance.panel_path == "realdata/panels/aar_hourly_borough.csv.gz"
    assert provenance.panel_sha256 == sha256_of_file(_AAR_PANEL)
    assert provenance.training_window_end.date().isoformat() == AAR_TRAIN_END
    assert provenance.n_source_rows > 50_000  # the real training window
    assert "train_real_models.py recipe" in provenance.derivation
    assert "aar_hourly_borough" in provenance.trace()
    # the categorical zone column is skipped, and the skip is stated
    assert "borough" in dict(provenance.skipped_features)


def test_real_spring_validation_window_is_detected_as_drift(
    real_aar_panel, real_aar_reference
) -> None:
    """REAL DATA. The headline demonstration. Serving on the untouched spring
    2026 validation window -- the exact window where ADR-0030 measured the
    committed AAR intervals at 98.1% coverage against a 90% target -- the
    monitor flags input drift against the training window. That overcoverage
    stops being a curiosity and becomes a predicted consequence: the calibration
    window and the serving window are not exchangeable, and now the runtime can
    SAY so at serve time instead of discovering it in a post-hoc audit.

    The seasonal signature ADR-0030 named (a winter-weighted calibration window
    against a spring serving window) is asserted specifically: month and both
    temperature features drift."""
    import pandas as pd

    rows = _real_serving_rows(real_aar_panel[real_aar_panel.date > pd.Timestamp(AAR_VALID_START)])
    assert len(rows) > 10_000
    verdict = assess_drift(real_aar_reference, rows, target_coverage=TARGET_COVERAGE)

    assert verdict.status == "drift"
    assert {"month", "tmax_c", "tmin_c"} <= set(verdict.drifted_features)
    assert verdict.interval_guarantee == "unsupported"
    assert "EXCHANGEABILITY" in verdict.interval_caveat
    assert verdict.is_traceable is True

    # the seasonal shift is an enormous effect, not a marginal p-value
    by_feature = {f.feature: f for f in verdict.features}
    assert by_feature["month"].psi_band == "significant"
    assert by_feature["tmax_c"].psi_band == "significant"
    assert by_feature["tmin_c"].psi_band == "significant"


def test_real_exchangeable_split_of_the_training_window_reports_no_drift(
    real_aar_panel, real_aar_reference
) -> None:
    """REAL DATA control. A random (exchangeable) split of the SAME training
    window is not drift. This is what proves the flag above is a real temporal
    distribution change rather than an artefact of the monitor -- the same
    control ADR-0030 used to isolate the winter->spring shift as the cause of
    the overcoverage."""
    import pandas as pd

    train = real_aar_panel[real_aar_panel.date <= pd.Timestamp(AAR_TRAIN_END)].dropna(
        subset=["lag14", "roll28"]
    )
    held_out = train.iloc[np.random.default_rng(7).permutation(len(train))[:4000]]
    verdict = assess_drift(real_aar_reference, _real_serving_rows(held_out))
    assert verdict.status == "no_drift"
    assert verdict.drifted_features == ()
    assert verdict.interval_guarantee == "unqualified"
    assert verdict.interval_caveat is None


@pytest.mark.skipif(not _AAR_MODEL.exists(), reason="real AAR booster absent (gitignored artifact)")
def test_real_committed_booster_serves_a_drifted_forecast_with_the_caveat_attached(
    real_aar_panel, real_aar_reference
) -> None:
    """REAL DATA, end to end: the real committed AAR booster (hash-verified by
    the runtime) serves a real forecast for a spring-2026 row, and the drift
    verdict for that serving window rides on the SAME object as the point
    estimate. The forecast is returned, not blocked."""
    import pandas as pd

    runtime, _ = _runtime_for(_AAR_MODEL)
    valid = real_aar_panel[real_aar_panel.date > pd.Timestamp(AAR_VALID_START)]
    window = _real_serving_rows(valid)
    feature_row = dict(window[0])
    feature_row["borough"] = 1  # zone column the booster needs; not monitored
    calibration = fit_symmetric_conformal(
        np.abs(valid.y.to_numpy(dtype=float)[:2000] - valid.roll28.to_numpy(dtype=float)[:2000]),
        target_coverage=TARGET_COVERAGE,
    )

    served = runtime.forecast_monitored(
        "forecast.demand",
        feature_row,
        horizon_start=_utc(2026, 5, 20, 8),
        horizon_end=_utc(2026, 5, 20, 9),
        issued_at=_utc(2026, 5, 19, 20),
        reference=real_aar_reference,
        serving_window=window,
        calibration=calibration,
    )

    assert np.isfinite(served.point_estimate)  # served, not blocked
    assert served.interval is not None
    assert served.drift_status == "drift"
    assert served.interval_guarantee_supported is False
    assert "NOT SUPPORTED" in served.interval_caveat
    assert "aar_hourly_borough" in served.summary()
