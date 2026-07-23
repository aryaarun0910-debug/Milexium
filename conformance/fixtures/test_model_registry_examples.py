"""Fixture-level conformance: the real `ModelVersion`s docs/MODEL_CARDS.md
documents (via conformance/fixtures/model_registry_builders.py) validate
against the independent schema verifier, and register into a real
`ModelRegistry` with the product-target model (AAR) as champion.
"""

from __future__ import annotations

from packages.canonical import ModelVersion
from packages.core.model_registry import ModelRegistry
from packages.verify import verify_against_schema

from conformance.fixtures.model_registry_builders import build_real_model_versions


def test_every_real_model_version_matches_its_own_schema() -> None:
    for name, model_version in build_real_model_versions().items():
        errors = verify_against_schema(model_version.model_dump(mode="json"), ModelVersion)
        assert errors == [], f"{name}: {errors}"


def test_all_five_real_model_versions_register_under_forecast_demand() -> None:
    registry = ModelRegistry()
    versions = build_real_model_versions()
    for model_version in versions.values():
        registry.register(model_version)

    listed = registry.list_for_task("forecast.demand")
    assert len(listed) == 5
    assert {v.model_version_id for v in listed} == {
        v.model_version_id for v in versions.values()
    }


def test_aar_product_target_model_can_be_promoted_champion() -> None:
    """docs/MODEL_CARDS.md labels the AAR model "PRODUCT TARGET"; the other
    four are "generalization evidence (not the product target)" -- promoting
    AAR reflects that existing labeling, it is not invented here."""
    registry = ModelRegistry()
    versions = build_real_model_versions()
    for model_version in versions.values():
        registry.register(model_version)

    registry.promote(versions["aar"].model_version_id)
    assert registry.champion("forecast.demand") == versions["aar"]
