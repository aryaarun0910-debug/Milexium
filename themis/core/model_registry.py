"""Model registry (Program D contract, v0.1 first slice).

Catalogs the `ModelVersion` canonical entities (`themis/canonical/entities.py`)
this repository already has real evaluation evidence for, and tracks a simple
"champion" pointer per task -- one model version, not a full champion/
challenger/canary lifecycle with shadow evaluation, drift detection, or
rollback (`blueprint/05-core-model-runtime-and-forecast.md`'s "Champion/
challenger" section describes that full lifecycle; it stays Specified).

`ModelRegistry` is the IN-MEMORY reference implementation, matching the pattern
`themis/canonical/events.py`'s `HashChainAppender` established.
`PersistentModelRegistry` (below) is the same contract over a real database.

WHAT THE PERSISTENT HALF CLOSES (MX-D-REGISTRY-PERSISTENCE-009). ADR-0041 and
ADR-0048 made Program D's promotion ROLES durable and left this catalog in a
dict, and IMPLEMENTATION_STATUS recorded the result plainly: "`ModelRegistry` is
still in-memory: promotion roles survive a restart, the model catalog does not."

That asymmetry is worse than either half of it would have been alone. A restored
`PersistentPromotionController` read a `champion_id` out of `promotion_champions`
and could not say what model that was -- not resolve it, not validate a challenger
against it, not describe it in an explanation -- because the `ModelVersion` it
named had lived only in the process that died. The pointer outliving its referent
is a dangling reference WITH an audit trail: every appearance of durability and
none of the content. `themis/core/promotion.py` named it in its own class
docstring rather than hiding it, and the 2 -> 3 migration
(`themis/core/migrations.py`) records how many such references each existing
database is carrying at the moment the catalog appears beneath them.

PLATFORM-OWNED MODELS (ADR-0040). `ModelVersion.tenant_id` is mandatory, but the
five real models here are trained on public data and belong to no customer. They
are stamped with the one reserved `PLATFORM_TENANT_ID`, and resolution must let
any tenant use them while letting none of them claim one. That rule lives in
exactly one predicate, `ModelRegistry._is_visible_to`, which every resolution
method routes through -- not as a special case repeated at each call site. It
mirrors the asymmetric `model_versions` policy in
`themis/canonical/sql/rls_postgres.sql`, which is what actually enforces the
boundary at the database layer; this class is a tenant-aware view, not a
security control. `aletheia/conformance/property-tests/test_platform_tenant.py` proves
both halves.
"""

from __future__ import annotations

from datetime import datetime, timezone

from themis.canonical.entities import ModelVersion
from themis.canonical.ids import PLATFORM_TENANT_ID, ModelVersionId, TenantId
from themis.core.feature_store import CoreDatabase, _iso_utc
from themis.core.migrations import model_reference_query
from themis.core.task_registry import get_task


class UnknownModelVersionError(ValueError):
    """Raised when a `model_version_id` has not been registered."""


class DuplicateModelVersionError(ValueError):
    """Raised when a `model_version_id` is registered a second time."""


class ForeignTenantModelError(ValueError):
    """A store bound to one tenant was asked to register another tenant's model.

    Including the PLATFORM's. That is not an oversight, it is ADR-0043's rule
    stated in Python so both engines behave alike: a session acting as a customer
    may READ a platform model and may not WRITE one, and the way the platform
    seeds its own catalog is by acting as itself. On PostgreSQL the `WITH CHECK`
    half of `core_model_versions`'s policy refuses the same write at the database
    layer; this exception is what makes SQLite -- which has no policy and cannot
    have one -- refuse it too, and what turns a `InsufficientPrivilege` from
    psycopg into an error that names the actual mistake."""


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


# --------------------------------------------------------------------------- #
# Persistent backend
# --------------------------------------------------------------------------- #
#: The catalog's columns, in the order `core_v0_1.sql` declares them. Written
#: once and used for both halves of the round trip, so a column added to the
#: SELECT and forgotten in the INSERT is not a thing that can happen.
_CATALOG_COLUMNS = (
    "tenant_id",
    "model_version_id",
    "task",
    "training_data_manifest_hash",
    "feature_schema_version",
    "evaluation_window_start",
    "evaluation_window_end",
    "artifact_hash",
    "registered_at",
    "registered_sequence",
)
_CATALOG_SELECT = ", ".join(_CATALOG_COLUMNS[:8])


