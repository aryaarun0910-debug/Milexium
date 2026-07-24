"""Serve-time conformal calibration for the forecast runtime.

The runtime's original interval was a caller-supplied `interval_half_width`: an
honest but *manual* number with no empirical backing. This module replaces that
guesswork with split-conformal calibration -- the same finite-sample-corrected
residual-quantile construction realdata/train_real_models.py already uses to
report each model's achieved coverage (its `conformal` function). A held-out
calibration set (never seen during fitting) yields a residual quantile at a
target coverage; the runtime adds that quantile symmetrically (or two-sided)
around a point estimate to produce a real prediction interval.

Consistency with the training pipeline is deliberate: the order-statistic index
here is `ceil((n+1) * coverage)`, exactly the `k = ceil((n+1)*(1-alpha))` the
repo's `conformal` uses with `alpha = 1 - coverage`, so a `ConformalCalibration`
fit here on a model's calibration residuals reproduces that model's committed
half-width. Where this module deliberately differs: it is *global*
(unconditioned), not the Mondrian hour-bucket variant, because the repo's own
finding (docs/RND_QUESTIONS.md Q4) is that hour-bucket conditioning gave no
improvement (97.8% vs 98.1% coverage) -- so the serve-time surface takes the
simpler distribution-free marginal calibration.

Honesty (blueprint 01 / architecture/decisions/0001): a conformal interval is
distribution-free ONLY under exchangeability of the calibration and serving
data. It is a *marginal* coverage property, NOT a probability statement about
any single forecast, and NOT a guarantee. The repo already measured
overcoverage on the untouched validation windows (AAR 98.1%, Chicago 92.6%,
MTA bus 92.0%, MTA subway 91.7% -- all above the 90% target), attributed to
distribution shift between the (partly-winter) calibration window and the
(spring) validation window. Serve-time calibration inherits exactly this
limitation: the intervals tend to be wider than the nominal level, not
narrower, and lose their guarantee the moment the serving distribution drifts
from the calibration window. This module records the residual quantile; it does
not upgrade its epistemic status.

numpy is imported lazily inside the fitting functions so importing this module
(e.g. for the `ConformalCalibration` value object, whose `apply` is pure Python)
does not require numpy -- mirroring runtime.py's lazy xgboost/pandas imports.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConformalCalibration(BaseModel):
    """A fitted split-conformal calibration: signed offsets to add to a point
    estimate to obtain a prediction interval at `target_coverage`.

    Frozen value object. `lower_offset`/`upper_offset` are *additive* signed
    offsets (interval = [point + lower_offset, point + upper_offset]) rather
    than magnitudes, so the symmetric and two-sided cases share one apply path
    with no sign bookkeeping. A symmetric calibration has
    `lower_offset == -upper_offset`; a two-sided calibration allows asymmetric
    tails. `clip_nonnegative` mirrors the training pipeline's
    `np.clip(pred - width, 0, None)` -- demand counts cannot go negative.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_coverage: float = Field(
        gt=0.0, lt=1.0, description="Nominal coverage the calibration targets, e.g. 0.90."
    )
    lower_offset: float = Field(description="Signed offset added to the point for the low bound (usually <= 0).")
    upper_offset: float = Field(description="Signed offset added to the point for the high bound (usually >= 0).")
    n_calibration: int = Field(ge=1, description="Number of finite calibration residuals the fit used.")
    clip_nonnegative: bool = Field(
        default=True, description="Clip the low bound at 0 (demand is a non-negative count)."
    )

    @model_validator(mode="after")
    def _offsets_ordered(self) -> "ConformalCalibration":
        if self.upper_offset < self.lower_offset:
            raise ValueError(
                f"upper_offset ({self.upper_offset}) must be >= lower_offset ({self.lower_offset})"
            )
        return self

    @property
    def is_symmetric(self) -> bool:
        return math.isclose(self.lower_offset, -self.upper_offset, abs_tol=1e-9)

    @property
    def interval_width(self) -> float:
        """Nominal (pre-clip) interval width, `upper_offset - lower_offset`."""
        return self.upper_offset - self.lower_offset

    def apply(self, point_estimate: float) -> tuple[float, float]:
        """Return (low, high) for a point estimate. Low is clipped at 0 when
        `clip_nonnegative`, which can shrink the realized width below
        `interval_width` for small point estimates."""
        low = point_estimate + self.lower_offset
        high = point_estimate + self.upper_offset
        if self.clip_nonnegative:
            low = max(low, 0.0)
        return low, high


def _corrected_order_index(n: int, coverage: float) -> int:
    """1-indexed order statistic for split-conformal at `coverage`:
    `ceil((n+1) * coverage)`, capped into [1, n]. Identical to the
    `k = ceil((n+1)*(1-alpha))` finite-sample correction in
    realdata/train_real_models.py's `conformal` (with `alpha = 1 - coverage`).
    When the corrected index exceeds n (coverage so high the sample cannot
    support it), it caps at the largest residual -- the most conservative
    finite interval the data can express."""
    k = math.ceil((n + 1) * coverage)
    return min(max(k, 1), n)


