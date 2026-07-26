"""Acquisition manifest -- the contract every dataset must carry before a
single byte enters the estate (blueprint 17, "Acquisition manifest").

The manifest is the governance record: it is what makes an integrator (or a
future auditor, or a court) able to answer "where did this data come from,
what are we allowed to do with it, and is it what it claims to be." Manifests
are small JSON and ARE committed to git (unlike the raw bytes they describe);
they live under data/acquired/catalog/.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ManifestError(ValueError):
    """Raised when a manifest is missing required governance fields or malformed."""


class QualityTest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str


class AcquisitionManifest(BaseModel):
    """Mirrors blueprint 17's acquisition-manifest YAML exactly. Every field
    is required governance metadata except where the blueprint itself treats
    it as optional (derived artifacts, sensitive fields)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    owner_and_source: str
    license_and_commercial_rights: str = Field(
        description="Must state the actual license and whether commercial use is permitted. "
        "An empty or 'unknown' value is a governance failure, not a default."
    )
    decision_tasks_enabled: tuple[str, ...] = Field(min_length=1)
    geography: str
    time_coverage: str
    source_url: str
    expected_download_gb: float = Field(ge=0)
    expected_expanded_gb: float = Field(ge=0)
    expected_retained_gb: float = Field(ge=0)
    schema_and_format: str
    sensitive_fields: tuple[str, ...] = ()
    update_frequency: str
    source_checksum: str | None = Field(
        default=None,
        description="Expected sha256 of the downloaded object, if known ahead of time. "
        "None means 'record on first acquisition' (trust-on-first-use), which is "
        "acceptable for an openly published source but must be noted as such.",
    )
    canonical_contract: str = Field(
        description="Which canonical entity/adapter this data maps toward, or 'none-yet' "
        "if it is raw research data with no canonical mapping designed."
    )
    quality_tests: tuple[QualityTest, ...] = ()
    acceptance_threshold: str
    retention_and_deletion: str
    derived_artifacts: tuple[str, ...] = ()
    zone: str = Field(
        pattern=r"^(raw/public|raw/partner|standards|networks|benchmarks|simulation)$",
        description="Which estate zone the raw object lands in after validation.",
    )

    def rights_are_declared(self) -> bool:
        """A manifest whose rights field is empty or a placeholder is not
        acquirable -- the whole point is that nothing enters without stated
        rights."""
        v = self.license_and_commercial_rights.strip().lower()
        return bool(v) and v not in {"unknown", "tbd", "todo", "?"}


def load_manifest(path: str | Path) -> AcquisitionManifest:
    raw = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{path}: not valid JSON: {exc}") from exc
    try:
        manifest = AcquisitionManifest.model_validate(data)
    except Exception as exc:
        raise ManifestError(f"{path}: invalid acquisition manifest: {exc}") from exc
    if not manifest.rights_are_declared():
        raise ManifestError(
            f"{path}: license_and_commercial_rights is empty or a placeholder "
            f"({manifest.license_and_commercial_rights!r}); nothing enters the "
            "estate without declared rights (blueprint 17)"
        )
    return manifest
