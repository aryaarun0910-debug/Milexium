"""Program D: Milexium Core and adaptive memory -- v0.1 first slice only.

Full Program D scope (`blueprint/05-core-model-runtime-and-forecast.md`,
`blueprint/14-execution-roadmap.md`) is task registry + feature contracts +
model routing + memory tiers + parameter-delta registry + test-time
adaptation + calibration/drift services + champion/challenger/canary
promotion. This package implements only the task registry and a
champion-pointer model registry cataloging the `ModelVersion`s this
repository already has real evaluation evidence for
(`forge/knowledge/docs/MODEL_CARDS.md`); everything else in Program D remains Specified.

Not wired into `app/__init__.py` -- import directly from
`themis.core.task_registry` / `themis.core.model_registry` until a
central export is added.
"""

from themis.core.model_registry import (
    DuplicateModelVersionError,
    ModelRegistry,
    UnknownModelVersionError,
)
from themis.core.task_registry import TASK_REGISTRY, TaskDescriptor, UnknownTaskError, get_task

__all__ = [
    "DuplicateModelVersionError",
    "ModelRegistry",
    "UnknownModelVersionError",
    "TASK_REGISTRY",
    "TaskDescriptor",
    "UnknownTaskError",
    "get_task",
]

CONTRACT_VERSION = "0.1.0"