def fit_symmetric_conformal(
    residuals: Iterable[float],
    *,
    target_coverage: float = 0.90,
    clip_nonnegative: bool = True,
) -> ConformalCalibration:
    """Symmetric split-conformal from signed residuals (y_true - y_pred).

    Uses the |residual| quantile (matching the training pipeline's
    `resid = np.abs(y_cal - pred_cal)`), producing offsets (-q, +q). This is
    the default and the one that reproduces the committed model-card coverage.
    """
    import numpy as np

    r = np.abs(np.asarray(list(residuals), dtype=float))
    r = r[np.isfinite(r)]
    n = int(r.size)
    if n == 0:
        raise ValueError("need at least one finite residual to calibrate")
    k = _corrected_order_index(n, target_coverage)
    q = float(np.sort(r)[k - 1])
    return ConformalCalibration(
        target_coverage=target_coverage,
        lower_offset=-q,
        upper_offset=q,
        n_calibration=n,
        clip_nonnegative=clip_nonnegative,
    )


def fit_two_sided_conformal(
    residuals: Iterable[float],
    *,
    target_coverage: float = 0.90,
    clip_nonnegative: bool = True,
) -> ConformalCalibration:
    """Two-sided split-conformal from signed residuals: independent lower- and
    upper-tail quantiles at alpha/2 each (alpha = 1 - target_coverage), so a
    skewed residual distribution gets an asymmetric interval instead of an
    inflated symmetric one. Falls back to the symmetric shape when residuals
    are themselves symmetric."""
    import numpy as np

    r = np.asarray(list(residuals), dtype=float)
    r = np.sort(r[np.isfinite(r)])
    n = int(r.size)
    if n == 0:
        raise ValueError("need at least one finite residual to calibrate")
    alpha = 1.0 - target_coverage
    k_hi = _corrected_order_index(n, 1.0 - alpha / 2.0)
    upper = float(r[k_hi - 1])
    # symmetric position from the bottom of the sorted signed residuals
    k_lo = min(max(int(math.floor((n + 1) * (alpha / 2.0))), 1), n)
    lower = float(r[k_lo - 1])
    if lower > upper:  # tiny/degenerate samples: fall back to symmetric magnitude
        return fit_symmetric_conformal(
            r, target_coverage=target_coverage, clip_nonnegative=clip_nonnegative
        )
    return ConformalCalibration(
        target_coverage=target_coverage,
        lower_offset=lower,
        upper_offset=upper,
        n_calibration=n,
        clip_nonnegative=clip_nonnegative,
    )


def fit_conformal_from_predictions(
    y_true: Iterable[float],
    y_pred: Iterable[float],
    *,
    target_coverage: float = 0.90,
    mode: str = "symmetric",
    clip_nonnegative: bool = True,
) -> ConformalCalibration:
    """Fit a calibration from a validation set's actuals and the model's
    predictions on that set (residual = y_true - y_pred). `mode` is
    "symmetric" (default) or "two_sided"."""
    import numpy as np

    yt = np.asarray(list(y_true), dtype=float)
    yp = np.asarray(list(y_pred), dtype=float)
    if yt.shape != yp.shape:
        raise ValueError(f"y_true and y_pred must have the same shape; got {yt.shape} and {yp.shape}")
    residuals = yt - yp
    if mode == "symmetric":
        return fit_symmetric_conformal(
            residuals, target_coverage=target_coverage, clip_nonnegative=clip_nonnegative
        )
    if mode == "two_sided":
        return fit_two_sided_conformal(
            residuals, target_coverage=target_coverage, clip_nonnegative=clip_nonnegative
        )
    raise ValueError(f"mode must be 'symmetric' or 'two_sided', got {mode!r}")


def empirical_coverage(
    calibration: ConformalCalibration,
    y_true: Iterable[float],
    y_pred: Iterable[float],
) -> float:
    """Fraction of a holdout whose actual falls inside the calibrated interval
    -- the honest, measured coverage (report this, not the nominal target).
    Applies the same non-negative clipping the calibration declares."""
    import numpy as np

    yt = np.asarray(list(y_true), dtype=float)
    yp = np.asarray(list(y_pred), dtype=float)
    if yt.shape != yp.shape:
        raise ValueError(f"y_true and y_pred must have the same shape; got {yt.shape} and {yp.shape}")
    lo = yp + calibration.lower_offset
    hi = yp + calibration.upper_offset
    if calibration.clip_nonnegative:
        lo = np.clip(lo, 0.0, None)
    return float(np.mean((yt >= lo) & (yt <= hi)))
