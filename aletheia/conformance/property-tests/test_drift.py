"""Conformance for the drift / change-point service (themis/core/drift.py),
Program D's adaptive-memory v0.1 slice.

Covers the three failure injections the packet names:

- A stationary stream reports no change-point (CUSUM in-control ARL is long: a
  batch of stationary streams stays overwhelmingly quiet).
- An injected mean shift IS detected, with the correct direction and just after
  the shift.
- PSI and KS flag a shifted distribution and pass an unshifted one.

Synthetic cases (seeded numpy) are labelled synthetic; the closing block runs
the change-point detector and both distribution tests on the REAL NYC
Access-A-Ride daily panel (data/curated/panels/aar_daily.csv) and its well-known
2020 COVID collapse. Status: Demonstrated.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

from themis.core.drift import (
    cusum_change_point,
    ks_two_sample,
    population_stability_index,
)

_AAR_DAILY = Path(__file__).resolve().parents[3] / "data" / "curated" / "panels" / "aar_daily.csv"


# --------------------------------------------------------------------------- #
# PSI (SYNTHETIC)
# --------------------------------------------------------------------------- #
def test_psi_is_near_zero_for_the_same_distribution() -> None:
    rng = np.random.default_rng(0)
    result = population_stability_index(rng.normal(0, 1, 5000), rng.normal(0, 1, 5000))
    assert result.psi < 0.1
    assert result.band == "none"
    assert result.flagged is False


def test_psi_flags_a_shifted_distribution() -> None:
    rng = np.random.default_rng(0)
    result = population_stability_index(rng.normal(0, 1, 5000), rng.normal(2, 1, 5000))
    assert result.psi >= 0.2
    assert result.band == "significant"
    assert result.flagged is True


def test_psi_grows_monotonically_with_the_shift() -> None:
    rng = np.random.default_rng(1)
    ref = rng.normal(0, 1, 5000)
    psis = [population_stability_index(ref, rng.normal(mu, 1, 5000)).psi for mu in (0.0, 0.5, 1.0, 2.0)]
    assert psis[0] < psis[1] < psis[2] < psis[3]


def test_psi_rejects_empty_and_constant_reference() -> None:
    with pytest.raises(ValueError):
        population_stability_index(np.array([]), np.array([1.0, 2.0]))
    with pytest.raises(ValueError):
        population_stability_index(np.ones(100), np.arange(100.0))  # constant ref -> edges collapse


# --------------------------------------------------------------------------- #
# KS (SYNTHETIC)
# --------------------------------------------------------------------------- #
def test_ks_passes_an_unshifted_distribution() -> None:
    # two independent N(0,1) draws -> same distribution, KS should not flag
    result = ks_two_sample(
        np.random.default_rng(0).normal(0, 1, 2000),
        np.random.default_rng(1000).normal(0, 1, 2000),
    )
    assert result.flagged is False
    assert result.p_value > 0.05
    assert 0.0 <= result.statistic <= 1.0


def test_ks_p_value_is_calibrated_under_the_null() -> None:
    """The real guarantee behind 'passes an unshifted distribution': under the
    null the flag rate is ~alpha and the p-value is ~uniform (mean ~0.5). A
    single unlucky draw flagging is expected of a calibrated test, not a bug."""
    results = [
        ks_two_sample(
            np.random.default_rng(s).normal(0, 1, 2000),
            np.random.default_rng(1000 + s).normal(0, 1, 2000),
        )
        for s in range(200)
    ]
    flag_rate = sum(r.flagged for r in results) / len(results)
    assert flag_rate <= 0.12  # ~alpha=0.05, comfortably not a broken always-flag
    assert 0.4 <= float(np.mean([r.p_value for r in results])) <= 0.6


def test_ks_flags_a_shifted_distribution() -> None:
    rng = np.random.default_rng(0)
    result = ks_two_sample(rng.normal(0, 1, 3000), rng.normal(1, 1, 3000))
    assert result.flagged is True
    assert result.p_value < 0.05
    assert result.statistic > 0.0


def test_ks_statistic_is_one_for_disjoint_supports() -> None:
    result = ks_two_sample(np.zeros(50), np.ones(50))
    assert result.statistic == pytest.approx(1.0)
    assert result.flagged is True


def test_ks_rejects_empty_samples() -> None:
    with pytest.raises(ValueError):
        ks_two_sample(np.array([]), np.array([1.0]))


# --------------------------------------------------------------------------- #
# CUSUM change-point (SYNTHETIC)
# --------------------------------------------------------------------------- #
def test_stationary_stream_reports_no_change_point() -> None:
    """A batch of stationary N(0,1) streams stays quiet under the default
    threshold (long in-control ARL). A handful of false alarms is expected of
    any CUSUM, so the assertion is a low rate, not an impossible zero."""
    detections = 0
    for seed in range(50):
        stream = np.random.default_rng(seed).normal(0.0, 1.0, 400)
        detections += cusum_change_point(stream, ref_size=100).detected
    assert detections <= 2  # <= 4% false-alarm rate over the batch
    # and a specific representative stationary stream is flat-out quiet
    assert not cusum_change_point(np.random.default_rng(0).normal(0, 1, 400), ref_size=100).detected


def test_injected_upward_mean_shift_is_detected_with_direction() -> None:
    rng = np.random.default_rng(0)
    stream = np.concatenate([rng.normal(0, 1, 150), rng.normal(3, 1, 150)])
    result = cusum_change_point(stream, ref_size=80)
    assert result.detected is True
    assert result.direction == "up"
    assert result.index >= 150  # only after the shift point
    assert result.index <= 160  # and promptly


def test_injected_downward_mean_shift_is_detected_with_direction() -> None:
    rng = np.random.default_rng(0)
    stream = np.concatenate([rng.normal(0, 1, 150), rng.normal(-3, 1, 150)])
    result = cusum_change_point(stream, ref_size=80)
    assert result.detected is True
    assert result.direction == "down"
    assert result.index >= 150


def test_cusum_validates_ref_size() -> None:
    stream = np.zeros(10)
    with pytest.raises(ValueError):
        cusum_change_point(stream, ref_size=1)          # too small
    with pytest.raises(ValueError):
        cusum_change_point(stream, ref_size=10)         # leaves nothing to monitor


def test_cusum_rejects_a_constant_reference_window() -> None:
    stream = np.concatenate([np.ones(50), np.arange(50.0)])
    with pytest.raises(ValueError):
        cusum_change_point(stream, ref_size=40)  # zero-variance reference


# --------------------------------------------------------------------------- #
# REAL DATA: NYC Access-A-Ride daily scheduled trips, 2020 COVID collapse
# --------------------------------------------------------------------------- #
def _load_aar_series() -> "tuple[np.ndarray, list[date]]":
    import pandas as pd

    df = pd.read_csv(_AAR_DAILY, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    return df["scheduled_trips"].to_numpy(dtype=float), [d.date() for d in df["date"]]


@pytest.mark.skipif(not _AAR_DAILY.exists(), reason="real AAR daily panel absent")
def test_real_aar_covid_collapse_is_detected_as_a_downward_change_point() -> None:
    """REAL DATA: standardizing by the pre-collapse baseline (first ~2 weeks of
    March 2020), CUSUM flags the mid-March demand collapse as a downward shift."""
    values, dates = _load_aar_series()
    result = cusum_change_point(values, ref_size=12)
    assert result.detected is True
    assert result.direction == "down"
    assert dates[result.index].year == 2020 and dates[result.index].month == 3


@pytest.mark.skipif(not _AAR_DAILY.exists(), reason="real AAR daily panel absent")
def test_real_aar_pre_vs_crash_distributions_flag_on_psi_and_ks() -> None:
    """REAL DATA: the pre-collapse fortnight vs the April-2020 trough are plainly
    different distributions -- both PSI and KS flag."""
    values, dates = _load_aar_series()
    pre = np.array([v for v, d in zip(values, dates) if d < date(2020, 3, 16)])
    trough = np.array(
        [v for v, d in zip(values, dates) if date(2020, 3, 20) <= d < date(2020, 5, 1)]
    )
    assert population_stability_index(pre, trough, bins=5).flagged is True
    assert ks_two_sample(pre, trough).flagged is True


@pytest.mark.skipif(not _AAR_DAILY.exists(), reason="real AAR daily panel absent")
def test_real_aar_stable_period_random_split_does_not_flag() -> None:
    """REAL DATA control: a random (exchangeable) split of a single stable year
    (2023) is NOT drift -- PSI stays low and KS passes. This proves the flags
    above are a real distribution change, not an artefact of the test."""
    values, dates = _load_aar_series()
    y2023 = np.array([v for v, d in zip(values, dates) if d.year == 2023])
    idx = np.random.default_rng(0).permutation(len(y2023))
    half = len(idx) // 2
    a, b = y2023[idx[:half]], y2023[idx[half:]]
    assert population_stability_index(a, b).flagged is False
    assert ks_two_sample(a, b).flagged is False
