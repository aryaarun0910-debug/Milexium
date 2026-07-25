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

PLATFORM-OWNED MODELS (ADR-0040). `ModelVersion.tenant_id` is mandatory, but the
five real models here are trained on public data and belong to no customer. They
are stamped with the one reserved `PLATFORM_TENANT_ID`, and resolution must let
any tenant use them while letting none of them claim one. That rule lives in
exactly one predicate, `ModelRegistry._is_visible_to`, which every resolution
method routes through -- not as a special case repeated at each call site. It
mirrors the asymmetric `model_versions` policy in
`packages/canonical/sql/rls_postgres.sql`, which is what actually enforces the
boundary at the database layer; this class is a tenant-aware view, not a
security control. `conformance/property-tests/test_platform_tenant.py` proves
both halves.
"""

from __future__ import annotations

from packages.canonical.entities import ModelVersion
from packages.canonical.ids import PLATFORM_TENANT_ID, ModelVersionId, TenantId
from packages.core.task_registry import get_task


class UnknownModelVersionError(ValueError):
    """Raised when a `model_version_id` has not been registered."""


class DuplicateModelVersionError(ValueError):
    """Raised when a `model_version_id` is registered a second time."""


def is_platform_owned(model_version: ModelVersion) -> bool:
    """True for a model owned by the platform rather than by a customer.

    The models in this repository are trained on public data (NYC TLC, Chicago
    TNP, MTA, NTD) and belong to no customer, so ADR-0040 reserved one
    well-known tenant id for them instead of making `tenant_id` nullable.
    """
    return model_version.tenant_id == PLATFORM_TENANT_ID


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

    @staticmethod
    def _is_visible_to(model_version: ModelVersion, tenant_id: TenantId) -> bool:
        """THE ONE PLACE the platform-tenant rule lives (ADR-0040).

        A tenant may resolve its own models and the platform's, and nobody
        else's. Every resolution method below routes through this predicate, so
        there is no `if tenant_id == PLATFORM ...` special case at each call
        site -- which is precisely the failure mode ADR-0040 rejected the
        nullable-`tenant_id` option to avoid: the first consumer that forgets
        the special case gets a silently wrong answer rather than an error.

        This mirrors the `model_versions` USING clause in sql/rls_postgres.sql
        (`tenant_id = GUC OR tenant_id = PLATFORM`) so an in-memory resolution
        and a database read agree on what is visible. It is deliberately
        READ-side only: the registry has no notion of writing a platform model,
        and the database's WITH CHECK is what refuses a forged one.
        """
        return model_version.tenant_id == tenant_id or is_platform_owned(model_version)

    def list_for_task(self, task: str, *, tenant_id: TenantId | None = None) -> tuple[ModelVersion, ...]:
        """Every registered version for `task`, in registration order.

        With `tenant_id`, only the versions that tenant may resolve: its own
        plus the platform's. Without it, every registered version regardless of
        owner -- the platform's own catalog view, and the pre-ADR-0040 behaviour
        every existing caller already relies on.
        """
        get_task(task)
        return tuple(
            v
            for v in self._versions.values()
            if v.task == task and (tenant_id is None or self._is_visible_to(v, tenant_id))
        )

    def promote(self, model_version_id: ModelVersionId) -> None:
        """Mark the given, already-registered version as champion for its task.
        A simple pointer: promoting a new version for a task just overwrites
        the previous pointer, it does not check the new version is better."""
        model_version = self.get(model_version_id)
        self._champions[model_version.task] = model_version_id

    def champion(self, task: str, *, tenant_id: TenantId | None = None) -> ModelVersion | None:
        """The current champion for `task`, or `None` if none has been promoted.

        With `tenant_id`, this is Program D's model RESOLUTION step and it
        answers for the acting tenant: the champion is returned when that tenant
        may resolve it -- its own model, or a PLATFORM-owned one, which is the
        whole point of ADR-0040's reserved tenant -- and `None` when the champion
        belongs to some other customer. `None` for "not resolvable by you" is the
        same answer as "nothing promoted yet", which is correct here: a tenant
        must not be able to tell another customer's champion apart from an empty
        registry.

        Without `tenant_id`, the unscoped pointer, unchanged.
        """
        get_task(task)
        champion_id = self._champions.get(task)
        if champion_id is None:
            return None
        model_version = self._versions[champion_id]
        if tenant_id is not None and not self._is_visible_to(model_version, tenant_id):
            return None
        return model_version
