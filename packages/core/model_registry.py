"""Model registry (Program D contract, v0.1 first slice).

Catalogs the `ModelVersion` canonical entities (`packages/canonical/entities.py`)
this repository already has real evaluation evidence for, and tracks a simple
"champion" pointer per task -- one model version, not a full champion/
challenger/canary lifecycle with shadow evaluation, drift detection, or
rollback (`blueprint/05-core-model-runtime-and-forecast.md`'s "Champion/
challenger" section describes that full lifecycle; it stays Specified).

In-memory reference implementation only, matching the pattern
`packages/canonical/events.py`'s `HashChainAppender` already established: a
single reference backend plus conformance tests, rather than a new SQL table
-- see `conformance/property-tests/test_model_registry.py`.
"""

from __future__ import annotations

from packages.canonical.entities import ModelVersion
from packages.canonical.ids import ModelVersionId
from packages.core.task_registry import get_task


class UnknownModelVersionError(ValueError):
    """Raised when a `model_version_id` has not been registered."""


class DuplicateModelVersionError(ValueError):
    """Raised when a `model_version_id` is registered a second time."""


class ModelRegistry:
    """In-memory reference `ModelVersion` catalog with per-task champion pointers."""

    def __init__(self) -> None:
        self._versions: dict[ModelVersionId, ModelVersion] = {}
        self._champions: dict[str, ModelVersionId] = {}

    def register(self, model_version: ModelVersion) -> None:
        """Add a model version. Rejects an unknown task (Program D's model
        resolution starts by filtering on task, per blueprint 05's "Model
        resolution" step 1 -- a version for a task this registry doesn't
        know about can never be resolved) and rejects re-registering an
        already-used `model_version_id`."""
        get_task(model_version.task)
        if model_version.model_version_id in self._versions:
            raise DuplicateModelVersionError(
                f"model_version_id {model_version.model_version_id!r} is already registered"
            )
        self._versions[model_version.model_version_id] = model_version

    def get(self, model_version_id: ModelVersionId) -> ModelVersion:
        try:
            return self._versions[model_version_id]
        except KeyError:
            raise UnknownModelVersionError(
                f"no registered model version {model_version_id!r}"
            ) from None

    def list_for_task(self, task: str) -> tuple[ModelVersion, ...]:
        """Every registered version for `task`, in registration order."""
        get_task(task)
        return tuple(v for v in self._versions.values() if v.task == task)

    def promote(self, model_version_id: ModelVersionId) -> None:
        """Mark the given, already-registered version as champion for its task.
        A simple pointer: promoting a new version for a task just overwrites
        the previous pointer, it does not check the new version is better."""
        model_version = self.get(model_version_id)
        self._champions[model_version.task] = model_version_id

    def champion(self, task: str) -> ModelVersion | None:
        """The current champion for `task`, or `None` if none has been promoted."""
        get_task(task)
        champion_id = self._champions.get(task)
        return self._versions[champion_id] if champion_id is not None else None
