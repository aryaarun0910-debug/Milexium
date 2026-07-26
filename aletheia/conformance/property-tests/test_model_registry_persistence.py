"""Conformance: the MODEL CATALOG survives a restart (MX-D-REGISTRY-PERSISTENCE-009).

THE DEFECT THIS CLOSES, in the words that recorded it (IMPLEMENTATION_STATUS.md):

    "`ModelRegistry` is still in-memory: promotion roles survive a restart, the
     model catalog does not."

That asymmetry is worse than either half of it alone. `promotion_champions`
durably records a `model_version_id`; the `ModelVersion` it names lived in a
Python dict. A restored `PersistentPromotionController` therefore held a champion
pointer it could not resolve, validate a challenger against, or describe -- a
dangling reference WITH an audit trail, which has every appearance of durability
and none of the content. `themis/core/promotion.py` said so in its own class
docstring rather than hiding it.

FOUR CLAIMS ARE UNDER TEST, and the third is the one that could do real harm:

1. **The catalog is durable, and it is the same contract.** `PersistentModelRegistry`
   is method-for-method identical to the in-memory reference (checked structurally),
   behaves identically on the operations both can do (checked observably), and its
   rows and champion pointers come back after the connection is closed and reopened
   -- on SQLite and on PostgreSQL 17, from one code path.

2. **Adding a table to a versioned schema is a MIGRATION.** The schema now has a
   ledger (ADR-0055), so this is version 2 -> 3: detected, ordered, idempotent,
   refusing an unknown or newer version, and -- new here -- each step produces
   exactly ITS OWN version's shape, so an interrupted chain resumes from a state
   that is internally consistent rather than from a stamp that contradicts its
   tables.

3. **THE HAZARD ADR-0055 NAMED, MET FOR THE FIRST TIME.** Its limitations say:

       "A future data-moving migration on PostgreSQL will hit RLS. From v2 onward
        the tables are FORCEd, so a data-moving migration with no GUC in scope
        sees zero rows and 'succeeds' having moved nothing. 1 -> 2 is safe only
        because v1 predates RLS."

   The 2 -> 3 migration counts rows: how many model versions this database's
   promotion state ALREADY references, which the new (necessarily empty) catalog
   cannot describe. That count goes into the ledger permanently, so a wrong one is
   not a wrong log line, it is a false reassurance an operator will later act on.
   With no `milexium.tenant_id` in scope the honest-looking answer is ZERO. The
   suite proves the hazard is real (a blind count under the version-2 policy
   returns 0 while a scoped control proves the rows are there), proves the
   migration gets the RIGHT number anyway, and proves that if the handling were
   ever removed the migration REFUSES instead of recording the zero.

4. **The new tables are guarded like every other tenant-scoped table**, with the
   one asymmetry ADR-0040/0043 requires: a platform-owned model is readable by
   every scoped tenant and writable by none of them -- including through the
   ADR-0043 empty-string trap, which this is the only Program D table to be
   genuinely exposed to.

The PostgreSQL half skips cleanly (never fails) when the native `milexium_dev`
instance on 5432 is absent, so CI stays green -- but a skip proves nothing, so the
packet's evidence requirement is that these RUN.

SYNTHETIC data only, and labelled as such: a `ModelVersion` is a record about a
model, not operator data, and this packet moves no panel. Status: Demonstrated,
never operator-Validated.
"""

from __future__ import annotations

import inspect
import sqlite3
import uuid
from pathlib import Path

import pytest

from themis.canonical import ModelVersion, ModelVersionId, TenantId, new_id
from themis.canonical.ids import PLATFORM_TENANT_ID
from themis.canonical.postgres_storage import is_reachable as pg_is_reachable
from themis.core.feature_store import (
    CORE_RLS_PATH,
    CORE_SCHEMA_PATH,
    CoreDatabase,
    _read_dev_password,
)
from themis.core.migrations import (
    ALL_CORE_TABLES,
    CORE_MODEL_TABLES,
    CORE_SCHEMA_V2_PATH,
    CORE_TABLES,
    CURRENT_SCHEMA_VERSION,
    MIGRATION_LEDGER_TABLE,
    CoreSchemaError,
    RowSecurityInForceError,
    UnknownSchemaVersionError,
    _migrate_1_to_2,
    _migrate_2_to_3,
    applied_migrations,
    detect_shape,
    migrate,
    model_reference_query,
    split_statements,
)
from themis.core.model_registry import (
    DuplicateModelVersionError,
    ForeignTenantModelError,
    ModelRegistry,
    PersistentModelRegistry,
    UnknownModelVersionError,
)
from themis.core.task_registry import UnknownTaskError

from conformance.fixtures.builders import utc

psycopg = pytest.importorskip("psycopg")

from psycopg import sql as pg_sql  # noqa: E402

TASK = "forecast.demand"
_CANONICAL_SCHEMA = (
    Path(__file__).resolve().parents[3]
    / "themis"
    / "canonical"
    / "sql"
    / "schema_v0_1.sql"
)


def _model_version(
    tenant_id: TenantId, *, task: str = TASK, **overrides
) -> ModelVersion:
    """SYNTHETIC. A well-formed `ModelVersion`; the hashes are placeholders and
    nothing here reads them as anything but opaque text."""
    fields = dict(
        model_version_id=new_id(ModelVersionId),
        tenant_id=tenant_id,
        task=task,
        training_data_manifest_hash="deadbeef" * 8,
        feature_schema_version="zone_hour_demand_v1",
        evaluation_window_start=utc(2026, 3, 2),
        evaluation_window_end=utc(2026, 5, 31),
        artifact_hash="cafebabe" * 8,
    )
    fields.update(overrides)
    return ModelVersion(**fields)


# --------------------------------------------------------------------------- #
# SYNTHETIC version-2 rows. Three DISTINCT model version ids are referenced from
# eight columns across six tables -- so a migration that counted rows instead of
# distinct references, or that looked at one table and stopped, gets a different
# (and visibly wrong) number rather than a plausible one.
# --------------------------------------------------------------------------- #
_CHAMPION = "019a0000-0000-7000-8000-00000000c0de"
_CHALLENGER = "019a0000-0000-7000-8000-00000000beef"
_PRIOR = "019a0000-0000-7000-8000-0000000000a1"
_REFERENCED_IDS = frozenset({_CHAMPION, _CHALLENGER, _PRIOR})

_V2_ROWS: dict[str, tuple[str, tuple]] = {
    "feature_values": (
        "entity_id, feature_name, value, knowledge_time, write_sequence",
        ("zone-1", "lag1", 42.5, "2026-01-01T00:00:00.000000+00:00", 1),
    ),
    "promotion_decisions": (
        "decision_sequence, task, challenger_id, incumbent_id, metric_name, "
        "challenger_metric, incumbent_metric, higher_is_better, min_improvement, "
        "margin, promoted, decided_at, rationale",
        (
            1, TASK, _CHALLENGER, _CHAMPION, "wape", 0.2, 0.3, 0, 0.0, 0.1, 1,
            "2026-06-01T00:00:00.000000+00:00", "first champion",
        ),
    ),
    "promotion_rollbacks": (
        "rollback_sequence, task, from_champion_id, to_champion_id, decided_at, reason",
        (1, TASK, _CHAMPION, _PRIOR, "2026-06-02T00:00:00.000000+00:00", "error spike"),
    ),
    "promotion_champions": ("task, champion_id", (TASK, _CHAMPION)),
    "promotion_champion_history": (
        "task, stack_position, champion_id",
        (TASK, 1, _PRIOR),
    ),
    "promotion_challengers": (
        "task, model_version_id, enrol_sequence",
        (TASK, _CHALLENGER, 1),
    ),
    "promotion_canaries": (
        "task, model_version_id, traffic_fraction",
        (TASK, _CHALLENGER, 0.25),
    ),
}


def _seed_version_2(database: CoreDatabase, tenant: TenantId) -> None:
    for table, (columns, values) in _V2_ROWS.items():
        placeholders = ", ".join("?" for _ in values)
        database.execute(
            f"INSERT INTO {table} (tenant_id, {columns}) "  # noqa: S608
            f"VALUES (?, {placeholders})",
            (str(tenant),) + values,
        )
    database.commit()


