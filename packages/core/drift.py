"""Drift / change-point detection service (Program D, v0.1 slice).

`blueprint/05-core-model-runtime-and-forecast.md` lists calibration/drift
monitoring among Program D's adaptive-memory services; the model registry's
champion pointer is meant to move when a model drifts. This module is the
detection half, v0.1: pure numpy (no scipy / sklearn -- the p-value and the
change statistic are computed directly), with two families of test.

1. Distribution drift between a reference sample and a live sample:
   - `population_stability_index` (PSI): binned relative-entropy-style score,
     the standard industry rule of thumb (<0.1 no shift, 0.1-0.2 moderate,
     >=0.2 significant).
   - `ks_two_sample` (Kolmogorov-Smirnov): the max CDF gap plus an asymptotic
     p-value from the Kolmogorov distribution series (no scipy).

2. Change-point / mean-shift on a metric stream:
   - `cusum_change_point`: a two-sided tabular CUSUM standardized by a
     reference window, reporting the first index (and direction) where the
     accumulated deviation crosses the decision threshold, or none.

Detection only -- deciding what to DO about a flagged drift (retrain, roll a
champion back) is the promotion controller's / operator's job, kept separate so
a monitor cannot silently change what serves. Status: Demonstrated on
synthetic streams and on the real NYC Access-A-Ride daily panel (its 2020 COVID
collapse); never operator-Validated.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

# Industry-standard PSI interpretation bands.
PSI_MODERATE = 0.1
PSI_SIGNIFICANT = 0.2


class PSIResult(BaseModel):
    """Population Stability Index between a reference and a live sample."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    psi: float
    n_bins: int
    threshold: float
    flagged: bool = Field(description="True when psi >= threshold (drift).")
    band: Literal["none", "moderate", "significant"]


class KSResult(BaseModel):
    """Two-sample Kolmogorov-Smirnov drift test."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    statistic: float = Field(description="Max absolute gap between the two empirical CDFs, in [0, 1].")
    p_value: float
    alpha: float
    flagged: bool = Field(description="True when p_value < alpha (distributions differ).")
    n_reference: int
    n_actual: int


class ChangePointResult(BaseModel):
    """First mean-shift a two-sided CUSUM finds on a metric stream."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    detected: bool
    index: int | None = Field(description="Stream index of first detection; None if none.")
    direction: Literal["up", "down"] | None
    statistic: float = Field(description="CUSUM value at detection, or the running max if none.")
    ref_size: int
    slack_k: float
    threshold_h: float


# --------------------------------------------------------------------------- #
# Distribution drift
# --------------------------------------------------------------------------- #
def population_stability_index(
    reference: np.ndarray, actual: np.ndarray, *, bins: int = 10, threshold: float = PSI_SIGNIFICANT
) -> PSIResult:
    """PSI of `actual` against `reference`, using quantile bin edges derived
    from `reference`. Edges are deduplicated (a heavily tied reference yields
    fewer, still-valid bins) and the tails are opened to +/- inf so live values
    outside the reference range still land in a bin. A small epsilon floor on
    each bin proportion avoids log(0) / divide-by-zero."""
    ref = np.asarray(reference, dtype=float).ravel()
    act = np.asarray(actual, dtype=float).ravel()
    if ref.size == 0 or act.size == 0:
        raise ValueError("PSI needs non-empty reference and actual samples")

    quantiles = np.linspace(0.0, 1.0, bins + 1)
    edges = np.unique(np.quantile(ref, quantiles))
    if edges.size < 2:
        raise ValueError("reference sample is constant -- PSI bin edges collapse")
    edges[0], edges[-1] = -np.inf, np.inf

    ref_counts, _ = np.histogram(ref, bins=edges)
    act_counts, _ = np.histogram(act, bins=edges)
    eps = 1e-6
    ref_pct = np.clip(ref_counts / ref_counts.sum(), eps, None)
    act_pct = np.clip(act_counts / act_counts.sum(), eps, None)
    psi = float(np.sum((act_pct - ref_pct) * np.log(act_pct / ref_pct)))

    band: Literal["none", "moderate", "significant"]
    if psi >= PSI_SIGNIFICANT:
        band = "significant"
    elif psi >= PSI_MODERATE:
        band = "moderate"
    else:
        band = "none"
    return PSIResult(
        psi=psi,
        n_bins=int(edges.size - 1),
        threshold=float(threshold),
        flagged=psi >= threshold,
        band=band,
    )


