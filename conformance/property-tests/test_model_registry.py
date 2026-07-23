"""Conformance tests for the model registry (packages/core), Program D's
task/model registry first slice: register, look up, list by task, and
promote a champion pointer.
"""

from __future__ import annotations

import pytest

from packages.canonical import ModelVersion, ModelVersionId, TenantId, new_id
from packages.core.model_registry import (
    DuplicateModelVersionError,
    ModelRegistry,
    UnknownModelVersionError,
)
from packages.core.task_registry import UnknownTaskError

from conformance.fixtures.builders import utc


def _model_version(
    *, tenant_id: TenantId | None = None, task: str = "forecast.demand", **overrides
) -> ModelVersion:
    fields = dict(
        model_version_id=new_id(ModelVersionId),
        tenant_id=tenant_id or new_id(TenantId),
        task=task,
        training_data_manifest_hash="deadbeef" * 8,
        feature_schema_version="zone_hour_demand_v1",
        evaluation_window_start=utc(2026, 3, 2),
        evaluation_window_end=utc(2026, 5, 31),
        artifact_hash="cafebabe" * 8,
    )
    fields.update(overrides)
    return ModelVersion(**fields)


def test_register_then_get_returns_the_same_model_version() -> None:
    registry = ModelRegistry()
    model_version = _model_version()
    registry.register(model_version)
    assert registry.get(model_version.model_version_id) == model_version


def test_get_unknown_model_version_id_raises() -> None:
    registry = ModelRegistry()
    with pytest.raises(UnknownModelVersionError):
        registry.get(new_id(ModelVersionId))


def test_register_unknown_task_is_rejected() -> None:
    registry = ModelRegistry()
    with pytest.raises(UnknownTaskError):
        registry.register(_model_version(task="forecast.no_show"))


def test_register_same_model_version_id_twice_is_rejected() -> None:
    registry = ModelRegistry()
    model_version = _model_version()
    registry.register(model_version)
    with pytest.raises(DuplicateModelVersionError):
        registry.register(model_version)


def test_list_for_task_returns_only_that_tasks_versions() -> None:
    registry = ModelRegistry()
    demand_a = _model_version()
    demand_b = _model_version()
    registry.register(demand_a)
    registry.register(demand_b)
    listed = registry.list_for_task("forecast.demand")
    assert set(listed) == {demand_a, demand_b}


def test_list_for_task_unknown_task_raises() -> None:
    registry = ModelRegistry()
    with pytest.raises(UnknownTaskError):
        registry.list_for_task("forecast.no_show")


def test_champion_is_none_before_any_promotion() -> None:
    registry = ModelRegistry()
    assert registry.champion("forecast.demand") is None


def test_promote_sets_the_champion() -> None:
    registry = ModelRegistry()
    model_version = _model_version()
    registry.register(model_version)
    registry.promote(model_version.model_version_id)
    assert registry.champion("forecast.demand") == model_version


def test_promote_unregistered_model_version_raises() -> None:
    registry = ModelRegistry()
    with pytest.raises(UnknownModelVersionError):
        registry.promote(new_id(ModelVersionId))


def test_promoting_a_second_version_replaces_the_champion() -> None:
    """Registering two versions for the same task and promoting the second
    correctly updates which one is champion."""
    registry = ModelRegistry()
    first = _model_version()
    second = _model_version()
    registry.register(first)
    registry.register(second)

    registry.promote(first.model_version_id)
    assert registry.champion("forecast.demand") == first

    registry.promote(second.model_version_id)
    assert registry.champion("forecast.demand") == second
    assert registry.champion("forecast.demand") != first
