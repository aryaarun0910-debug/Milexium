"""Serve-time drift monitoring for the forecast runtime (Program E).

ADR-0034 built a drift / change-point service (`packages.core.drift`: PSI,
two-sample KS, two-sided CUSUM). ADR-0030 built serve-time split-conformal
intervals (`packages.forecast.conformal`). Until this module they had never
been connected, which left the worst failure mode this system can have
available: a model whose serving inputs have wandered arbitrarily far from its
training distribution keeps returning a confident point estimate wrapped in an
interval that *looks* calibrated. Silently wrong, with a number that says it is
fine.

This module closes that gap. It compares the incoming feature distribution
against the model's TRAINING distribution reference and returns a
`DriftVerdict` that is ATTACHED to the served forecast (`MonitoredForecast`),
not written to a log nobody reads.

Three deliberate boundaries:

1. DETECTION IS IMPORTED, NOT REIMPLEMENTED. Every statistic here comes from
   `packages.core.drift`, used read-only. Program D owns the tests; Program E
   owns only the serve-time wiring, the reference's provenance, and the
   honesty caveat. There is no second PSI implementation to drift out of sync
   with the first.

2. REPORT, DO NOT DECIDE. A drifted forecast is still returned, unchanged and
   unsuppressed. ADR-0034 kept detection separate from action precisely so a
   monitor cannot silently change what serves; deciding to retrain, roll a
   champion back, or refuse to serve belongs to the promotion controller
   (`packages.core.promotion`) and the operator. A monitor that quietly
   substitutes its own judgement is worse than one that warns, because the
   caller can no longer tell what the model actually said.

3. THE INTERVAL CAVEAT IS THE POINT. A split-conformal interval is
   distribution-free ONLY under EXCHANGEABILITY of the calibration and serving
   data. Detected input drift is direct evidence against that assumption --
   the very premise the interval rests on. So a drifted `MonitoredForecast`
   carries an explicit, machine-readable statement that its interval's
   coverage guarantee is NOT supported, rather than presenting the interval
   unqualified. This repo already has empirical proof the concern is real and
   not theoretical: the committed intervals OVERCOVER (AAR 98.1% against a 90%
   target) and refitting conformal on a random exchangeable split of the same
   window recovers ~90% -- isolating a winter->spring distribution shift as the
   cause (ADR-0030, docs/RND_QUESTIONS.md Q4).

WHERE THE REFERENCE COMES FROM. `ModelVersion`
(`packages/canonical/entities.py`) carries `training_data_manifest_hash`,
`feature_schema_version` and an evaluation window -- but NO feature reference
distribution. So the artifact cannot supply one today; that is stated in code
by `reference_from_model_artifact`, which returns `None` with a reason rather
than inventing a plausible-looking baseline. References are therefore DERIVED
from the committed panel over the model's training window, and every
`DriftReference` carries a `ReferenceProvenance` recording the source kind, the
panel path and its SHA-256, the window, the row counts, the subsample seed and
the derivation recipe -- so a verdict is traceable to the data it was computed
against, not merely asserted.

Status: Demonstrated (real committed AAR panel + booster, and seeded synthetic
cases, both labelled). Never operator-Validated.

numpy is imported lazily inside the functions that need it, mirroring
runtime.py's lazy xgboost/pandas imports, so importing this module for its
value objects stays cheap.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.canonical.entities import ForecastVintage, ModelVersion
from packages.core.drift import (  # READ-ONLY: Program D owns these (ADR-0034)
    PSI_SIGNIFICANT,
    ks_two_sample,
    population_stability_index,
)

# A PSI/KS computed on a handful of rows is noise, not a measurement. Below
# this many usable rows the monitor says "insufficient_data" -- it never
# reports a confident no-drift verdict it cannot support. 30 is the smallest
# sample at which `population_stability_index`'s 10 quantile bins hold ~3 rows
# each; anything thinner and a single row moves a bin proportion by >30%.
MIN_ROWS_FOR_STABLE_STATISTIC = 30

# Cap on how many reference values a DriftReference stores per feature. A
# reference is a serialisable value object that travels with a served model,
# not a copy of the training set; 5000 draws pin the empirical CDF tightly
# enough for KS/PSI while keeping the object small. Subsampling is seeded, and
# the seed is recorded in the provenance, so a reference is reproducible.
DEFAULT_MAX_REFERENCE_SAMPLE = 5000

# Family-wise alpha for the KS corroboration across features. Monitoring ~15
# features at alpha=0.05 each would flag a perfectly in-distribution serve
# about half the time; the per-feature alpha is therefore Bonferroni-corrected
# to `alpha / n_features`. PSI carries no such correction because it is an
# effect size with fixed interpretation bands, not a hypothesis test.
DEFAULT_KS_FAMILY_ALPHA = 0.05

ARTIFACT_CARRIES_NO_REFERENCE_REASON = (
    "ModelVersion (packages/canonical/entities.py) records "
    "training_data_manifest_hash, feature_schema_version and an evaluation "
    "window, but no per-feature training reference distribution. A serve-time "
    "drift reference therefore CANNOT be read out of the registered artifact "
    "today and must be derived from the committed panel over the model's "
    "training window, with the derivation recorded in ReferenceProvenance."
)

DriftStatus = Literal["no_drift", "drift", "insufficient_data"]
IntervalGuarantee = Literal["unqualified", "unsupported", "not_assessed"]


def sha256_of_file(path: Path | str) -> str:
    """SHA-256 of a file's bytes -- what makes a reference's cited panel
    traceable rather than merely named."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# Provenance and reference