def _kolmogorov_sf(t: float, terms: int = 100) -> float:
    """Survival function of the Kolmogorov distribution,
    Q(t) = 2 * sum_{j>=1} (-1)^{j-1} exp(-2 j^2 t^2), clamped to [0, 1].

    The standard asymptotic used for the two-sample KS p-value (Numerical
    Recipes). Pure numpy so the service adds no scipy dependency."""
    if t <= 0.0:
        return 1.0
    j = np.arange(1, terms + 1)
    series = np.sum(((-1.0) ** (j - 1)) * np.exp(-2.0 * (j**2) * (t**2)))
    return float(min(1.0, max(0.0, 2.0 * series)))


def ks_two_sample(reference: np.ndarray, actual: np.ndarray, *, alpha: float = 0.05) -> KSResult:
    """Two-sample KS test: the statistic is the maximum gap between the two
    empirical CDFs; the p-value is the asymptotic Kolmogorov survival function
    with the Stephens finite-sample correction. Flags drift when p < alpha."""
    ref = np.sort(np.asarray(reference, dtype=float).ravel())
    act = np.sort(np.asarray(actual, dtype=float).ravel())
    n1, n2 = ref.size, act.size
    if n1 == 0 or n2 == 0:
        raise ValueError("KS needs non-empty reference and actual samples")

    grid = np.concatenate([ref, act])
    cdf_ref = np.searchsorted(ref, grid, side="right") / n1
    cdf_act = np.searchsorted(act, grid, side="right") / n2
    statistic = float(np.max(np.abs(cdf_ref - cdf_act)))

    en = np.sqrt(n1 * n2 / (n1 + n2))
    p_value = _kolmogorov_sf((en + 0.12 + 0.11 / en) * statistic)
    return KSResult(
        statistic=statistic,
        p_value=p_value,
        alpha=float(alpha),
        flagged=p_value < alpha,
        n_reference=int(n1),
        n_actual=int(n2),
    )


# --------------------------------------------------------------------------- #
# Change-point / mean-shift
# --------------------------------------------------------------------------- #
def cusum_change_point(
    stream: np.ndarray,
    *,
    ref_size: int,
    slack_k: float = 0.5,
    threshold_h: float = 10.0,
) -> ChangePointResult:
    """Two-sided tabular CUSUM for a mean shift on a metric stream.

    The first `ref_size` points establish an in-control mean and std; the stream
    is standardized by them, then two one-sided cumulative sums accumulate
    excursions beyond a slack `slack_k` (in std units). The first index past the
    reference window where either sum exceeds `threshold_h` is the change point;
    its sign gives the direction. A stationary stream keeps both sums small and
    reports no change.

    `slack_k` (~half the shift you want to catch) and `threshold_h` (~decision
    sensitivity, larger = fewer false alarms) are the standard CUSUM knobs.
    """
    values = np.asarray(stream, dtype=float).ravel()
    if ref_size < 2 or ref_size >= values.size:
        raise ValueError("ref_size must be >= 2 and leave at least one point to monitor")

    mu = float(np.mean(values[:ref_size]))
    sigma = float(np.std(values[:ref_size]))
    if sigma == 0.0:
        raise ValueError("reference window has zero variance -- cannot standardize")

    s_hi = 0.0
    s_lo = 0.0
    running_max = 0.0
    for i in range(ref_size, values.size):
        z = (values[i] - mu) / sigma
        s_hi = max(0.0, s_hi + z - slack_k)
        s_lo = max(0.0, s_lo - z - slack_k)
        running_max = max(running_max, s_hi, s_lo)
        if s_hi > threshold_h or s_lo > threshold_h:
            direction: Literal["up", "down"] = "up" if s_hi > s_lo else "down"
            return ChangePointResult(
                detected=True,
                index=int(i),
                direction=direction,
                statistic=float(max(s_hi, s_lo)),
                ref_size=int(ref_size),
                slack_k=float(slack_k),
                threshold_h=float(threshold_h),
            )
    return ChangePointResult(
        detected=False,
        index=None,
        direction=None,
        statistic=float(running_max),
        ref_size=int(ref_size),
        slack_k=float(slack_k),
        threshold_h=float(threshold_h),
    )