def _apply_version_2_row_level_security(database: CoreDatabase) -> None:
    """The row-level security version 2 shipped: ENABLE + FORCE + one symmetric
    policy on each of the SEVEN tables.

    Generated here rather than read from `core_rls_postgres.sql`, because that
    file now also guards the two tables version 2 does not have -- applying it to
    a genuine version-2 database would fail on a missing relation. What matters
    for these tests is that the seven tables really are FORCEd before the
    migration runs, which is asserted from `pg_class` rather than assumed from
    this helper having been called."""
    for table in CORE_TABLES:
        database.execute_ddl(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        database.execute_ddl(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        database.execute_ddl(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        database.execute_ddl(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = current_setting('milexium.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true))"
        )
    database.commit()


def _rls_bits(database: CoreDatabase, table: str) -> tuple[bool, bool] | None:
    """`(relrowsecurity, relforcerowsecurity)` straight out of `pg_class`, or
    `None` if the relation does not exist. Read from the catalog rather than
    inferred from behaviour, so an ENABLE-only outcome fails explicitly instead
    of being masked by the acting role happening to see nothing."""
    rows = database.query(
        "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() AND c.relname = ?",
        (table,),
    )
    return (bool(rows[0][0]), bool(rows[0][1])) if rows else None


# --------------------------------------------------------------------------- #
# Engine fixture: durable storage that can be opened RAW (to build an old or
# deliberately broken database) or through CoreDatabase (which migrates).
# --------------------------------------------------------------------------- #
class _Engine:
    def __init__(self, kind: str, tmp_path: Path) -> None:
        self.kind = kind
        self._path = str(tmp_path / "core_registry.db")
        self._schema = f"mx_core_reg_{uuid.uuid4().hex}"
        self._opened: list[CoreDatabase] = []

    def raw(self) -> CoreDatabase:
        """A `CoreDatabase` over the storage with NO migration run. The only way
        to build a version-2 database at all, now that both constructors migrate
        on open -- a migration test that could only build its "old" database
        through today's code would not be testing a migration."""
        if self.kind == "sqlite":
            connection = sqlite3.connect(self._path)
            connection.execute("PRAGMA foreign_keys = ON")
            database = CoreDatabase(connection, placeholder="?")
        else:
            connection = psycopg.connect(
                host="localhost",
                port=5432,
                dbname="milexium_dev",
                user="milexium_dev",
                password=_read_dev_password(),
            )
            ident = pg_sql.Identifier(self._schema)
            with connection.cursor() as cur:
                cur.execute(pg_sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(ident))
                cur.execute(pg_sql.SQL("SET search_path TO {}").format(ident))
            connection.commit()
            database = CoreDatabase(connection, placeholder="%s", schema=self._schema)
        self._opened.append(database)
        return database

    def create_version_2(
        self, *, seeded: bool = True, tenant: TenantId | None = None, rls: bool = True
    ) -> tuple[CoreDatabase, TenantId]:
        """A genuine ADR-0048 database, built from the preserved version-2 DDL's
        own bytes -- and, on PostgreSQL, carrying the row-level security version 2
        actually shipped with. The RLS is the point: without it this fixture would
        be testing a migration against a database no deployment ever had, and the
        hazard under test would be invisible."""
        tenant = tenant or new_id(TenantId)
        database = self.raw()
        for statement in split_statements(
            CORE_SCHEMA_V2_PATH.read_text(encoding="utf-8")
        ):
            database.execute_ddl(statement)
        database.commit()
        if seeded:
            _seed_version_2(database, tenant)
        if rls and self.kind == "postgres":
            _apply_version_2_row_level_security(database)
        return database, tenant

    def open(self, **kwargs) -> CoreDatabase:
        database = (
            CoreDatabase.sqlite(self._path, **kwargs)
            if self.kind == "sqlite"
            else CoreDatabase.postgres(schema=self._schema, **kwargs)
        )
        self._opened.append(database)
        return database

    def open_fresh(self) -> CoreDatabase:
        """A brand-new database at the current version in its OWN storage -- the
        reference a migrated database's shape is compared against."""
        database = (
            CoreDatabase.sqlite(self._path + ".fresh")
            if self.kind == "sqlite"
            else CoreDatabase.postgres(schema=self._schema + "_fresh")
        )
        self._opened.append(database)
        return database

    def cleanup(self) -> None:
        for database in self._opened:
            try:
                database._conn.rollback()
            except Exception:  # pragma: no cover - teardown must not mask failures
                pass
            if database.schema is not None:
                try:
                    database.drop_schema()
                except Exception:  # pragma: no cover
                    pass
            try:
                database.close()
            except Exception:  # pragma: no cover
                pass


@pytest.fixture(params=["sqlite", "postgres"])
def engine(request, tmp_path):
    """One contract, both engines (ADR-0002/0004). The SQLite parameter always
    runs; the PostgreSQL parameter skips cleanly when the native instance is
    absent."""
    if request.param == "postgres" and not pg_is_reachable():
        pytest.skip("PostgreSQL (milexium_dev, port 5432) is not reachable")
    instance = _Engine(request.param, tmp_path)
    try:
        yield instance
    finally:
        instance.cleanup()


@pytest.fixture
def pg_engine(tmp_path):
    """PostgreSQL only -- for the row-level-security half, which has no SQLite
    counterpart to run (SQLite has no policies and cannot have any)."""
    if not pg_is_reachable():
        pytest.skip("PostgreSQL (milexium_dev, port 5432) is not reachable")
    instance = _Engine("postgres", tmp_path)
    try:
        yield instance
    finally:
        instance.cleanup()


@pytest.fixture
def migrated_pg(pg_engine):
    """A seeded, RLS-carrying version-2 PostgreSQL database, migrated to the
    current version. Yields `(database, tenant)`."""
    _, tenant = pg_engine.create_version_2()
    pg_engine._opened[-1].close()
    return pg_engine.open(), tenant


# =========================================================================
# 0. Portability, and the two names that must not collide
# =========================================================================


def test_the_catalog_ddl_runs_unmodified_on_a_bare_sqlite_connection() -> None:
    """ADR-0002's portability discipline, applied to what this packet adds.
    Executed from the FILE'S OWN BYTES against a bare `sqlite3.connect(':memory:')`
    -- no `CoreDatabase`, no helper -- and applied TWICE, because reopening an
    existing database is the persistence claim itself and a DDL file that could
    only be applied once would not survive it."""
    connection = sqlite3.connect(":memory:")
    try:
        for _ in range(2):
            connection.executescript(CORE_SCHEMA_PATH.read_text(encoding="utf-8"))
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert set(CORE_MODEL_TABLES) <= names
    finally:
        connection.close()


def test_the_preserved_version_2_ddl_still_runs_and_has_no_catalog() -> None:
    """The version-2 file is a specification AND the thing the 1 -> 2 step
    applies, so a version of it that stopped parsing would break a migration and
    not merely a test. It must also keep NOT having the catalog: the moment it
    grows one, the migration it defines stops being a migration."""
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(CORE_SCHEMA_V2_PATH.read_text(encoding="utf-8"))
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert set(CORE_TABLES) <= names
        assert not (set(CORE_MODEL_TABLES) & names), (
            "the version-2 DDL has grown a catalog table -- it is a HISTORICAL "
            "artifact and must keep recording the shape that actually shipped"
        )
    finally:
        connection.close()


def test_the_catalog_table_is_not_named_model_versions() -> None:
    """THE COLLISION THAT WOULD NOT HAVE BEEN AN ERROR. The canonical contract
    already declares a table called `model_versions`, and a Program D store can be
    opened against a database that also carries the canonical schema -- these
    tables deliberately hold no foreign key into it, which is exactly what makes
    that combination legal. Two tables of that name in one schema would not
    collide loudly: `CREATE TABLE IF NOT EXISTS` means whichever contract created
    it first silently ABSORBS the other's writes, and each then reads the other's
    rows as its own. Same reasoning that named the ledger `core_schema_migrations`
    (ADR-0055), applied where the other table genuinely exists."""
    core_ddl = CORE_SCHEMA_PATH.read_text(encoding="utf-8")
    canonical_ddl = _CANONICAL_SCHEMA.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS core_model_versions" in core_ddl
    assert "CREATE TABLE model_versions" in canonical_ddl, (
        "the canonical schema no longer declares model_versions -- if it moved, "
        "the reason this table is prefixed needs revisiting, not this assertion "
        "deleting"
    )
    for statement in split_statements(core_ddl):
        assert not statement.startswith("CREATE TABLE IF NOT EXISTS model_versions"), (
            "themis/core declares a bare `model_versions`, which the canonical "
            "contract already owns"
        )


def test_the_platform_tenant_literal_in_the_core_rls_file_has_not_drifted() -> None:
    """A `PLATFORM_TENANT_ID` the policy does not know about is a naming
    convention wearing a security boundary's clothes. The literal appears exactly
    ONCE and it is in the READ half."""
    rls = CORE_RLS_PATH.read_text(encoding="utf-8")
    body = "\n".join(
        line for line in rls.splitlines() if not line.strip().startswith("--")
    )

    assert body.count(str(PLATFORM_TENANT_ID)) == 1, (
        "the platform tenant literal appears somewhere other than the one "
        "core_model_versions USING clause it belongs in"
    )
    policy = next(
        statement
        for statement in split_statements(rls)
        if statement.startswith("CREATE POLICY tenant_isolation ON core_model_versions")
    )
    using, with_check = policy.split("WITH CHECK")
    assert str(PLATFORM_TENANT_ID) in using, (
        "a scoped tenant can no longer READ a platform model -- ADR-0040's "
        "reserved tenant exists precisely so that it can"
    )
    assert str(PLATFORM_TENANT_ID) not in with_check, (
        "the WITH CHECK half admits the platform id, so a session acting as a "
        "customer could FORGE a platform model -- readable by every operator"
    )


def test_no_clause_this_packet_added_is_written_as_is_not_null() -> None:
    """ADR-0043's empty-string trap, guarded statically as well as behaviourally.
    `current_setting(name, true)` returns NULL only when the GUC was NEVER set;
    after `RESET` it returns the EMPTY STRING, which `IS NOT NULL` accepts. A
    previous fix written that way did not work, and the prose would not have
    caught it."""
    body = "\n".join(
        line
        for line in CORE_RLS_PATH.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("--")
    )
    assert "IS NOT NULL" not in body.upper()
    assert "coalesce(current_setting('milexium.tenant_id', true), '') <> ''" in body


def test_the_statement_splitter_is_pinned_to_the_files_it_splits() -> None:
    """`split_statements` strips `--` comments and splits on `;`, which is correct
    for these files and would be wrong for one containing either inside a string
    literal. Pinning the COUNTS is what makes that assumption fail HERE rather
    than by silently truncating a schema at the offending statement."""
    counts = {
        CORE_SCHEMA_PATH: 11,  # 9 tables + 2 indexes
        CORE_SCHEMA_V2_PATH: 8,  # the 7 version-2 tables + the as-of index
        CORE_RLS_PATH: 36,  # 9 tables x (ENABLE, FORCE, DROP POLICY, CREATE POLICY)
    }
    for path, expected in counts.items():
        statements = split_statements(path.read_text(encoding="utf-8"))
        assert len(statements) == expected, (
            f"{path.name} split into {len(statements)} statements, expected "
            f"{expected} -- either the file changed or the splitter has stopped "
            "being correct for it"
        )


# =========================================================================
# 1. The catalog is durable, and it is the SAME contract
# =========================================================================


def test_the_persistent_registry_mirrors_the_in_memory_contract() -> None:
    """The whole claim is that a caller can be handed either backend without
    changing a line. Checked structurally rather than trusted: same method names,
    same signatures. `__init__` is excluded -- one takes a database and a tenant,
    the other takes nothing, and that is the only difference there is meant to
    be."""
    for name in ("register", "get", "list_for_task", "promote", "champion"):
        reference = getattr(ModelRegistry, name)
        persistent = getattr(PersistentModelRegistry, name)
        assert inspect.signature(reference) == inspect.signature(persistent), (
            f"ModelRegistry.{name} has diverged from PersistentModelRegistry.{name}"
        )


def test_the_model_catalog_survives_a_restart(engine) -> None:
    """THE DEFECT, stated as a test. Register, drop the connection entirely,
    reopen the same storage, and the model version is still there and still
    equal -- field for field, not merely present by id."""
    tenant = new_id(TenantId)
    model_version = _model_version(tenant)
    PersistentModelRegistry(engine.open(), tenant).register(model_version)
    engine._opened[-1].close()

    restored = PersistentModelRegistry(engine.open(), tenant)
    assert restored.get(model_version.model_version_id) == model_version


def test_the_registry_champion_pointer_survives_a_restart(engine) -> None:
    """Both halves of the registry's state, not just the catalog. A catalog that
    came back without its champion pointer would have moved the defect rather
    than closed it."""
    tenant = new_id(TenantId)
    model_version = _model_version(tenant)
    first = PersistentModelRegistry(engine.open(), tenant)
    first.register(model_version)
    first.promote(model_version.model_version_id)
    engine._opened[-1].close()

    assert PersistentModelRegistry(engine.open(), tenant).champion(TASK) == model_version


def test_a_restored_catalog_answers_every_read_the_in_memory_one_does(engine) -> None:
    """Signature parity says the contract looks the same; this says it ANSWERS
    the same. The identical sequence of operations is run against both backends
    and every observable compared -- after the persistent one has been closed and
    reopened, so what is compared is a restored database rather than a warm
    object."""
    tenant = new_id(TenantId)
    first, second = _model_version(tenant), _model_version(tenant)

    reference = ModelRegistry()
    persistent = PersistentModelRegistry(engine.open(), tenant)
    for registry in (reference, persistent):
        registry.register(first)
        registry.register(second)
        registry.promote(first.model_version_id)
        registry.promote(second.model_version_id)
    engine._opened[-1].close()
    restored = PersistentModelRegistry(engine.open(), tenant)

    assert restored.get(first.model_version_id) == reference.get(first.model_version_id)
    assert restored.champion(TASK) == reference.champion(TASK) == second
    assert restored.list_for_task(TASK) == reference.list_for_task(TASK) == (
        first,
        second,
    )


def test_registration_order_is_preserved_across_a_restart(engine) -> None:
    """`list_for_task` promises registration order, and a dict preserves insertion
    order for free where a table does not. A restored listing that came back in
    primary-key order would look plausible and be wrong."""
    tenant = new_id(TenantId)
    versions = [_model_version(tenant) for _ in range(4)]
    registry = PersistentModelRegistry(engine.open(), tenant)
    for model_version in versions:
        registry.register(model_version)
    engine._opened[-1].close()

    restored = PersistentModelRegistry(engine.open(), tenant)
    assert restored.list_for_task(TASK) == tuple(versions)


def test_get_unknown_model_version_id_raises(engine) -> None:
    registry = PersistentModelRegistry(engine.open(), new_id(TenantId))
    with pytest.raises(UnknownModelVersionError):
        registry.get(new_id(ModelVersionId))


def test_register_unknown_task_is_rejected(engine) -> None:
    """Rejected BEFORE the row is written, so an unresolvable version never
    reaches the table (Program D's resolution starts by filtering on task, so a
    version for an unknown task can never be resolved and would sit there
    forever)."""
    tenant = new_id(TenantId)
    database = engine.open()
    registry = PersistentModelRegistry(database, tenant)
    with pytest.raises(UnknownTaskError):
        registry.register(_model_version(tenant, task="forecast.no_show"))

    database.use_tenant(tenant)
    assert database.query("SELECT COUNT(*) FROM core_model_versions")[0][0] == 0


def test_register_same_model_version_id_twice_is_rejected(engine) -> None:
    tenant = new_id(TenantId)
    registry = PersistentModelRegistry(engine.open(), tenant)
    model_version = _model_version(tenant)
    registry.register(model_version)
    with pytest.raises(DuplicateModelVersionError):
        registry.register(model_version)


def test_promote_unregistered_model_version_raises(engine) -> None:
    registry = PersistentModelRegistry(engine.open(), new_id(TenantId))
    with pytest.raises(UnknownModelVersionError):
        registry.promote(new_id(ModelVersionId))


def test_champion_is_none_before_any_promotion(engine) -> None:
    assert PersistentModelRegistry(engine.open(), new_id(TenantId)).champion(TASK) is None


def test_list_for_task_returns_only_that_tasks_versions(engine) -> None:
    """The task filter is in the SQL, and it is proved against a row the store
    itself would refuse to write.

    `TASK_REGISTRY` is a CLOSED vocabulary of one task today, so a second version
    for a second task cannot be registered through `register()` at all -- which
    would make this test unwritable, or (worse) writable as a tautology over a
    single row. The other row therefore goes in by raw SQL: the table has no
    CHECK on `task`, so a row like this is exactly what a future task, or a
    writer that did not go through this class, would produce."""
    tenant = new_id(TenantId)
    database = engine.open()
    registry = PersistentModelRegistry(database, tenant)
    demand = _model_version(tenant)
    registry.register(demand)

    database.use_tenant(tenant)
    database.execute(
        "INSERT INTO core_model_versions (tenant_id, model_version_id, task, "
        "training_data_manifest_hash, feature_schema_version, "
        "evaluation_window_start, evaluation_window_end, artifact_hash, "
        "registered_at, registered_sequence) "
        "VALUES (?, ?, 'forecast.duration', 'x', 'y', 'a', 'b', 'z', 'c', 2)",
        (str(tenant), str(new_id(ModelVersionId))),
    )
    database.commit()

    assert registry.list_for_task(TASK) == (demand,)
    # Control: the other row really is in the table, and really is this tenant's.
    assert database.query("SELECT COUNT(*) FROM core_model_versions")[0][0] == 2


def test_list_for_task_unknown_task_raises(engine) -> None:
    with pytest.raises(UnknownTaskError):
        PersistentModelRegistry(engine.open(), new_id(TenantId)).list_for_task(
            "forecast.no_show"
        )


# =========================================================================
# 2. Tenant scoping and the platform tenant (both engines -- SQLite has only
#    the predicate, PostgreSQL has the predicate AND the policy)
# =========================================================================


def test_a_second_tenant_cannot_see_the_first_tenants_models(engine) -> None:
    """Two registries over ONE database. The catalog is a shared table, which is
    the entire reason it needs a boundary at all -- proved on both engines,
    because on SQLite the store's predicate is the only thing standing there."""
    database = engine.open()
    owner, stranger = new_id(TenantId), new_id(TenantId)
    model_version = _model_version(owner)
    PersistentModelRegistry(database, owner).register(model_version)

    other = PersistentModelRegistry(database, stranger)
    assert other.list_for_task(TASK) == ()
    with pytest.raises(UnknownModelVersionError):
        other.get(model_version.model_version_id)
    # Control: the row really is there, for the tenant that registered it.
    assert PersistentModelRegistry(database, owner).get(
        model_version.model_version_id
    ) == model_version


def test_a_platform_model_is_resolvable_by_every_tenant(engine) -> None:
    """ADR-0040's whole point. The five models this repository has evaluation
    evidence for are trained on public data and belong to no customer; a strict
    `tenant_id = me` would make them invisible to the operators who must run
    them."""
    database = engine.open()
    customer = new_id(TenantId)
    platform_model = _model_version(PLATFORM_TENANT_ID)
    PersistentModelRegistry(database, PLATFORM_TENANT_ID).register(platform_model)

    registry = PersistentModelRegistry(database, customer)
    assert registry.get(platform_model.model_version_id) == platform_model
    assert platform_model in registry.list_for_task(TASK)


def test_a_customer_registry_cannot_register_a_platform_model(engine) -> None:
    """The other half of the asymmetry, in Python so both engines refuse it: a
    customer may USE a platform model and may not FORGE one. The platform seeds
    its own catalog by binding a registry to the platform tenant -- the same
    "the GUC is the identity" trust model every policy in this repository has."""
    tenant = new_id(TenantId)
    registry = PersistentModelRegistry(engine.open(), tenant)

    with pytest.raises(ForeignTenantModelError) as raised:
        registry.register(_model_version(PLATFORM_TENANT_ID))
    assert "PLATFORM" in str(raised.value)


def test_registering_another_customers_model_is_refused(engine) -> None:
    """Not a platform special case: a store bound to A cannot write a row stamped
    B, full stop. Without this the `tenant_id` on a `ModelVersion` and the tenant
    a store acts as could silently disagree, and the row would land under whoever
    the object claimed to be."""
    registry = PersistentModelRegistry(engine.open(), new_id(TenantId))
    with pytest.raises(ForeignTenantModelError):
        registry.register(_model_version(new_id(TenantId)))


def test_the_tenant_kwarg_narrows_a_listing_and_cannot_widen_it(engine) -> None:
    """`list_for_task(tenant_id=...)` filters through the same `_is_visible_to`
    predicate the in-memory class uses. What it cannot do is reach another
    customer's rows -- which is a real divergence from the in-memory class, whose
    unscoped listing returns every registered version regardless of owner."""
    database = engine.open()
    customer = new_id(TenantId)
    own = _model_version(customer)
    platform_model = _model_version(PLATFORM_TENANT_ID)
    PersistentModelRegistry(database, customer).register(own)
    PersistentModelRegistry(database, PLATFORM_TENANT_ID).register(platform_model)

    registry = PersistentModelRegistry(database, customer)
    assert set(registry.list_for_task(TASK)) == {own, platform_model}
    assert registry.list_for_task(TASK, tenant_id=customer) == registry.list_for_task(
        TASK
    )
    # A third party sees only what IT may resolve, even through this registry.
    assert registry.list_for_task(TASK, tenant_id=new_id(TenantId)) == (platform_model,)


def test_a_restored_controller_can_resolve_the_champion_it_was_left_holding(
    engine,
) -> None:
    """THE DEFECT'S ACTUAL CONSEQUENCE, closed end to end.

    `PersistentPromotionController` validates every role assignment through
    `_require_registered_for_task`, which calls `registry.get()`. Its ROLES were
    durable and the registry behind that `get()` was a dict a restart emptied, so
    a restored controller held a `model_version_id` it could not resolve -- it
    could not say what the model was, could not accept a challenger against it,
    and could not explain the choice. Composed with a persistent registry, both
    halves come back together.

    THE ORDERING BELOW IS DELIBERATE AND WAS FOUND BY MUTATION-TESTING THIS TEST.
    Written the obvious way -- register, enrol, close, reopen -- it stayed GREEN
    with the registry's own `commit()` deleted, because the controller shares this
    `CoreDatabase` and ITS commit swept the registry's pending INSERT along with
    it. The catalog write is therefore committed and reopened on its own, BEFORE
    any controller exists, so the registry's durability is load-bearing here and
    not borrowed from a neighbour.

    The CONTROL at the end is the other important half: the same restored roles,
    composed with a fresh in-memory `ModelRegistry` -- precisely what a restart
    used to leave -- are still unresolvable. Without that line this test would
    pass just as happily against the old behaviour, because the promotion tables
    were already durable."""
    from themis.core.promotion import PersistentPromotionController

    tenant = new_id(TenantId)
    challenger = _model_version(tenant)
    PersistentModelRegistry(engine.open(), tenant).register(challenger)
    engine._opened[-1].close()

    # A NEW connection. Nothing but the registry's own commit can have carried
    # the catalog row this far, and `register_challenger` resolves it through
    # `_require_registered_for_task` -> `registry.get()` before it writes.
    second = engine.open()
    PersistentPromotionController(
        PersistentModelRegistry(second, tenant), second, tenant
    ).register_challenger(TASK, challenger.model_version_id)
    second.close()

    reopened = engine.open()
    restored_registry = PersistentModelRegistry(reopened, tenant)
    restored = PersistentPromotionController(restored_registry, reopened, tenant)

    assert restored.challengers(TASK) == (challenger.model_version_id,)
    # The role came back AND the thing it points at can be described again.
    assert restored_registry.get(challenger.model_version_id) == challenger

    # CONTROL: with the in-memory registry a restart used to leave behind, the
    # same durable role is unresolvable -- which is the defect, reproduced.
    with pytest.raises(UnknownModelVersionError):
        PersistentPromotionController(
            ModelRegistry(), reopened, tenant
        ).register_challenger(TASK, challenger.model_version_id)


def test_the_registry_champion_pointer_does_not_touch_the_promotion_ledger(
    engine,
) -> None:
    """The two champion mechanisms must not fight. `PersistentPromotionController`
    documents that it never touches the registry's ADR-0010 pointer, and the
    converse has to hold too: persisting this one into `promotion_champions`
    would have installed a serving champion that no `promotion_decisions` row
    authorised, making the ledger incomplete for the first time."""
    tenant = new_id(TenantId)
    database = engine.open()
    registry = PersistentModelRegistry(database, tenant)
    model_version = _model_version(tenant)
    registry.register(model_version)
    registry.promote(model_version.model_version_id)

    database.use_tenant(tenant)
    assert database.query("SELECT COUNT(*) FROM promotion_champions")[0][0] == 0
    assert database.query("SELECT COUNT(*) FROM promotion_decisions")[0][0] == 0
    assert database.query("SELECT COUNT(*) FROM core_model_champions")[0][0] == 1


# =========================================================================
# 3. Schema shape: tenant_id NOT NULL and leading the key, on both engines
# =========================================================================


@pytest.mark.parametrize("table", CORE_MODEL_TABLES)
def test_the_new_tables_carry_a_not_null_tenant_id(engine, table: str) -> None:
    """A NULLABLE tenant would be barely better than none:
    `tenant_id = current_setting(...)` is never true for NULL, so a null-tenant
    row would be invisible under the policy AND present in the table --
    unreadable, undeletable through the store, permanently unattributable. Read
    out of each engine's own catalog, so a column that exists only in the file's
    text fails here."""
    database = engine.open()
    if engine.kind == "sqlite":
        columns = {
            row[1]: bool(row[3])
            for row in database.query(f"PRAGMA table_info({table})")  # noqa: S608
        }
    else:
        columns = {
            row[0]: row[1] == "NO"
            for row in database.query(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = ? AND table_name = ?",
                (database.schema, table),
            )
        }
    assert "tenant_id" in columns, f"{table} has no tenant_id column"
    assert columns["tenant_id"] is True, f"{table}.tenant_id is nullable"


@pytest.mark.parametrize("table", CORE_MODEL_TABLES)
def test_tenant_id_leads_the_new_primary_keys(engine, table: str) -> None:
    """FIRST in the key, not merely present. Uniqueness becomes per-tenant -- two
    operators can each hold a champion for `forecast.demand`, which they must,
    since the task name is not customer-specific -- and the tenant predicate
    leads the index that serves resolution."""
    database = engine.open()
    if engine.kind == "sqlite":
        key = sorted(
            (row[5], row[1])
            for row in database.query(f"PRAGMA table_info({table})")  # noqa: S608
            if row[5]
        )
        first = key[0][1]
    else:
        first = database.query(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_attribute a ON a.attrelid = c.oid "
            "AND a.attnum = i.indkey[0] "
            "WHERE n.nspname = current_schema() AND c.relname = ? AND i.indisprimary",
            (table,),
        )[0][0]
    assert first == "tenant_id"


# =========================================================================
# 4. The migration: version 2 -> 3
# =========================================================================


def test_a_version_two_database_is_detected_as_version_two(engine) -> None:
    """Detected from its TABLE SET and columns -- version 2 has no ledger row of
    its own unless something stamped one, which is true of every Program D
    database written before ADR-0055."""
    database, _ = engine.create_version_2()
    assert detect_shape(database) == 2


def test_a_version_two_database_is_stamped_then_migrated(engine) -> None:
    """The inference happens exactly ONCE. Version 2 is recorded as 'adopted' --
    recognised and stamped, nothing changed -- and only then is version 3 applied
    on top of a recorded fact rather than a fresh guess."""
    engine.create_version_2()[0].close()
    ledger = applied_migrations(engine.open())

    assert [(row.version, row.applied_by) for row in ledger] == [
        (2, "adopted"),
        (3, "migrated"),
    ]


def test_migrating_a_version_two_database_reaches_the_current_shape(engine) -> None:
    """The claim is not "it has a catalog now" but "it is INDISTINGUISHABLE from a
    database created at the current version". Compared against a REAL freshly
    created database rather than a list of expected columns, because a list would
    be a second place for the schema to be written down."""
    engine.create_version_2()[0].close()
    migrated = engine.open()
    fresh = engine.open_fresh()

    for table in ALL_CORE_TABLES:
        assert migrated.column_names(table) == fresh.column_names(table), (
            f"{table} after migration does not match a freshly-created database"
        )
    assert migrated.schema_version() == fresh.schema_version() == CURRENT_SCHEMA_VERSION


def test_the_migration_does_not_disturb_a_single_existing_row(engine) -> None:
    """2 -> 3 is additive: no rebuild, no rewrite, nothing renamed. The seven
    version-2 tables must come through untouched, and "untouched" is asserted on
    the ROWS rather than inferred from the migration not having any code that
    would move them."""
    database, tenant = engine.create_version_2()
    database.close()
    migrated = engine.open()
    migrated.use_tenant(tenant)

    for table in CORE_TABLES:
        assert int(migrated.query(f"SELECT COUNT(*) FROM {table}")[0][0]) == 1, (  # noqa: S608
            f"{table} lost its row in the 2 -> 3 migration"
        )
    assert migrated.query("SELECT value FROM feature_values")[0][0] == 42.5


def test_a_version_one_database_migrates_all_the_way_to_three(engine) -> None:
    """The chain is now longer than one step, which is what ADR-0055 said had not
    been exercised: "a three-step chain is not proved by a one-step one". A
    genuine pre-tenant database walks 1 -> 2 -> 3 in one open, and every stamp is
    recorded in order."""
    from themis.core.migrations import CORE_SCHEMA_V1_PATH

    database = engine.raw()
    for statement in split_statements(CORE_SCHEMA_V1_PATH.read_text(encoding="utf-8")):
        database.execute_ddl(statement)
    database.commit()
    database.close()

    migrated = engine.open()
    assert [(row.version, row.applied_by) for row in applied_migrations(migrated)] == [
        (1, "adopted"),
        (2, "migrated"),
        (3, "migrated"),
    ]
    assert migrated.schema_version() == CURRENT_SCHEMA_VERSION


def test_the_one_to_two_step_produces_the_version_two_shape_and_stops(engine) -> None:
    """EACH STEP PRODUCES ITS OWN VERSION'S SHAPE. Applied directly, 1 -> 2 must
    leave a database detected as version 2 -- not as version 3.

    This is not tidiness. `migrate()` commits between stamps, so a step that
    created the current shape would leave the tables at 3 while the ledger said 2
    for a real, committed window; a crash there yields a `SchemaShapeMismatchError`
    on the next open that nobody introduced by hand and no tool can resolve. It is
    why `core_v0_2_pre_catalog.sql` is preserved AND applied."""
    from themis.core.migrations import CORE_SCHEMA_V1_PATH

    database = engine.raw()
    for statement in split_statements(CORE_SCHEMA_V1_PATH.read_text(encoding="utf-8")):
        database.execute_ddl(statement)
    database.commit()

    _migrate_1_to_2(database, None)
    database.commit()

    assert detect_shape(database) == 2, (
        "the 1 -> 2 step produced a shape that is not version 2 -- an interrupted "
        "chain would then resume from a stamp that contradicts its own tables"
    )


def test_migrating_twice_is_a_no_op(engine) -> None:
    engine.create_version_2()[0].close()
    database = engine.open()
    before = applied_migrations(database)

    assert migrate(database) == (CURRENT_SCHEMA_VERSION, CURRENT_SCHEMA_VERSION)
    assert applied_migrations(database) == before


def test_the_ledger_records_each_version_exactly_once(engine) -> None:
    """`version` is the ledger's PRIMARY KEY, so a second stamp of the same
    version is refused by the DATABASE rather than merely skipped by Python."""
    engine.create_version_2()[0].close()
    database = engine.open()
    for _ in range(3):
        migrate(database)

    versions = [row.version for row in applied_migrations(database)]
    assert versions == sorted(set(versions)) == [2, 3]


def test_a_version_two_database_carrying_a_catalog_table_is_refused(engine) -> None:
    """Shape detection matches the table SET exactly. A version-2 database that
    has acquired `core_model_versions` is not "version 2 with an extra table" --
    it is a shape no release ever produced, and running a migration that CREATES
    that table over one that may already hold rows is how a migration destroys
    data."""
    database, _ = engine.create_version_2()
    database.execute_ddl(
        "CREATE TABLE core_model_versions (tenant_id TEXT NOT NULL, "
        "model_version_id TEXT NOT NULL, PRIMARY KEY (tenant_id, model_version_id))"
    )
    database.commit()
    database.close()

    with pytest.raises(UnknownSchemaVersionError):
        engine.open()


def test_the_two_to_three_precheck_refuses_an_existing_catalog_table(engine) -> None:
    """The same refusal reached the other way -- by calling the migration
    directly, which ADR-0055's design requires to be no less guarded than going
    through the runner."""
    database, _ = engine.create_version_2()
    database.execute_ddl("CREATE TABLE core_model_champions (tenant_id TEXT NOT NULL)")
    database.commit()

    with pytest.raises(CoreSchemaError) as raised:
        _migrate_2_to_3(database, None)
    assert "core_model_champions" in str(raised.value)


def test_the_migration_records_what_the_empty_catalog_starts_life_owing(
    engine,
) -> None:
    """The ledger note is where a migration's DECISIONS and the obligations it
    creates are recorded permanently. A version-2 database arrives with durable
    promotion roles pointing at model versions the new catalog cannot describe --
    that is a real, countable inheritance and the operator has to be told the
    size of it."""
    engine.create_version_2()[0].close()
    note = applied_migrations(engine.open())[-1].note

    assert f"{len(_REFERENCED_IDS)} model version(s)" in note
    assert "1 tenant(s)" in note
    assert "must be re-registered" in note


def test_an_empty_version_two_database_owes_nothing_and_says_so(engine) -> None:
    """The other branch, and the one that must not be silently identical. With no
    promotion state there is nothing dangling, and the note says that rather than
    reporting a count of zero in the same sentence shape as a real one."""
    engine.create_version_2(seeded=False)[0].close()
    note = applied_migrations(engine.open())[-1].note

    assert "no promotion state in this database referenced a model version" in note


def test_unregistered_references_lists_what_the_catalog_cannot_describe(
    engine,
) -> None:
    """The migration's count, made actionable at runtime and from the SAME column
    list. A migrated database starts with these outstanding by construction, and
    they cannot be re-derived automatically: a champion pointer records an id, not
    a training manifest or an artifact hash."""
    _, tenant = engine.create_version_2()
    engine._opened[-1].close()
    database = engine.open()
    registry = PersistentModelRegistry(database, tenant)

    assert {str(m) for m in registry.unregistered_references()} == _REFERENCED_IDS

    # And registering one removes it -- so the list is a live answer, not a
    # snapshot the migration wrote down.
    registry.register(_model_version(tenant, model_version_id=ModelVersionId(_CHAMPION)))
    assert {str(m) for m in registry.unregistered_references()} == _REFERENCED_IDS - {
        _CHAMPION
    }


def test_unregistered_references_is_scoped_to_its_own_tenant(engine) -> None:
    """"What must I re-register" is a question about one operator. Another
    tenant's dangling references are not this tenant's business, and on SQLite --
    where there is no policy to enforce that -- the `WHERE tenant_id = ?` over
    the derived table is what does."""
    _, tenant = engine.create_version_2()
    engine._opened[-1].close()
    database = engine.open()

    assert PersistentModelRegistry(database, new_id(TenantId)).unregistered_references() == ()
    # Control: the references really are there, for the tenant that owns them.
    assert PersistentModelRegistry(database, tenant).unregistered_references() != ()


# =========================================================================
# 5. THE HAZARD ADR-0055 NAMED: a 2 -> N migration that counts through a
#    live policy sees ZERO rows and succeeds having counted nothing.
# =========================================================================


@pytest.mark.parametrize("table", CORE_TABLES)
def test_the_version_two_fixture_really_is_forced_under_row_security(
    pg_engine, table: str
) -> None:
    """THE CONTROL WITHOUT WHICH THE NEXT THREE TESTS PROVE NOTHING. If the
    fixture's version-2 database were not actually FORCEd, the hazard would be
    absent from it and "the migration counted correctly" would be evidence about
    the fixture. Both bits read straight out of `pg_class`."""
    database, _ = pg_engine.create_version_2()
    assert _rls_bits(database, table) == (True, True)


def test_a_blind_count_under_the_version_two_policy_returns_zero(pg_engine) -> None:
    """THE HAZARD ITSELF, demonstrated before anything is claimed to handle it.

    A migration holds no tenant identity -- it acts for the database, not for an
    operator -- so it reads with no `milexium.tenant_id` in scope. Under the
    version-2 policy that read returns ZERO ROWS, and zero rows is not an error:
    it is an ordinary answer meaning "there was nothing to do". The positive
    control immediately below it is what makes this a demonstration of a trap
    rather than a demonstration of an empty table."""
    database, tenant = pg_engine.create_version_2()

    database.execute_ddl("RESET milexium.tenant_id")
    blind = int(database.query("SELECT COUNT(*) FROM promotion_champions")[0][0])
    database.use_tenant(tenant)
    scoped = int(database.query("SELECT COUNT(*) FROM promotion_champions")[0][0])

    assert blind == 0
    assert scoped == 1, (
        "the control failed: the row is not there, so the zero above is honest "
        "and this test demonstrates nothing"
    )


def test_the_two_to_three_migration_counts_rows_the_policy_would_have_hidden(
    pg_engine,
) -> None:
    """THE SINGLE MOST IMPORTANT TEST IN THIS PACKET.

    The migration runs with no GUC in scope, over tables the test above has just
    shown return zero rows in that state. The number it writes into the permanent
    ledger must be the TRUE one. If the handling in `_migrate_2_to_3` were
    removed, this database's note would confidently record that no model versions
    were referenced -- which is not a wrong log line, it is a false reassurance an
    operator would later act on -- and this assertion is what fails.

    Asserted on the exact count, not on "non-empty": three DISTINCT ids are
    referenced from eight columns across six tables, so a migration that counted
    rows, or looked at one table and stopped, produces a plausible wrong number
    rather than an obviously wrong one."""
    _, tenant = pg_engine.create_version_2()
    pg_engine._opened[-1].close()

    note = applied_migrations(pg_engine.open())[-1].note

    assert f"{len(_REFERENCED_IDS)} model version(s)" in note, (
        "the 2 -> 3 migration counted through a live row-security policy and "
        f"recorded something other than {len(_REFERENCED_IDS)} -- ADR-0055's "
        "named hazard, realised: the migration 'succeeded' having seen nothing"
    )
    assert "0 model version(s)" not in note


def test_the_migration_refuses_rather_than_counting_through_a_live_policy(
    pg_engine, monkeypatch
) -> None:
    """AND IF THE HANDLING IS EVER REMOVED, THE MIGRATION STOPS.

    `suspend_row_level_security` is neutered here -- exactly the edit a future
    change might make by accident -- and the migration must then REFUSE rather
    than proceed to a confident zero. That refusal is the difference between a
    hazard that is handled and a hazard that happens to be handled today: the
    guard reads `pg_class` rather than trusting the suspension to have run,
    because a count of zero is indistinguishable from an empty database and no
    result the migration could inspect would tell it apart."""
    database, _ = pg_engine.create_version_2()
    monkeypatch.setattr(CoreDatabase, "suspend_row_level_security", lambda self: None)

    with pytest.raises(RowSecurityInForceError) as raised:
        _migrate_2_to_3(database, None)
    message = str(raised.value)
    assert "promotion_champions" in message
    assert "zero rows" in message


def test_a_refused_migration_leaves_row_security_in_force(
    pg_engine, monkeypatch
) -> None:
    """A refusal must not be a half-migration, and after this packet that
    includes the boundary. The suspension is DDL inside the migration's own
    transaction, so a migration that raises has it rolled back with everything
    else -- rather than leaving nine tables of operator data unguarded because a
    later step failed."""
    database, _ = pg_engine.create_version_2()
    monkeypatch.setattr(CoreDatabase, "suspend_row_level_security", lambda self: None)

    with pytest.raises(RowSecurityInForceError):
        _migrate_2_to_3(database, None)
    database._conn.rollback()

    for table in CORE_TABLES:
        assert _rls_bits(database, table) == (True, True), (
            f"{table} was left unguarded by a migration that did not complete"
        )


def test_row_security_is_restored_before_the_migration_commits(pg_engine) -> None:
    """THE WINDOW THAT IS NEVER PUBLISHED. `migrate()` commits after each
    migration's stamp, so a step that lowered the boundary and left restoring it
    to the runner's final `apply_row_level_security()` would publish a real,
    committed interval in which nine tables had no policy.

    Proved by driving the migration by hand and reading `pg_class` BEFORE any
    commit: the boundary is already back."""
    database, _ = pg_engine.create_version_2()

    _migrate_2_to_3(database, None)

    for table in ALL_CORE_TABLES:
        assert _rls_bits(database, table) == (True, True), (
            f"{table} is unguarded at the point the migration returned -- the "
            "next commit would publish that state to every other session"
        )
    database._conn.rollback()


def test_the_suspension_is_a_deliberate_no_op_on_sqlite(engine) -> None:
    """SQLite has no row-level security, so there is nothing to suspend and
    nothing that can hide a row from a statement that asked for it. Asserted
    rather than left implicit: `row_security_in_force` returning `()` there is
    what makes the guard silent on the reference engine instead of refusing
    every migration."""
    database = engine.open()
    if engine.kind == "sqlite":
        assert database.row_security_in_force(ALL_CORE_TABLES) == ()
        database.suspend_row_level_security()  # must not raise
    else:
        assert set(database.row_security_in_force(ALL_CORE_TABLES)) == set(
            ALL_CORE_TABLES
        )


# =========================================================================
# 6. The new tables are guarded like every other tenant-scoped table
# =========================================================================


def test_the_acting_role_is_bound_by_row_security(migrated_pg) -> None:
    """ASSERTED BEFORE ANY POLICY RESULT BELOW IS BELIEVED. A superuser or a role
    holding BYPASSRLS skips every policy, and PostgreSQL checks both BEFORE
    ownership and before FORCE -- so a privileged credential would make every
    isolation test in this file pass for the wrong reason (ADR-0006/0046)."""
    database, _ = migrated_pg
    acting, is_super, bypasses = database.query(
        "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles "
        "WHERE rolname = current_user"
    )[0]

    assert is_super is False, f"acting as superuser {acting!r}"
    assert bypasses is False, f"acting role {acting!r} holds BYPASSRLS"


@pytest.mark.parametrize("table", CORE_MODEL_TABLES)
def test_the_acting_role_owns_the_new_tables(migrated_pg, table: str) -> None:
    """FORCE is only meaningful against the OWNER. The migration CREATES these
    tables, so ownership has to be established for FORCE to be what stands in the
    way rather than an ordinary privilege error."""
    database, _ = migrated_pg
    (owner,) = database.query(
        "SELECT c.relowner::regrole::text FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() AND c.relname = ?",
        (table,),
    )[0]
    (acting,) = database.query("SELECT current_user")[0]

    assert owner == acting


@pytest.mark.parametrize("table", CORE_MODEL_TABLES)
def test_the_new_tables_do_not_exist_before_the_migration(pg_engine, table: str) -> None:
    """The strongest form of "not enabled before": on a genuine version-2
    database the relation is not merely unguarded, it is ABSENT from `pg_class`
    entirely -- so "RLS is on afterwards" is evidence about the migration and
    cannot be an artefact of the fixture."""
    database, _ = pg_engine.create_version_2()
    assert _rls_bits(database, table) is None
    assert database.table_exists(table) is False


@pytest.mark.parametrize("table", CORE_MODEL_TABLES)
def test_the_new_tables_have_no_row_security_until_the_rls_file_is_applied(
    pg_engine, table: str
) -> None:
    """THE FALSE-BEFORE / TRUE-AFTER CONTROL, ON THE SAME RELATION. The portable
    DDL is applied on its own -- both `pg_class` bits read FALSE, because
    `core_v0_1.sql` cannot contain a Postgres-only construct and therefore cannot
    enable anything -- and only `core_rls_postgres.sql` turns them on. Without
    this pair, "enabled and forced" would be a claim about PostgreSQL's defaults
    rather than about this packet's RLS file."""
    database = pg_engine.raw()
    for statement in split_statements(CORE_SCHEMA_PATH.read_text(encoding="utf-8")):
        database.execute_ddl(statement)
    database.commit()

    assert _rls_bits(database, table) == (False, False)

    database.apply_row_level_security()
    database.commit()

    assert _rls_bits(database, table) == (True, True)


@pytest.mark.parametrize("table", CORE_MODEL_TABLES)
def test_row_level_security_is_enabled_and_forced_after_migrating(
    migrated_pg, table: str
) -> None:
    """Both bits, from `pg_class`, after a real 2 -> 3 migration.
    `relforcerowsecurity` is the one that actually matters here, because the
    acting role OWNS these tables and a table owner bypasses RLS by default -- an
    ENABLE-only outcome would constrain not one of this repository's own
    connections while looking identical from the application side."""
    database, _ = migrated_pg
    bits = _rls_bits(database, table)
    assert bits is not None, f"{table} does not exist after the migration"
    enabled, forced = bits

    assert enabled is True, f"{table} has no ROW LEVEL SECURITY after the migration"
    assert forced is True, (
        f"{table} has RLS enabled but not FORCED, and the acting role OWNS it -- "
        "a table owner bypasses RLS, so this boundary would not constrain a "
        "single one of this repository's own connections"
    )


@pytest.mark.parametrize("table", CORE_MODEL_TABLES)
def test_exactly_one_tenant_isolation_policy_per_new_table(
    migrated_pg, table: str
) -> None:
    """A table with NO policy denies everything and looks like isolation from the
    outside; several PERMISSIVE policies are OR-ed together and quietly widen it.
    Neither is what was asked for, so the count is asserted, not the presence."""
    database, _ = migrated_pg
    policies = [
        row[0]
        for row in database.query(
            "SELECT policyname FROM pg_policies "
            "WHERE schemaname = current_schema() AND tablename = ?",
            (table,),
        )
    ]
    assert policies == ["tenant_isolation"]


def test_a_cross_tenant_read_of_the_catalog_is_blocked(migrated_pg) -> None:
    """A RAW, UNFILTERED scan -- no `tenant_id` predicate at all -- as a tenant
    the row does not belong to. What is under test is the POLICY, never a Python
    code path: a WHERE clause is application code a refactor can drop, a policy is
    not. Paired with a positive control, so the denial cannot be an empty
    table."""
    database, tenant = migrated_pg
    owner = new_id(TenantId)
    PersistentModelRegistry(database, owner).register(_model_version(owner))

    database.use_tenant(new_id(TenantId))
    assert database.query("SELECT tenant_id FROM core_model_versions") == []

    database.use_tenant(owner)
    assert database.query("SELECT tenant_id FROM core_model_versions") == [
        (str(owner),)
    ]


def test_a_cross_tenant_write_to_the_catalog_is_refused(migrated_pg) -> None:
    """The `WITH CHECK` half, with the Python check deliberately bypassed by
    issuing raw SQL. `PersistentModelRegistry.register` refuses a foreign tenant
    in application code; this proves the DATABASE refuses it too, which is the
    only half that survives a caller who does not go through the class."""
    database, _ = migrated_pg
    victim = new_id(TenantId)
    database.use_tenant(new_id(TenantId))

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        database.execute(
            "INSERT INTO core_model_versions (tenant_id, model_version_id, task, "
            "training_data_manifest_hash, feature_schema_version, "
            "evaluation_window_start, evaluation_window_end, artifact_hash, "
            "registered_at, registered_sequence) "
            "VALUES (?, ?, ?, 'x', 'y', 'a', 'b', 'z', 'c', 1)",
            (str(victim), str(new_id(ModelVersionId)), TASK),
        )
    database._conn.rollback()


def test_a_customer_session_cannot_forge_a_platform_model(migrated_pg) -> None:
    """THE ASYMMETRY, ADVERSARIALLY. ADR-0040's platform tenant makes a row
    readable by EVERY operator, so a forged one is not a private mistake -- it is
    a model every customer of this platform can then resolve and run. The Python
    guard is bypassed here on purpose; what is under test is that the policy's
    `WITH CHECK` omits the platform id."""
    database, _ = migrated_pg
    database.use_tenant(new_id(TenantId))

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        database.execute(
            "INSERT INTO core_model_versions (tenant_id, model_version_id, task, "
            "training_data_manifest_hash, feature_schema_version, "
            "evaluation_window_start, evaluation_window_end, artifact_hash, "
            "registered_at, registered_sequence) "
            "VALUES (?, ?, ?, 'x', 'y', 'a', 'b', 'z', 'c', 1)",
            (str(PLATFORM_TENANT_ID), str(new_id(ModelVersionId)), TASK),
        )
    database._conn.rollback()


def test_a_scoped_tenant_may_read_a_platform_model_through_the_policy(
    migrated_pg,
) -> None:
    """The other half of the asymmetry at the DATABASE layer, not just in the
    store: a raw unfiltered scan as an unrelated customer DOES return the
    platform row. Without this the previous test would be satisfied by a policy
    that simply denied everything."""
    database, _ = migrated_pg
    platform_model = _model_version(PLATFORM_TENANT_ID)
    PersistentModelRegistry(database, PLATFORM_TENANT_ID).register(platform_model)

    database.use_tenant(new_id(TenantId))
    assert database.query(
        "SELECT tenant_id FROM core_model_versions"
    ) == [(str(PLATFORM_TENANT_ID),)]


def test_the_champion_pointer_is_never_readable_across_tenants(migrated_pg) -> None:
    """`core_model_champions` is SYMMETRIC even though it points at rows that may
    be platform-owned. A platform MODEL is shared; the CHOICE to serve it is one
    operator's, and admitting the platform id here would have exposed another
    operator's serving decision."""
    database, _ = migrated_pg
    owner = new_id(TenantId)
    registry = PersistentModelRegistry(database, owner)
    platform_model = _model_version(PLATFORM_TENANT_ID)
    PersistentModelRegistry(database, PLATFORM_TENANT_ID).register(platform_model)
    registry.promote(platform_model.model_version_id)

    database.use_tenant(new_id(TenantId))
    assert database.query("SELECT tenant_id FROM core_model_champions") == []

    database.use_tenant(owner)
    assert database.query("SELECT tenant_id FROM core_model_champions") == [
        (str(owner),)
    ]


def test_force_is_load_bearing_on_the_catalog(migrated_pg) -> None:
    """Lift FORCE, watch the boundary collapse, put it back. Without this the
    suite could not distinguish "the policy holds" from "the owner happens to see
    nothing" -- and since the acting role owns these tables, that distinction is
    the whole question."""
    database, _ = migrated_pg
    owner = new_id(TenantId)
    PersistentModelRegistry(database, owner).register(_model_version(owner))

    database.use_tenant(new_id(TenantId))
    assert database.query("SELECT tenant_id FROM core_model_versions") == []

    database.execute_ddl("ALTER TABLE core_model_versions NO FORCE ROW LEVEL SECURITY")
    database.commit()
    leaked = database.query("SELECT tenant_id FROM core_model_versions")

    database.execute_ddl("ALTER TABLE core_model_versions FORCE ROW LEVEL SECURITY")
    database.commit()

    assert leaked == [(str(owner),)], (
        "lifting FORCE did not expose the other tenant's row, so FORCE is not "
        "what was holding the boundary and this suite proves nothing"
    )
    assert database.query("SELECT tenant_id FROM core_model_versions") == []


def test_a_reset_guc_reads_back_empty_and_still_denies_platform_rows(
    migrated_pg,
) -> None:
    """THE EMPTY-STRING TRAP (ADR-0043), ON THE ONE PROGRAM D TABLE GENUINELY
    EXPOSED TO IT.

    Every other policy in `core_rls_postgres.sql` survives a reset session only
    INCIDENTALLY, because `tenant_id = ''` is false for any real UUIDv7. The
    platform branch has no such accident protecting it: `tenant_id = '<PLATFORM>'`
    is true whatever the GUC says, so without the non-empty conjunct an unset or
    RESET session would read every platform model and the file's advertised
    deny-all default would be false for exactly the rows nobody owns.

    `current_setting(name, true)` returns NULL only when the GUC was NEVER set;
    after `RESET` it returns the EMPTY STRING, which an `IS NOT NULL` guard
    happily accepts -- and a first attempt at ADR-0043's fix written that way did
    NOT work. So the empty string is asserted EXPLICITLY here, before deny-all is
    claimed, and a future "fix" that reintroduces `IS NOT NULL` fails on the line
    below rather than opening the door silently."""
    database, _ = migrated_pg
    owner = new_id(TenantId)
    PersistentModelRegistry(database, owner).register(_model_version(owner))
    platform_model = _model_version(PLATFORM_TENANT_ID)
    PersistentModelRegistry(database, PLATFORM_TENANT_ID).register(platform_model)

    database.use_tenant(owner)
    # Control: with a tenant in scope, BOTH rows are visible through this policy.
    assert len(database.query("SELECT tenant_id FROM core_model_versions")) == 2

    database.execute_ddl("RESET milexium.tenant_id")
    value, is_null = database.query(
        "SELECT current_setting('milexium.tenant_id', true), "
        "current_setting('milexium.tenant_id', true) IS NULL"
    )[0]
    assert value == "" and is_null is False, (
        "a RESET GUC did not read back as the empty string, so the trap this "
        "test exists to pin has changed shape"
    )

    for table in CORE_MODEL_TABLES:
        assert database.query(f"SELECT tenant_id FROM {table}") == [], (  # noqa: S608
            f"{table} returned rows to a session with no tenant in scope"
        )


def test_the_migration_ledger_is_still_readable_without_a_tenant_guc(
    migrated_pg,
) -> None:
    """The deliberate EXCEPTION, re-checked now that a version-3 migration
    depends on it. `core_schema_migrations` carries no policy on purpose: a
    connection has not set `milexium.tenant_id` at the instant it is opened,
    which is exactly when the version is read; under a tenant policy that read
    would return zero rows, zero rows is indistinguishable from "never stamped",
    and the runner would try to migrate an already-migrated database."""
    database, _ = migrated_pg
    database.execute_ddl("RESET milexium.tenant_id")

    assert _rls_bits(database, MIGRATION_LEDGER_TABLE) == (False, False)
    assert database.schema_version() == CURRENT_SCHEMA_VERSION


def test_the_reference_query_covers_every_model_version_column(migrated_pg) -> None:
    """A column missed by `model_reference_query` is a dangling reference that is
    never reported and never re-registered -- silently, because the query would
    still return plenty of others. Checked against the tables' ACTUAL columns
    rather than against the list itself: every column whose name marks it as
    holding a model version must appear in the query's text.

    `incumbent_id` is in that set deliberately. It is the one such column whose
    name does not end in `model_version_id`, and therefore exactly the one a
    tidier suffix-only check would have missed -- which is the failure this test
    is about, reproduced in the test's own predicate."""
    database, _ = migrated_pg
    query = model_reference_query()
    model_columns = ("model_version_id", "champion_id", "challenger_id", "incumbent_id")

    for table in CORE_TABLES:
        for column in database.column_names(table):
            if column.endswith(model_columns):
                assert f"{column} AS model_version_id FROM {table}" in query, (
                    f"{table}.{column} names a model version and is not covered by "
                    "model_reference_query() -- references through it would never "
                    "be reported as unregistered"
                )