# --------------------------------------------------------------------------- #
class ReferenceProvenance(BaseModel):
    """Where a drift reference came from, in enough detail to re-derive it.

    A drift verdict is only as trustworthy as the baseline it was measured
    against. An unattributed reference is indistinguishable from an invented
    one, so this object is mandatory on every `DriftReference` and is carried
    through onto the verdict.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_kind: Literal["model_artifact", "committed_panel", "synthetic"] = Field(
        description="What class of source the reference distribution was read from."
    )
    description: str = Field(description="Human-readable identification of the source.")
    derivation: str = Field(
        description="How the reference rows were produced from that source "
        "(feature recipe, window filter, subsampling) -- the recorded derivation."
    )
    panel_path: str | None = Field(
        default=None, description="Repo-relative path of the committed panel, when there is one."
    )
    panel_sha256: str | None = Field(
        default=None, description="SHA-256 of the panel file's bytes, so the source is pinned."
    )
    model_version_id: str | None = Field(
        default=None, description="Model whose training window the reference represents."
    )
    training_window_start: datetime | None = None
    training_window_end: datetime | None = None
    n_source_rows: int = Field(ge=0, description="Rows in the source window before subsampling.")
    n_reference_rows: int = Field(ge=0, description="Rows actually retained per feature.")
    sample_seed: int | None = Field(
        default=None, description="Seed used to subsample; None when no subsampling occurred."
    )
    skipped_features: tuple[tuple[str, str], ...] = Field(
        default=(),
        description="(feature, reason) pairs for schema features the reference could NOT cover -- "
        "stated, not silently dropped.",
    )

    @property
    def is_traceable(self) -> bool:
        """True when the verdict can be traced to a concrete, pinned source: a
        committed panel identified by content hash, or a named model artifact.
        Synthetic references are deliberately NOT traceable -- they are for
        tests, and a caller can tell them apart."""
        if self.source_kind == "committed_panel":
            return bool(self.panel_path and self.panel_sha256)
        if self.source_kind == "model_artifact":
            return bool(self.model_version_id)
        return False

    def trace(self) -> str:
        """One-line citation of the reference's origin."""
        parts = [f"{self.source_kind}: {self.description}"]
        if self.panel_path:
            parts.append(f"panel={self.panel_path}")
        if self.panel_sha256:
            parts.append(f"sha256={self.panel_sha256[:16]}...")
        if self.training_window_start and self.training_window_end:
            parts.append(
                f"window={self.training_window_start.date()}..{self.training_window_end.date()}"
            )
        parts.append(f"rows={self.n_reference_rows}/{self.n_source_rows}")
        return " | ".join(parts)