class PersistentModelRegistry:
    """Durable `ModelVersion` catalog: `ModelRegistry`'s contract, backed by
    `core_model_versions` and `core_model_champions` in
    `themis/core/sql/core_v0_1.sql`.

    Method-for-method identical to the in-memory reference, so a caller can be
    handed either without changing a line -- proved structurally by
    `aletheia/conformance/property-tests/test_model_registry_persistence.py`, the same
    check `test_core_persistence.py` applies to the other two Program D stores.

    ONE TENANT PER REGISTRY, exactly as for `PersistentFeatureStore` and
    `PersistentPromotionController`. `tenant_id` is a required constructor
    argument, so there is no unscoped path to the table, and on PostgreSQL every
    operation first points the `milexium.tenant_id` GUC at it so the policy is
    the outer boundary and the `WHERE` clause the inner one.

    WHAT ONE TENANT MEANS HERE IS NOT WHAT IT MEANS FOR THE OTHER TWO STORES, and
    the difference is ADR-0040's whole reason for existing. A feature value
    belongs to the operator whose data produced it and to nobody else. A MODEL
    may belong to the platform: the five this repository has real evaluation
    evidence for are trained on public data (NYC TLC, Chicago TNP, MTA, NTD) and
    belong to no customer. So this store reads its OWN tenant's rows AND the
    platform's, and writes only its own -- readable by every tenant, writable by
    none of them. The rule is not re-implemented here: `_is_visible_to` on the
    in-memory class is still the single predicate, and
    `core_rls_postgres.sql`'s asymmetric `core_model_versions` policy is the
    database-layer statement of the same thing (ADR-0043, including the
    empty-string tightening -- a session with no tenant in scope reads NO rows,
    platform rows included).

    THE ONE THING THIS STORE CAN DO THAT THE IN-MEMORY ONE CANNOT is answer what
    it does NOT know: `unregistered_references()` lists the model versions this
    tenant's promotion state already points at and the catalog cannot describe.
    On a database migrated from version 2 that list starts non-empty by
    construction -- the roles were durable before the catalog was -- and it is
    the actionable form of the count the 2 -> 3 migration wrote into the ledger.

    TWO TABLES, AND THE SECOND ONE IS NOT `promotion_champions`.
    `ModelRegistry.promote()` is ADR-0010's simple pointer: it overwrites without
    evaluating a gate. `PersistentPromotionController` documents that it never
    touches that pointer, so the two mechanisms do not fight over one piece of
    state -- and persisting this one INTO `promotion_champions` would have made
    them fight, silently, by installing a serving champion that no
    `promotion_decisions` row authorised. `core_model_champions` is the cost of
    keeping that promise.
    """

    def __init__(self, database: CoreDatabase, tenant_id: TenantId) -> None:
        self._db = database
        # Validated as a canonical TenantId rather than accepted as any string:
        # a malformed tenant would otherwise become a silently distinct, and
        # permanently unreadable, partition of the catalog.
        self._tenant_id = str(TenantId(str(tenant_id)))

    @property
    def tenant_id(self) -> TenantId:
        """The single tenant this registry writes as. Read-only: rebinding it
        would turn one object into a cross-tenant path."""
        return TenantId(self._tenant_id)

    def _scope(self) -> None:
        """Point the session at this registry's tenant before any statement.
        A no-op on SQLite (no RLS to key); on PostgreSQL it is what makes the
        policy, rather than the WHERE clause, the boundary."""
        self._db.use_tenant(self._tenant_id)

    def _readable_tenants(self) -> tuple[str, ...]:
        """The tenants whose rows this registry may READ: its own, and the
        platform's -- own first, which is what makes `get` deterministic if both
        ever hold the same id. Deduplicated, because a registry bound to the
        platform tenant is both of them."""
        return tuple(dict.fromkeys((self._tenant_id, str(PLATFORM_TENANT_ID))))

    @staticmethod
    def _to_model_version(row: tuple) -> ModelVersion:
        return ModelVersion(
            tenant_id=TenantId(row[0]),
            model_version_id=ModelVersionId(row[1]),
            task=row[2],
            training_data_manifest_hash=row[3],
            feature_schema_version=row[4],
            evaluation_window_start=datetime.fromisoformat(row[5]),
            evaluation_window_end=datetime.fromisoformat(row[6]),
            artifact_hash=row[7],
        )

    def _find(self, model_version_id: ModelVersionId) -> ModelVersion | None:
        """The one visible row for an id, or `None`.

        Own tenant queried BEFORE the platform rather than both at once. The
        primary key is `(tenant_id, model_version_id)`, so a customer's id and a
        platform id CAN coincide -- uniqueness cannot be global under row-level
        security, because the check that would enforce it would have to read
        every other tenant's rows. Asking in priority order makes the answer
        deterministic instead of dependent on which row the planner reached
        first, and "your own model wins" is the only defensible priority: a
        platform id appearing later must not change what an operator's own id
        resolves to."""
        self._scope()
        for tenant in self._readable_tenants():
            rows = self._db.query(
                f"SELECT {_CATALOG_SELECT} FROM core_model_versions "
                "WHERE tenant_id = ? AND model_version_id = ?",
                (tenant, str(model_version_id)),
            )
            if rows:
                return self._to_model_version(rows[0])
        return None

    # -- writes ------------------------------------------------------------- #
    def register(self, model_version: ModelVersion) -> None:
        """Add a model version. Rejects an unknown task (Program D's model
        resolution starts by filtering on task, per blueprint 05's "Model
        resolution" step 1 -- a version for a task this registry doesn't know
        about can never be resolved), rejects re-registering an id this registry
        can already see, and rejects a model belonging to anyone but this
        registry's own tenant.

        THAT LAST REJECTION IS THE ADR-0043 RULE, not an extra restriction. A
        `ModelVersion` carries its own `tenant_id`; if that is not the tenant
        this store acts as, writing it would be forging a row for someone else --
        and for the PLATFORM tenant specifically it would be forging a model
        every other operator can then read. PostgreSQL refuses it independently
        (the `WITH CHECK` half of the policy) and SQLite cannot, so the check is
        here, where both engines pass through it. The platform seeds its own
        catalog by binding a registry to `PLATFORM_TENANT_ID`, which is the same
        "the GUC is the identity" trust model every other policy in this
        repository has.
        """
        get_task(model_version.task)
        owner = str(model_version.tenant_id)
        if owner != self._tenant_id:
            raise ForeignTenantModelError(
                f"this registry acts as tenant {self._tenant_id!r} and cannot "
                f"register a model owned by {owner!r}"
                + (
                    " -- that is the ADR-0040 PLATFORM tenant, whose models every "
                    "operator can read; seeding one means binding a registry to "
                    "the platform tenant, not writing it as a customer"
                    if owner == str(PLATFORM_TENANT_ID)
                    else ""
                )
            )
        if self._find(model_version.model_version_id) is not None:
            raise DuplicateModelVersionError(
                f"model_version_id {model_version.model_version_id!r} is already registered"
            )
        self._scope()
        # Per-tenant, as every application-assigned sequence in this schema is:
        # under RLS this MAX() sees only the acting tenant's rows, so a global
        # counter could not be derived even if one were wanted (core_v0_1.sql
        # note (c)).
        next_sequence = int(
            self._db.query(
                "SELECT COALESCE(MAX(registered_sequence), 0) + 1 "
                "FROM core_model_versions WHERE tenant_id = ?",
                (self._tenant_id,),
            )[0][0]
        )
        self._db.execute(
            f"INSERT INTO core_model_versions ({', '.join(_CATALOG_COLUMNS)}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self._tenant_id,
                str(model_version.model_version_id),
                model_version.task,
                model_version.training_data_manifest_hash,
                model_version.feature_schema_version,
                _iso_utc(model_version.evaluation_window_start),
                _iso_utc(model_version.evaluation_window_end),
                model_version.artifact_hash,
                _iso_utc(datetime.now(timezone.utc)),
                next_sequence,
            ),
        )
        self._db.commit()

    def promote(self, model_version_id: ModelVersionId) -> None:
        """Mark the given, already-registered version as champion for its task.
        A simple pointer: promoting a new version for a task just overwrites the
        previous pointer, it does not check the new version is better.

        The pointer is stamped with THIS registry's tenant even when the model it
        names is platform-owned, and that is the right way round: a platform model
        is shared, but the decision to serve it is one operator's and must not be
        readable by another (hence the symmetric policy on
        `core_model_champions`, beside the asymmetric one on the catalog).
        """
        model_version = self.get(model_version_id)
        self._scope()
        # DELETE + INSERT rather than an upsert, matching
        # `PersistentPromotionController.set_canary`: `ON CONFLICT` is spelled
        # compatibly on both engines but is a later addition to each, and two
        # statements are unambiguous in the portable subset (ADR-0002).
        self._db.execute(
            "DELETE FROM core_model_champions WHERE tenant_id = ? AND task = ?",
            (self._tenant_id, model_version.task),
        )
        self._db.execute(
            "INSERT INTO core_model_champions (tenant_id, task, champion_id) "
            "VALUES (?, ?, ?)",
            (self._tenant_id, model_version.task, str(model_version_id)),
        )
        self._db.commit()

    # -- reads -------------------------------------------------------------- #
    def get(self, model_version_id: ModelVersionId) -> ModelVersion:
        """The registered version for an id.

        Raises `UnknownModelVersionError` both when no such row exists and when
        one exists that this tenant may not resolve. The two are deliberately the
        same answer -- an operator must not be able to tell another customer's
        model apart from an id that was never registered, which would otherwise
        make this method an existence oracle over every tenant's catalog.

        Note that this CLOSES a gap ADR-0043 recorded and left open: the
        in-memory `ModelRegistry.get` is un-scoped, and no persistent equivalent
        could be -- there is no un-scoped way to reach a table under a policy."""
        model_version = self._find(model_version_id)
        if model_version is None:
            raise UnknownModelVersionError(
                f"no registered model version {model_version_id!r}"
            )
        return model_version

    def list_for_task(
        self, task: str, *, tenant_id: TenantId | None = None
    ) -> tuple[ModelVersion, ...]:
        """Every version for `task` this registry can see, in registration order.

        Ordered by `(registered_at, registered_sequence)`: the sequence is
        per-tenant and a listing may span two tenants (own and platform), so the
        sequence alone would produce a stable-looking order that was not a
        chronology. See core_v0_1.sql.

        `tenant_id` narrows the result exactly as it does on the in-memory class,
        through the same `_is_visible_to` predicate. What it CANNOT do is widen
        it: omitting it gives "everything this registry can see", which is this
        tenant's models plus the platform's -- never every registered version
        regardless of owner, which is what the in-memory class returns and what a
        shared table under a policy must not."""
        get_task(task)
        self._scope()
        tenants = self._readable_tenants()
        rows = self._db.query(
            f"SELECT {_CATALOG_SELECT} FROM core_model_versions "
            f"WHERE task = ? AND tenant_id IN ({', '.join('?' for _ in tenants)}) "
            "ORDER BY registered_at, registered_sequence, tenant_id",
            (task,) + tenants,
        )
        versions = tuple(self._to_model_version(row) for row in rows)
        if tenant_id is None:
            return versions
        return tuple(
            v for v in versions if ModelRegistry._is_visible_to(v, tenant_id)
        )

    def champion(
        self, task: str, *, tenant_id: TenantId | None = None
    ) -> ModelVersion | None:
        """The current champion for `task`, or `None` if none has been promoted.

        `None` for "not resolvable by you" is the same answer as "nothing
        promoted yet", for the reason the in-memory class gives: a tenant must
        not be able to tell another customer's champion apart from an empty
        registry.
        """
        get_task(task)
        self._scope()
        rows = self._db.query(
            "SELECT champion_id FROM core_model_champions "
            "WHERE tenant_id = ? AND task = ?",
            (self._tenant_id, task),
        )
        if not rows:
            return None
        champion_id = ModelVersionId(rows[0][0])
        model_version = self._find(champion_id)
        if model_version is None:
            # Only reachable if the catalog row went away after the pointer was
            # written. Raised rather than returned as None: "nothing promoted"
            # and "the promoted model has vanished" are different facts, and the
            # second one is the dangling-reference failure this whole packet
            # exists to end -- silently reporting it as the first would restore
            # it in a new place.
            raise UnknownModelVersionError(
                f"tenant {self._tenant_id!r} has {str(champion_id)!r} promoted for "
                f"task {task!r}, but no visible core_model_versions row describes "
                "it -- the champion pointer outlived its catalog entry"
            )
        if tenant_id is not None and not ModelRegistry._is_visible_to(
            model_version, tenant_id
        ):
            return None
        return model_version

    # -- the question only a persistent registry can be asked ---------------- #
    def unregistered_references(self) -> tuple[ModelVersionId, ...]:
        """Model versions this tenant's promotion state names and this catalog
        cannot describe, in id order.

        THE MIGRATION'S COUNT, MADE ACTIONABLE. A database migrated from schema
        version 2 arrives with durable promotion roles and an empty catalog, so
        this is non-empty by construction until a caller re-registers them -- and
        it cannot be re-populated automatically, because a champion pointer
        records an id, not a training manifest, a feature schema version, an
        evaluation window or an artifact hash. The 2 -> 3 migration counts these
        at migration time and writes the count into `core_schema_migrations`;
        this lists them, per tenant, at any time after.

        Scoped, unlike the migration's count: it reads through the policy on
        purpose, because the answer is "what must THIS operator re-register" and
        the operator has no business knowing another's dangling references. On
        SQLite, where there is no policy to read through, the `WHERE tenant_id =
        ?` over the derived table is what enforces the same thing -- which is why
        it is there rather than being left to RLS."""
        self._scope()
        referenced = [
            ModelVersionId(row[0])
            for row in self._db.query(
                "SELECT DISTINCT model_version_id FROM (\n"
                f"{model_reference_query()}\n"
                ") AS model_references WHERE tenant_id = ? "
                "ORDER BY model_version_id",
                (self._tenant_id,),
            )
        ]
        return tuple(
            model_version_id
            for model_version_id in referenced
            if self._find(model_version_id) is None
        )