class DriftReference(BaseModel):
    """Per-feature reference samples plus the provenance that justifies them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    samples: dict[str, tuple[float, ...]] = Field(
        description="Feature name -> finite reference values drawn from the training window."
    )
    provenance: ReferenceProvenance

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(self.samples)

    @property
    def n_rows(self) -> int:
        """Smallest per-feature reference size -- the binding constraint on
        whether a stable statistic can be computed at all."""
        return min((len(v) for v in self.samples.values()), default=0)


def reference_from_model_artifact(model_version: ModelVersion) -> DriftReference | None:
    """Attempt to read a drift reference out of the registered model artifact.

    Always returns `None` today, and that is the honest answer rather than a
    missing feature: `ModelVersion` carries no reference distribution (see
    `ARTIFACT_CARRIES_NO_REFERENCE_REASON`). This function exists so the gap is
    executable and testable instead of a comment -- a caller asks the artifact
    first, is told "no", and falls back to deriving from the committed panel
    with the derivation recorded. When a future `ModelVersion` does carry one,
    this is the single place that changes.
    """
    _ = model_version
    return None


def _finite_column(values):
    """Coerce a column to a 1-D float array of finite values. Raises
    TypeError/ValueError for a non-numeric (categorical) column -- the caller
    turns that into a recorded skip rather than a coerced-to-nonsense statistic."""
    import numpy as np

    array = np.asarray(values, dtype=float).ravel()
    return array[np.isfinite(array)]


def derive_reference_from_frame(
    frame,
    feature_names: Sequence[str],
    *,
    source_kind: Literal["model_artifact", "committed_panel", "synthetic"],
    description: str,
    derivation: str,
    panel_path: Path | str | None = None,
    model_version: ModelVersion | None = None,
    training_window_start: datetime | None = None,
    training_window_end: datetime | None = None,
    max_sample: int | None = DEFAULT_MAX_REFERENCE_SAMPLE,
    seed: int = 0,
) -> DriftReference:
    """Build a reference from a column-addressable table (a pandas DataFrame,
    or any mapping of feature name -> array-like) already restricted to the
    model's training window.

    Only numerically-coercible features are covered. A categorical feature (the
    trailing zone column of every zone-hour schema: borough / area / route /
    station_id) is SKIPPED and recorded in `provenance.skipped_features` with a
    reason -- PSI and KS are continuous-distribution tests, and silently
    coercing category codes to floats would produce a meaningless statistic
    that looks like a measurement. Categorical drift needs a chi-square-style
    test that Program D has not built; this monitor does not pretend otherwise.

    `panel_path`, when given, is hashed so the resulting verdict cites a pinned
    file rather than a filename.
    """
    import numpy as np

    samples: dict[str, tuple[float, ...]] = {}
    skipped: list[tuple[str, str]] = []
    n_source_rows = 0
    for name in feature_names:
        try:
            column = frame[name]
        except (KeyError, TypeError, IndexError):
            skipped.append((name, "absent from the reference source"))
            continue
        try:
            cleaned = _finite_column(column)
        except (TypeError, ValueError):
            skipped.append(
                (
                    name,
                    "non-numeric (categorical); PSI/KS are continuous tests and no "
                    "categorical drift test is built (v0.1)",
                )
            )
            continue
        if cleaned.size == 0:
            skipped.append((name, "no finite values in the reference window"))
            continue
        n_source_rows = max(n_source_rows, int(cleaned.size))
        if max_sample is not None and cleaned.size > max_sample:
            rng = np.random.default_rng(seed)
            cleaned = cleaned[np.sort(rng.choice(cleaned.size, max_sample, replace=False))]
        samples[name] = tuple(float(v) for v in cleaned)

    if not samples:
        raise ValueError(
            "no numeric feature could be covered -- refusing to build an empty drift reference"
        )

    resolved_path = Path(panel_path) if panel_path is not None else None
    provenance = ReferenceProvenance(
        source_kind=source_kind,
        description=description,
        derivation=derivation,
        panel_path=str(resolved_path).replace("\\", "/") if resolved_path else None,
        panel_sha256=sha256_of_file(resolved_path) if resolved_path else None,
        model_version_id=str(model_version.model_version_id) if model_version else None,
        training_window_start=training_window_start,
        training_window_end=training_window_end,
        n_source_rows=n_source_rows,
        n_reference_rows=min(len(v) for v in samples.values()),
        sample_seed=seed if max_sample is not None and n_source_rows > max_sample else None,
        skipped_features=tuple(skipped),
    )
    return DriftReference(samples=samples, provenance=provenance)


def derive_reference_from_rows(
    rows: Iterable[Mapping[str, object]],
    feature_names: Sequence[str],
    **kwargs,
) -> DriftReference:
    """Same as `derive_reference_from_frame` for an iterable of feature-row
    dicts -- the shape the runtime itself serves on."""
    materialised = list(rows)
    columns = {
        name: [row[name] for row in materialised if name in row] for name in feature_names
    }
    return derive_reference_from_frame(columns, feature_names, **kwargs)


# --------------------------------------------------------------------------- #
# Verdict
# --------------------------------------------------------------------------- #
class FeatureDriftResult(BaseModel):
    """Per-feature outcome of the two distribution tests."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    feature: str
    computable: bool = Field(
        description="False when the statistic could not be computed (constant reference, "
        "feature absent from the serving window, no finite values)."
    )
    note: str | None = Field(default=None, description="Why it was not computable.")
    psi: float | None = None
    psi_band: Literal["none", "moderate", "significant"] | None = None
    ks_statistic: float | None = None
    ks_p_value: float | None = None
    flagged: bool = Field(
        default=False,
        description="Drift on this feature: PSI at/above the significant band, or a "
        "multiplicity-corrected KS rejection.",
    )


class DriftVerdict(BaseModel):
    """The serve-time drift assessment, and what it implies for the interval.

    `status` is deliberately three-valued. `insufficient_data` is NOT folded
    into `no_drift`: "we could not tell" and "we checked and it is fine" are
    different claims, and collapsing them is exactly how a monitor ends up
    reassuring a caller about a serve it never examined.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: DriftStatus
    reason: str = Field(description="Plain statement of what was measured and concluded.")
    features: tuple[FeatureDriftResult, ...] = ()
    drifted_features: tuple[str, ...] = ()
    n_serving_rows: int = Field(ge=0)
    n_reference_rows: int = Field(ge=0)
    min_rows_required: int = Field(ge=1)
    psi_threshold: float
    ks_alpha_per_feature: float | None = Field(
        default=None, description="Bonferroni-corrected per-feature alpha actually applied."
    )
    provenance: ReferenceProvenance
    interval_guarantee: IntervalGuarantee = Field(
        description="'unqualified' only when drift was tested for and not found."
    )
    interval_caveat: str | None = Field(
        default=None,
        description="Explicit statement that the conformal coverage guarantee is not "
        "supported (or not assessed). None ONLY when the interval is unqualified.",
    )

    @property
    def interval_guarantee_supported(self) -> bool:
        """True only for `unqualified`. An untested interval is not a supported
        one -- `insufficient_data` returns False, not True."""
        return self.interval_guarantee == "unqualified"

    @property
    def is_traceable(self) -> bool:
        return self.provenance.is_traceable

    def trace(self) -> str:
        return self.provenance.trace()


_DRIFT_CAVEAT = (
    "INTERVAL COVERAGE GUARANTEE NOT SUPPORTED. Input drift was detected on "
    "{n} of {total} monitored feature(s) ({names}). A split-conformal interval "
    "is distribution-free only under EXCHANGEABILITY of the calibration and "
    "serving data; detected input drift is direct evidence against that "
    "assumption, which is the premise the interval rests on. The interval is "
    "reported UNCHANGED and the forecast is NOT suppressed -- treat the bounds "
    "as an uncalibrated width, not as a {coverage} coverage claim. Deciding "
    "what to do (retrain, roll back, refuse) belongs to the promotion "
    "controller and the operator, not to this monitor."
)

_NOT_ASSESSED_CAVEAT = (
    "INTERVAL COVERAGE GUARANTEE NOT ASSESSED. {reason} No drift verdict was "
    "reached, so the conformal interval's exchangeability assumption is "
    "UNTESTED here. Absence of a drift flag in this verdict is not evidence of "
    "no drift."
)


def _insufficient(
    reference: DriftReference,
    *,
    reason: str,
    n_serving_rows: int,
    min_rows: int,
    psi_threshold: float,
    features: tuple[FeatureDriftResult, ...] = (),
) -> DriftVerdict:
    return DriftVerdict(
        status="insufficient_data",
        reason=reason,
        features=features,
        drifted_features=(),
        n_serving_rows=n_serving_rows,
        n_reference_rows=reference.n_rows,
        min_rows_required=min_rows,
        psi_threshold=psi_threshold,
        ks_alpha_per_feature=None,
        provenance=reference.provenance,
        interval_guarantee="not_assessed",
        interval_caveat=_NOT_ASSESSED_CAVEAT.format(reason=reason),
    )


def assess_drift(
    reference: DriftReference,
    serving_rows: Iterable[Mapping[str, object]],
    *,
    psi_threshold: float = PSI_SIGNIFICANT,
    psi_bins: int = 10,
    ks_family_alpha: float = DEFAULT_KS_FAMILY_ALPHA,
    min_rows: int = MIN_ROWS_FOR_STABLE_STATISTIC,
    target_coverage: float | None = None,
) -> DriftVerdict:
    """Compare a serving window's feature distribution against the reference.

    Runs `packages.core.drift.population_stability_index` and `ks_two_sample`
    per feature, read-only. A feature is flagged when its PSI reaches the
    significant band (>= 0.2, Program D's own constant) OR when KS rejects at
    the Bonferroni-corrected per-feature alpha. PSI is the primary signal
    because it is an effect size with fixed bands; KS is corroboration and is
    corrected for multiplicity, without which monitoring 15 features at
    alpha=0.05 would flag a perfectly in-distribution serve about half the time.

    Never raises on a thin or awkward serving window: too few rows, an absent
    feature, or a constant reference produce an `insufficient_data` /
    `not computable` report, never a confident `no_drift`.
    """
    import numpy as np

    rows = list(serving_rows)
    n_serving = len(rows)
    if n_serving < min_rows:
        return _insufficient(
            reference,
            reason=(
                f"serving window has {n_serving} row(s); at least {min_rows} are needed "
                f"for a stable PSI/KS estimate."
            ),
            n_serving_rows=n_serving,
            min_rows=min_rows,
            psi_threshold=psi_threshold,
        )
    if reference.n_rows < min_rows:
        return _insufficient(
            reference,
            reason=(
                f"drift reference holds only {reference.n_rows} row(s) for its thinnest "
                f"feature; at least {min_rows} are needed."
            ),
            n_serving_rows=n_serving,
            min_rows=min_rows,
            psi_threshold=psi_threshold,
        )

    serving: dict[str, "np.ndarray"] = {}
    pending: list[FeatureDriftResult] = []
    for name in reference.feature_names:
        present = [row[name] for row in rows if name in row]
        if len(present) < min_rows:
            pending.append(
                FeatureDriftResult(
                    feature=name,
                    computable=False,
                    note=f"only {len(present)} serving row(s) carry this feature",
                )
            )
            continue
        try:
            column = _finite_column(present)
        except (TypeError, ValueError):
            pending.append(
                FeatureDriftResult(
                    feature=name,
                    computable=False,
                    note="serving values are non-numeric; no categorical drift test is built (v0.1)",
                )
            )
            continue
        if column.size < min_rows:
            pending.append(
                FeatureDriftResult(
                    feature=name,
                    computable=False,
                    note=f"only {int(column.size)} finite serving value(s)",
                )
            )
            continue
        serving[name] = column

    if not serving:
        return _insufficient(
            reference,
            reason=(
                "no monitored feature had enough usable serving values to compute a statistic."
            ),
            n_serving_rows=n_serving,
            min_rows=min_rows,
            psi_threshold=psi_threshold,
            features=tuple(pending),
        )

    alpha_per_feature = ks_family_alpha / len(serving)
    results: list[FeatureDriftResult] = list(pending)
    for name, column in serving.items():
        ref = np.asarray(reference.samples[name], dtype=float)
        psi_value: float | None = None
        psi_band = None
        note: str | None = None
        try:
            psi_result = population_stability_index(
                ref, column, bins=psi_bins, threshold=psi_threshold
            )
            psi_value, psi_band = psi_result.psi, psi_result.band
        except ValueError as exc:
            note = f"PSI not computable: {exc}"
        ks_result = ks_two_sample(ref, column, alpha=alpha_per_feature)
        flagged = bool(ks_result.flagged) or (
            psi_value is not None and psi_value >= psi_threshold
        )
        results.append(
            FeatureDriftResult(
                feature=name,
                computable=True,
                note=note,
                psi=psi_value,
                psi_band=psi_band,
                ks_statistic=ks_result.statistic,
                ks_p_value=ks_result.p_value,
                flagged=flagged,
            )
        )

    drifted = tuple(r.feature for r in results if r.flagged)
    coverage_label = f"{target_coverage:.0%}" if target_coverage is not None else "nominal"
    if drifted:
        status: DriftStatus = "drift"
        guarantee: IntervalGuarantee = "unsupported"
        caveat = _DRIFT_CAVEAT.format(
            n=len(drifted),
            total=len(serving),
            names=", ".join(drifted),
            coverage=coverage_label,
        )
        reason = (
            f"{len(drifted)} of {len(serving)} monitored feature(s) drifted "
            f"(PSI >= {psi_threshold} or KS p < {alpha_per_feature:.2}): {', '.join(drifted)}."
        )
    else:
        status = "no_drift"
        guarantee = "unqualified"
        caveat = None
        reason = (
            f"no monitored feature drifted across {len(serving)} feature(s) on "
            f"{n_serving} serving row(s) (PSI < {psi_threshold}, KS p >= "
            f"{alpha_per_feature:.2}). A passing test is not proof of "
            f"exchangeability, only an absence of evidence against it."
        )

    return DriftVerdict(
        status=status,
        reason=reason,
        features=tuple(results),
        drifted_features=drifted,
        n_serving_rows=n_serving,
        n_reference_rows=reference.n_rows,
        min_rows_required=min_rows,
        psi_threshold=psi_threshold,
        ks_alpha_per_feature=alpha_per_feature,
        provenance=reference.provenance,
        interval_guarantee=guarantee,
        interval_caveat=caveat,
    )


# --------------------------------------------------------------------------- #
# The served object
# --------------------------------------------------------------------------- #
class MonitoredForecast(BaseModel):
    """A `ForecastVintage` with its drift verdict ATTACHED.

    This is the whole point of the packet: a caller receives the point
    estimate, the interval, and "this forecast was produced under significant
    input drift, so the interval's coverage guarantee is not supported" in ONE
    object. There is no code path that hands out the number while leaving the
    verdict in a log.

    The vintage is byte-for-byte the vintage `ForecastRuntime.forecast` would
    have produced: no bound is widened, no estimate is suppressed, nothing is
    blocked. The monitor annotates; it does not decide.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    vintage: ForecastVintage
    drift: DriftVerdict

    @property
    def point_estimate(self) -> float:
        return self.vintage.point_estimate

    @property
    def interval(self) -> tuple[float, float] | None:
        if self.vintage.interval_low is None or self.vintage.interval_high is None:
            return None
        return (self.vintage.interval_low, self.vintage.interval_high)

    @property
    def drift_status(self) -> DriftStatus:
        return self.drift.status

    @property
    def interval_guarantee(self) -> IntervalGuarantee:
        return self.drift.interval_guarantee

    @property
    def interval_guarantee_supported(self) -> bool:
        return self.drift.interval_guarantee_supported

    @property
    def interval_caveat(self) -> str | None:
        """The honesty surface: `None` only when drift was tested for and not
        found. Any caller rendering the interval should render this next to
        it."""
        return self.drift.interval_caveat

    def summary(self) -> str:
        """One-line rendering suitable for a log line or an operator surface --
        the point estimate and the caveat, never one without the other."""
        bounds = self.interval
        span = f" [{bounds[0]:.3f}, {bounds[1]:.3f}]" if bounds else ""
        head = f"point={self.point_estimate:.3f}{span} drift={self.drift.status}"
        if self.interval_caveat is None:
            return f"{head} interval=unqualified | reference {self.drift.trace()}"
        return f"{head} | {self.interval_caveat} | reference {self.drift.trace()}"
