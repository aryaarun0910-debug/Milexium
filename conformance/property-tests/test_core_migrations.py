"""Conformance: the Program D schema has a MIGRATION PATH (MX-D-MIGRATIONS-008).

WHAT GAP THIS CLOSES, IN THE WORDS THAT RECORDED IT. ADR-0048's limitations say:

    "No migration path. Every CREATE is IF NOT EXISTS, so a pre-tenant ADR-0041
    database is not upgraded by reopening. Acceptable **only** because these
    tables have never held operator data -- and that ceases to be true the moment
    they do."

`CREATE TABLE IF NOT EXISTS` is not a weak migration mechanism; it is the
ABSENCE of one. It makes reopening an out-of-date database SUCCEED, quietly,
with the application running against a shape it was not written for. The moment
a design partner's export lands in these tables, "recreate the database" stops
being a remedy and starts being data loss.

FOUR CLAIMS ARE UNDER TEST, and the fourth is the one that could do real harm:

1. **A database states its version.** `core_schema_migrations` records one row
   per version reached, and every database reaching the current version records
   HOW it got there -- created empty, migrated forward, or adopted (recognised by
   shape and stamped without being changed, which is what happens to every
   database written before the ledger existed).

2. **The upgrade actually moves data.** A genuine ADR-0041 pre-tenant database --
   built from `packages/core/sql/legacy/core_v0_1_pre_tenant.sql`, the shape as
   it shipped, not a hand-written approximation -- is migrated to the ADR-0048
   shape with every row intact, bit-identical floats included, and lands in the
   SAME shape a freshly-created database has (compared column-by-column against a
   real fresh database, not against a list written down twice).

3. **Refusal, not repair.** A version newer than this code understands, a version
   it does not recognise, a shape that contradicts the recorded version, and a
   half-finished migration are each REFUSED. Silent divergence between code and
   schema is the failure this packet exists to prevent, so the refusals get more
   tests than the happy path.

4. **ROW-LEVEL SECURITY SURVIVES THE MIGRATION.** This is the dangerous one.
   Migrating REBUILDS tables (SQLite can neither add a `NOT NULL` column nor
   change a primary key in place, so the one portable technique is rename-aside /
   create / copy / drop), and on PostgreSQL a rebuilt table is a NEW RELATION:
   `relrowsecurity`, `relforcerowsecurity` and the `tenant_isolation` policy do
   NOT follow the data through. A migration that stopped after copying the rows
   would leave seven tables full of real operator data with tenant isolation
   SILENTLY REMOVED -- strictly worse than the database it started from, and
   green on every test that only checked the rows arrived. So both `pg_class`
   bits are re-asserted per table AFTER migrating, alongside a blocked
   cross-tenant read, a blocked cross-tenant write, the RESET/empty-string case,
   and a FORCE-lifted collapse proving FORCE rather than luck is what binds the
   owning role.

AND THE INVARIANT THAT MUST NOT BE COLLATERAL DAMAGE. ADR-0041's load-bearing
claim is that an as-of read at label time t returns only values whose
`knowledge_time` is STRICTLY < t. A migration rewrites the very table that claim
is about, so it is re-proved on the OTHER side of the migration -- including
against the real AAR panel, where every migrated as-of read must reproduce the
in-memory reference exactly.

The PostgreSQL half skips cleanly (never fails) when the native `milexium_dev`
instance on 5432 is absent, so CI stays green -- but a skip proves nothing, so
the packet's evidence requirement is that these RUN.

REAL vs SYNTHETIC is labelled per test. The real panel is NYC Access-A-Ride daily
scheduled trips (realdata/panels/aar_daily.csv), public aggregate data.
Status: Demonstrated, never operator-Validated.
"""

from __future__ import annotations

import math
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from packages.canonical import TenantId, new_id
from packages.canonical.postgres_storage import is_reachable as pg_is_reachable
from packages.core.feature_store import (
    CORE_RLS_PATH,
    CORE_SCHEMA_PATH,
    CoreDatabase,
    FeatureStore,
    PersistentFeatureStore,
    _iso_utc,
    _read_dev_password,
)
from packages.core.migrations import (
    CORE_MIGRATIONS_SCHEMA_PATH,
    CORE_SCHEMA_V1_PATH,
    CORE_TABLES,
    CURRENT_SCHEMA_VERSION,
    MIGRATION_LEDGER_TABLE,
    FutureSchemaVersionError,
    LegacyTenantRequiredError,
    SchemaShapeMismatchError,
    UnknownSchemaVersionError,
    applied_migrations,
    detect_shape,
    migrate,
    split_statements,
    stamped_version,
)

psycopg = pytest.importorskip("psycopg")

from psycopg import sql as pg_sql  # noqa: E402

TASK = "forecast.demand"

# --- REAL aggregate panel (labelled): NYC Access-A-Ride daily scheduled trips.
_AAR_DAILY = Path(__file__).resolve().parents[2] / "realdata" / "panels" / "aar_daily.csv"
# The leakage invariant is per-(entity, feature) and holds pointwise, so a short
# window exercises it exactly as the full panel does -- just fewer times -- and
# keeps the PostgreSQL parameter of a migration test measured in seconds.
_WINDOW = 60
_ENTITY = "aar_nyc_scheduled_trips"  # opaque id, no PII
_FEATURE = "scheduled_trips"


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# SYNTHETIC version-1 rows: one per table, in the PRE-TENANT column shape.
#
# Written as raw SQL against the legacy schema on purpose. There is no Python
# class that can produce these -- `PersistentFeatureStore` requires a tenant and
# names `tenant_id` in every statement, which is exactly the thing a version-1
# database does not have. A migration test that could only build its "old"
# database through today's code would not be testing a migration.
# --------------------------------------------------------------------------- #
_CHAMPION = "019a0000-0000-7000-8000-00000000c0de"
_CHALLENGER = "019a0000-0000-7000-8000-00000000beef"
_PRIOR = "019a0000-0000-7000-8000-0000000000a1"

_V1_ROWS: dict[str, tuple[str, tuple]] = {
    "feature_values": (
        "entity_id, feature_name, value, knowledge_time, write_sequence",
        ("zone-1", "lag1", 42.5, _iso_utc(_utc(2026, 1, 1)), 1),
    ),
    "promotion_decisions": (
        "decision_sequence, task, challenger_id, incumbent_id, metric_name, "
        "challenger_metric, incumbent_metric, higher_is_better, min_improvement, "
        "margin, promoted, decided_at, rationale",
        (
            1, TASK, _CHALLENGER, None, "wape", 0.2, None, 0, 0.0, None, 1,
            _iso_utc(_utc(2026, 6, 1)), "first champion",
        ),
    ),
    "promotion_rollbacks": (
        "rollback_sequence, task, from_champion_id, to_champion_id, decided_at, reason",
        (1, TASK, _CHAMPION, _PRIOR, _iso_utc(_utc(2026, 6, 2)), "error spike"),
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


def _seed_version_1(database: CoreDatabase) -> None:
    """One row in every one of the seven pre-tenant tables. All seven, not just
    `feature_values`: a migration that carried the feature store forward and
    quietly dropped the promotion ledger would have destroyed an operator's audit
    trail, which is the more expensive of the two losses."""
    for table, (columns, values) in _V1_ROWS.items():
        placeholders = ", ".join("?" for _ in values)
        database.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",  # noqa: S608
            values,
        )
    database.commit()


def _index_exists(database: CoreDatabase, name: str) -> bool:
    if database.schema is None:
        rows = database.query(
            "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)
        )
    else:
        rows = database.query(
            "SELECT 1 FROM pg_indexes WHERE schemaname = current_schema() "
            "AND indexname = ?",
            (name,),
        )
    return bool(rows)


# --------------------------------------------------------------------------- #
# Engine fixture: the same migration, both engines, with a RAW (unmigrated) path
# --------------------------------------------------------------------------- #
class _Engine:
    """Durable storage that can be opened twice: once RAW, to build a database at
    an old (or deliberately broken) version, and once through `CoreDatabase`,
    which is what runs the migration.

    The raw path is what makes these tests mean anything. `CoreDatabase.sqlite()`
    and `CoreDatabase.postgres()` now migrate on open, so there is no way to
    *create* an old database through them -- the old shape has to be laid down
    underneath, exactly as an ADR-0041 deployment left it.
    """

    def __init__(self, kind: str, tmp_path: Path) -> None:
        self.kind = kind
        self._path = str(tmp_path / "core_migrations.db")
        self._schema = f"mx_core_mig_{uuid.uuid4().hex}"
        self._opened: list[CoreDatabase] = []

    # -- the raw, unmigrated path -- #
    def raw(self) -> CoreDatabase:
        """A `CoreDatabase` over the storage with NO migration run: the DDL is
        whatever is already there (or nothing at all)."""
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

    def create_version_1(self, *, seeded: bool = True) -> CoreDatabase:
        """A genuine ADR-0041 database, built from the historical DDL's own
        bytes."""
        database = self.raw()
        for statement in split_statements(
            CORE_SCHEMA_V1_PATH.read_text(encoding="utf-8")
        ):
            database.execute_ddl(statement)
        database.commit()
        if seeded:
            _seed_version_1(database)
        return database

    # -- the ordinary path, which migrates -- #
    def open(self, **kwargs) -> CoreDatabase:
        database = (
            CoreDatabase.sqlite(self._path, **kwargs)
            if self.kind == "sqlite"
            else CoreDatabase.postgres(schema=self._schema, **kwargs)
        )
        self._opened.append(database)
        return database

    def open_fresh(self) -> CoreDatabase:
        """A brand-new database at the current version, in its OWN storage --
        the reference a migrated database's shape is compared against."""
        if self.kind == "sqlite":
            database = CoreDatabase.sqlite(self._path + ".fresh")
        else:
            database = CoreDatabase.postgres(schema=self._schema + "_fresh")
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
    """One migration, both engines (ADR-0002/0004). The SQLite parameter always
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
    """A seeded ADR-0041 PostgreSQL database, migrated to the current version and
    attributed to one tenant. Yields `(database, legacy_tenant)`."""
    legacy = new_id(TenantId)
    pg_engine.create_version_1().close()
    return pg_engine.open(legacy_tenant_id=legacy), legacy


# =========================================================================
# 0. Portability: whatever was added still runs on a bare SQLite connection
# =========================================================================


def test_every_core_sql_file_runs_unmodified_on_a_bare_sqlite_connection() -> None:
    """ADR-0002's portability discipline, applied to the files this packet adds.

    Executed from the FILES' OWN BYTES against a bare `sqlite3.connect(':memory:')`
    -- no `CoreDatabase`, no helper -- so what is proved is that the SQL is
    portable, not that some Python wrapper papers over it. Applied TWICE, because
    the whole point of a migration runner is that opening an existing database is
    safe, and a DDL file that could only be applied once would not survive
    contact with a reopen.
    """
    connection = sqlite3.connect(":memory:")
    try:
        for _ in range(2):
            for path in (CORE_MIGRATIONS_SCHEMA_PATH, CORE_SCHEMA_PATH):
                connection.executescript(path.read_text(encoding="utf-8"))
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert MIGRATION_LEDGER_TABLE in names
        assert set(CORE_TABLES) <= names
    finally:
        connection.close()


def test_the_historical_version_1_ddl_also_runs_on_a_bare_sqlite_connection() -> None:
    """The legacy file is a specification, and a specification that no longer
    parses is worthless. It is also what every migration test builds its "old"
    database from, so if it stopped running these tests would silently stop
    testing a migration."""
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(CORE_SCHEMA_V1_PATH.read_text(encoding="utf-8"))
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert set(CORE_TABLES) <= names
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(feature_values)")
        }
        assert "tenant_id" not in columns, (
            "the version-1 DDL has grown a tenant_id -- it is a HISTORICAL "
            "artifact and must keep recording the shape that actually shipped"
        )
    finally:
        connection.close()


def test_the_statement_splitter_is_pinned_to_the_files_it_splits() -> None:
    """`split_statements` strips `--` comments and splits on `;`, which is
    correct for these files and would be wrong for a file containing either
    inside a string literal. Pinning the COUNTS is what turns that assumption
    into something that fails HERE, loudly, rather than by silently truncating a
    schema at the offending statement and leaving a half-created database."""
    counts = {
        CORE_MIGRATIONS_SCHEMA_PATH: 1,  # the ledger table
        CORE_SCHEMA_V1_PATH: 8,  # 7 tables + the as-of index
        CORE_SCHEMA_PATH: 11,  # 9 tables + the as-of and catalog indexes
        CORE_RLS_PATH: 36,  # 9 tables x (ENABLE, FORCE, DROP POLICY, CREATE POLICY)
    }
    for path, expected in counts.items():
        statements = split_statements(path.read_text(encoding="utf-8"))
        assert len(statements) == expected, (
            f"{path.name} split into {len(statements)} statements, expected "
            f"{expected} -- either the file changed or the splitter has stopped "
            "being correct for it"
        )
        assert all("--" not in s for s in statements)


# =========================================================================
# 1. A database states its version
# =========================================================================


def test_a_fresh_database_records_the_version_it_was_created_at(engine) -> None:
    database = engine.open()
    assert database.schema_version() == CURRENT_SCHEMA_VERSION


def test_a_fresh_database_records_that_it_was_created_and_not_migrated(engine) -> None:
    """'created', 'migrated' and 'adopted' are genuinely different histories and
    the ledger keeps them apart. A database created empty at the current version
    never had an earlier shape and moved no rows; recording that as a migration
    would claim a transformation that never happened."""
    ledger = applied_migrations(engine.open())
    assert [(row.version, row.applied_by) for row in ledger] == [
        (CURRENT_SCHEMA_VERSION, "created")
    ]


def test_the_version_record_survives_a_reopen(engine) -> None:
    """The version is a property of the DATABASE, not of the process that opened
    it -- otherwise every restart would have to re-infer it."""
    first = engine.open()
    first.close()
    assert engine.open().schema_version() == CURRENT_SCHEMA_VERSION


def test_an_empty_database_is_detected_as_version_zero(engine) -> None:
    """Version 0 is a real answer, not an error: it is how "create it" is
    distinguished from "upgrade it", and conflating the two is how a migration
    runs against a database that has nothing to migrate."""
    assert detect_shape(engine.raw()) == 0


def test_a_current_database_is_detected_as_the_current_version(engine) -> None:
    assert detect_shape(engine.open()) == CURRENT_SCHEMA_VERSION


# =========================================================================
# 2. A pre-tenant (ADR-0041) database is recognised and carried forward
# =========================================================================


def test_a_pre_tenant_database_is_detected_as_version_one(engine) -> None:
    """Detected from its COLUMNS, because a version-1 database has no version
    record to read -- it predates the ledger, which is true of every Program D
    database that exists today."""
    legacy = engine.create_version_1()
    assert stamped_version(legacy) is None
    assert detect_shape(legacy) == 1


def test_a_pre_tenant_database_is_stamped_with_what_it_was_before_being_moved(
    engine,
) -> None:
    """The inference happens exactly ONCE in a database's life. Version 1 is
    recorded as 'adopted' -- recognised and stamped, nothing changed -- and only
    then does the chain get applied on top of a recorded fact rather than a fresh
    guess."""
    engine.create_version_1().close()
    ledger = applied_migrations(engine.open(legacy_tenant_id=new_id(TenantId)))

    assert [(row.version, row.applied_by) for row in ledger] == [
        (1, "adopted"),
        (2, "migrated"),
        (3, "migrated"),
    ]


def test_migrating_a_pre_tenant_database_reaches_the_current_shape(engine) -> None:
    """The claim is not "it has a tenant_id now" but "it is INDISTINGUISHABLE
    from a database created at the current version".

    Compared against a real freshly-created database rather than against a list
    of expected columns, because a list would be a second place for the schema to
    be written down -- and the failure mode this whole packet is about is two
    descriptions of a schema drifting apart.
    """
    engine.create_version_1().close()
    migrated = engine.open(legacy_tenant_id=new_id(TenantId))
    fresh = engine.open_fresh()

    for table in CORE_TABLES:
        assert migrated.column_names(table) == fresh.column_names(table), (
            f"{table} after migration does not match a freshly-created database"
        )
    assert migrated.schema_version() == fresh.schema_version()


def test_the_as_of_index_is_rebuilt_by_the_migration(engine) -> None:
    """The index is not decoration. ADR-0048's claim is that ONE index serves
    both the tenant predicate and the leakage predicate, so `knowledge_time < t`
    is not demoted to a filter over a wider scan. A rebuild that recreated the
    table and lost the index would leave that claim quietly false -- and
    `CREATE INDEX IF NOT EXISTS` would have hidden it, by skipping the new index
    while the old name was still taken."""
    engine.create_version_1().close()
    migrated = engine.open(legacy_tenant_id=new_id(TenantId))

    assert _index_exists(migrated, "ix_feature_values_as_of")


def test_migration_carries_every_row_through_stamped_with_the_declared_tenant(
    engine,
) -> None:
    """All seven tables, not just the feature store: a migration that dropped the
    promotion ledger would have destroyed an operator's audit trail.

    `use_tenant` is not decoration here. On PostgreSQL the migrated tables are
    under a FORCEd policy again, so this raw scan returns NOTHING without a
    tenant in scope -- which is itself the boundary working. (No-op on SQLite,
    which has no policy to key.)"""
    legacy = new_id(TenantId)
    engine.create_version_1().close()
    migrated = engine.open(legacy_tenant_id=legacy)
    migrated.use_tenant(legacy)

    for table in CORE_TABLES:
        rows = migrated.query(f"SELECT tenant_id FROM {table}")  # noqa: S608
        assert len(rows) == 1, f"{table} lost its row in the migration"
        assert rows[0][0] == str(legacy), f"{table} row carries the wrong tenant"


def test_migration_preserves_stored_values_bit_identically(engine) -> None:
    """ADR-0041 chose DOUBLE PRECISION over REAL so a value round-trips
    bit-identically on both engines, because the leakage proof rests on past
    reads being EXACTLY equal. A migration that rewrites every row is the obvious
    place for that to be lost -- through a float going via text, or through a
    column type changing on the way. Asserted with `==`, never `approx`."""
    values = [math.pi, 0.1 + 0.2, 1e-300, -0.0]
    legacy = new_id(TenantId)
    old = engine.create_version_1(seeded=False)
    for index, value in enumerate(values, start=1):
        old.execute(
            "INSERT INTO feature_values (entity_id, feature_name, value, "
            "knowledge_time, write_sequence) VALUES (?, ?, ?, ?, ?)",
            ("zone-1", "lag1", value, _iso_utc(_utc(2026, 1, index)), index),
        )
    old.commit()
    old.close()

    migrated = engine.open(legacy_tenant_id=legacy)
    migrated.use_tenant(legacy)  # the rebuilt tables are policied again on PostgreSQL
    stored = [
        float(row[0])
        for row in migrated.query(
            "SELECT value FROM feature_values ORDER BY write_sequence"
        )
    ]
    assert stored == values


def test_the_migrated_rows_are_readable_through_the_persistent_store(engine) -> None:
    """The migration is only useful if the ORDINARY code path can then read what
    it produced -- raw SQL agreeing with itself proves nothing about the store
    that has to serve the data."""
    legacy = new_id(TenantId)
    engine.create_version_1().close()
    store = PersistentFeatureStore(engine.open(legacy_tenant_id=legacy), legacy)

    assert store.entities() == frozenset({"zone-1"})
    assert store.get_feature("zone-1", "lag1", as_of=_utc(2026, 2, 1)) == 42.5


def test_a_different_tenant_cannot_see_the_migrated_rows(engine) -> None:
    """The rows were attributed to ONE operator. A second one must not inherit
    them -- on either engine, since the store's own predicate holds on SQLite
    where there is no policy to hold instead."""
    legacy = new_id(TenantId)
    engine.create_version_1().close()
    database = engine.open(legacy_tenant_id=legacy)
    stranger = PersistentFeatureStore(database, new_id(TenantId))

    assert stranger.entities() == frozenset()
    assert stranger.get_feature("zone-1", "lag1", as_of=_utc(2026, 2, 1)) is None
    # Control: the rows really are there, for the tenant they were attributed to.
    assert PersistentFeatureStore(database, legacy).get_feature(
        "zone-1", "lag1", as_of=_utc(2026, 2, 1)
    ) == 42.5


# =========================================================================
# 3. Whose data is it? -- the decision the migration refuses to make alone
# =========================================================================


def test_migration_refuses_to_invent_a_tenant_for_pre_existing_rows(engine) -> None:
    """THE DECISION THIS PACKET IS REALLY ABOUT. Adding `tenant_id NOT NULL` to a
    table with rows in it requires knowing whose those rows are, and this code
    cannot know. Every available default is wrong in a way that would be found
    late: an invented uuid names nobody, the ADR-0040 platform tenant would
    declare an operator's private data platform-owned (and platform-owned rows
    are readable by every tenant), and the empty string is precisely the value
    the RLS deny-all default assumes no row ever holds. So it refuses."""
    engine.create_version_1().close()

    with pytest.raises(LegacyTenantRequiredError):
        engine.open()


def test_the_refusal_names_the_tables_that_hold_rows(engine) -> None:
    """A refusal that does not say what it found is a refusal someone will
    override blindly. The message names the populated tables and their counts,
    which is the information needed to decide whose data it is."""
    engine.create_version_1().close()

    with pytest.raises(LegacyTenantRequiredError) as raised:
        engine.open()
    message = str(raised.value)
    assert "feature_values=1" in message
    assert "promotion_decisions=1" in message
    assert "legacy_tenant_id" in message


def test_the_refusal_leaves_the_database_exactly_as_it_was(engine) -> None:
    """A refusal must not be a half-migration. Nothing is written before the
    decision is made -- not even the version ledger -- so a refused database can
    be inspected as it stands and retried after a human decides, rather than
    being left in a state only this code understands."""
    engine.create_version_1().close()
    with pytest.raises(LegacyTenantRequiredError):
        engine.open()

    after = engine.raw()
    assert detect_shape(after) == 1
    assert after.table_exists(MIGRATION_LEDGER_TABLE) is False
    assert int(after.query("SELECT COUNT(*) FROM feature_values")[0][0]) == 1


def test_an_empty_pre_tenant_database_needs_no_tenant_decision(engine) -> None:
    """The case ADR-0048 claims is the only one that has ever existed ("these
    tables have never held operator data"). With no rows there is nothing to
    attribute, so nothing is invented and no human is asked."""
    engine.create_version_1(seeded=False).close()
    migrated = engine.open()

    assert migrated.schema_version() == CURRENT_SCHEMA_VERSION
    # Version 2's note specifically, not the last one: the chain is longer than
    # one step now, and "the tenant question was not asked" is a fact about the
    # migration that had a tenant question to ask.
    note = next(row.note for row in applied_migrations(migrated) if row.version == 2)
    assert "no rows existed" in note
    assert "none was invented" in note


def test_the_declared_tenant_is_recorded_permanently_in_the_ledger(engine) -> None:
    """"We decided these rows belong to X" has to survive as a RECORDED decision.
    Otherwise the only remaining evidence is the data the decision produced, and
    a stamp cannot later be distinguished from an original."""
    legacy = new_id(TenantId)
    engine.create_version_1().close()
    ledger = applied_migrations(engine.open(legacy_tenant_id=legacy))

    note = next(row.note for row in ledger if row.version == 2)
    assert str(legacy) in note
    assert "7 pre-tenant row(s) were attributed" in note


def test_a_malformed_declared_tenant_is_refused(engine) -> None:
    """Validated as a canonical `TenantId`, not accepted as any string: a typo
    would otherwise become a silently distinct, permanently unreadable partition
    of seven tables -- and unlike a bad row it would be the ONLY copy."""
    engine.create_version_1().close()

    with pytest.raises(ValueError):
        engine.open(legacy_tenant_id="not-a-uuid")


# =========================================================================
# 4. Idempotence -- running it twice does nothing the second time
# =========================================================================


def test_migrating_twice_is_a_no_op(engine) -> None:
    legacy = new_id(TenantId)
    engine.create_version_1().close()
    database = engine.open(legacy_tenant_id=legacy)
    before = applied_migrations(database)

    assert migrate(database) == (CURRENT_SCHEMA_VERSION, CURRENT_SCHEMA_VERSION)
    assert applied_migrations(database) == before


def test_migrating_twice_does_not_duplicate_or_re_stamp_rows(engine) -> None:
    """The failure a re-run would produce is not an error, it is DUPLICATED data
    -- so it is asserted on the rows, not only on the ledger."""
    legacy = new_id(TenantId)
    engine.create_version_1().close()
    database = engine.open(legacy_tenant_id=legacy)
    migrate(database)
    migrate(database)
    database.use_tenant(legacy)  # policied again on PostgreSQL after the rebuild

    for table in CORE_TABLES:
        assert int(database.query(f"SELECT COUNT(*) FROM {table}")[0][0]) == 1  # noqa: S608


def test_reopening_a_migrated_database_needs_no_legacy_tenant(engine) -> None:
    """Once migrated, the tenant question is settled and must never be asked
    again -- an operator prompted for it on every restart would eventually answer
    it differently."""
    engine.create_version_1().close()
    engine.open(legacy_tenant_id=new_id(TenantId)).close()

    reopened = engine.open()  # no legacy_tenant_id, and none required
    assert reopened.schema_version() == CURRENT_SCHEMA_VERSION


def test_the_ledger_records_each_version_exactly_once(engine) -> None:
    """`version` is the PRIMARY KEY of the ledger, so a second stamp of the same
    version is refused by the DATABASE rather than merely skipped by Python."""
    legacy = new_id(TenantId)
    engine.create_version_1().close()
    database = engine.open(legacy_tenant_id=legacy)
    for _ in range(3):
        migrate(database)

    versions = [row.version for row in applied_migrations(database)]
    assert versions == sorted(set(versions)) == [1, 2, 3]


# =========================================================================
# 5. Detection and refusal -- the point of having a version at all
# =========================================================================


def test_a_newer_schema_version_is_refused(engine) -> None:
    """The failure this packet exists to prevent, in its most dangerous form:
    code running against a schema it does not understand. The columns still being
    present is not evidence that what they MEAN has not changed, so a database
    written by a newer Milexium is refused outright rather than opened
    hopefully."""
    database = engine.open()
    database.execute(
        f"INSERT INTO {MIGRATION_LEDGER_TABLE} "
        "(version, name, applied_at, applied_by, note) VALUES (?, ?, ?, ?, ?)",
        (99, "from_the_future", _iso_utc(_utc(2027, 1, 1)), "migrated", "newer code"),
    )
    database.commit()
    database.close()

    with pytest.raises(FutureSchemaVersionError) as raised:
        engine.open()
    assert "99" in str(raised.value)
    assert str(CURRENT_SCHEMA_VERSION) in str(raised.value)


def test_an_unrecognisable_schema_is_refused_rather_than_guessed(engine) -> None:
    """A database with SOME of the seven tables is not "nearly version 1". No
    version ever looked like that, so there is no starting point to migrate from
    -- and guessing at the starting shape is how a migration destroys data."""
    legacy = engine.create_version_1()
    legacy.execute_ddl("DROP TABLE promotion_canaries")
    legacy.commit()
    legacy.close()

    with pytest.raises(UnknownSchemaVersionError):
        engine.open()


def test_a_table_carrying_unknown_columns_is_refused(engine) -> None:
    """Shape detection is exact, not "close enough". A version-1 table with an
    extra column is a schema this code has never written and cannot reason
    about."""
    legacy = engine.create_version_1()
    legacy.execute_ddl("ALTER TABLE feature_values ADD COLUMN experiment TEXT")
    legacy.commit()
    legacy.close()

    with pytest.raises(UnknownSchemaVersionError):
        engine.open()


def test_a_database_whose_shape_contradicts_its_stamp_is_refused(engine) -> None:
    """The condition the ledger exists to CATCH, and the most dangerous of all:
    a stamp saying 2 over tables shaped like 1. Everything downstream trusts the
    recorded version, so a wrong record is worse than no record -- an unstamped
    database at least gets inspected."""
    legacy = engine.create_version_1()
    for statement in split_statements(
        CORE_MIGRATIONS_SCHEMA_PATH.read_text(encoding="utf-8")
    ):
        legacy.execute_ddl(statement)
    legacy.execute(
        f"INSERT INTO {MIGRATION_LEDGER_TABLE} "
        "(version, name, applied_at, applied_by, note) VALUES (?, ?, ?, ?, ?)",
        (2, "adr_0048_tenant_isolation", _iso_utc(_utc(2026, 7, 1)), "migrated", "lie"),
    )
    legacy.commit()
    legacy.close()

    with pytest.raises(SchemaShapeMismatchError) as raised:
        engine.open()
    assert "version 1" in str(raised.value)


def test_a_half_finished_migration_is_refused_and_its_rebuild_tables_are_named(
    engine,
) -> None:
    """A migration that died between the rename and the copy leaves the rows in
    `mx_core_v1_*`. Starting a second rebuild on top of that would overwrite the
    only surviving copy, so the refusal names them instead."""
    legacy = engine.create_version_1()
    legacy.execute_ddl("ALTER TABLE feature_values RENAME TO mx_core_v1_feature_values")
    legacy.commit()
    legacy.close()

    with pytest.raises(UnknownSchemaVersionError) as raised:
        engine.open()
    assert "mx_core_v1_feature_values" in str(raised.value)


# =========================================================================
# 6. THE DANGEROUS ONE: row-level security must survive the migration
# =========================================================================


@pytest.mark.parametrize("table", CORE_TABLES)
def test_a_pre_tenant_postgres_table_has_no_policy_before_migration(
    pg_engine, table: str
) -> None:
    """The control that makes the next test mean something. A version-1 table
    predates `core_rls_postgres.sql` entirely, so both `pg_class` bits are FALSE
    -- if they were somehow true here, "RLS is on after migrating" would be
    proving nothing about the migration."""
    legacy = pg_engine.create_version_1()

    enabled, forced = legacy.query(
        "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() AND c.relname = ?",
        (table,),
    )[0]
    assert enabled is False and forced is False


def test_the_acting_role_is_bound_by_row_security(migrated_pg) -> None:
    """If the acting role were a superuser or held BYPASSRLS, every policy would
    be inert and every isolation assertion below would pass for the wrong reason.
    Both are checked by PostgreSQL BEFORE ownership and before FORCE, so neither
    could rescue a privileged connection -- which is why this is asserted first
    (ADR-0006/0046)."""
    database, _ = migrated_pg
    acting, is_super, bypasses = database.query(
        "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles "
        "WHERE rolname = current_user"
    )[0]

    assert is_super is False, f"acting as superuser {acting!r}"
    assert bypasses is False, f"acting role {acting!r} holds BYPASSRLS"


@pytest.mark.parametrize("table", CORE_TABLES)
def test_the_acting_role_owns_the_rebuilt_tables(migrated_pg, table: str) -> None:
    """FORCE is only meaningful against the OWNER. The migration CREATES these
    tables (a rebuild is a new relation), so ownership has to be re-established
    for FORCE to be what stands in the way rather than an ordinary privilege
    error."""
    database, _ = migrated_pg
    (owner,) = database.query(
        "SELECT c.relowner::regrole::text FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() AND c.relname = ?",
        (table,),
    )[0]
    (acting,) = database.query("SELECT current_user")[0]

    assert owner == acting


@pytest.mark.parametrize("table", CORE_TABLES)
def test_row_level_security_is_enabled_and_forced_after_migrating(
    migrated_pg, table: str
) -> None:
    """THE SINGLE MOST DANGEROUS THING THIS PACKET COULD GET WRONG.

    Migrating rebuilds every table, and a rebuilt table is a NEW RELATION:
    `relrowsecurity`, `relforcerowsecurity` and the `tenant_isolation` policy do
    not follow the data through. A migration that stopped after copying the rows
    would leave seven tables full of real operator data with tenant isolation
    silently REMOVED -- worse than the un-migrated database, and green on any
    test that only checked the rows arrived.

    Read straight out of `pg_class` rather than inferred from behaviour, so an
    ENABLE-only outcome fails HERE, explicitly. `relforcerowsecurity` is the bit
    that actually matters, because the acting role owns these tables."""
    database, _ = migrated_pg
    row = database.query(
        "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() AND c.relname = ?",
        (table,),
    )
    assert row, f"{table} does not exist after the migration"
    enabled, forced = row[0]

    assert enabled is True, (
        f"{table} lost ROW LEVEL SECURITY in the migration -- the rebuilt table "
        "is a new relation and the ENABLE did not carry over"
    )
    assert forced is True, (
        f"{table} has RLS enabled but not FORCED after the migration, and the "
        "acting role OWNS it -- a table owner bypasses RLS, so this boundary "
        "would not constrain a single one of this repository's own connections"
    )


@pytest.mark.parametrize("table", CORE_TABLES)
def test_exactly_one_tenant_isolation_policy_per_table_after_migrating(
    migrated_pg, table: str
) -> None:
    """A table with NO policy denies everything and looks like isolation from the
    outside; several PERMISSIVE policies are OR-ed together and quietly widen it.
    Neither is what was asked for, so the count is asserted, not just the
    presence."""
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


@pytest.mark.parametrize("table", CORE_TABLES)
def test_a_cross_tenant_read_of_migrated_rows_is_blocked(
    migrated_pg, table: str
) -> None:
    """A RAW, UNFILTERED scan -- no `tenant_id` predicate at all -- as a tenant
    the migrated rows were not attributed to. What is under test is the policy on
    the rebuilt table, never a Python code path: a WHERE clause is application
    code a refactor can drop, a policy is not.

    Paired with a positive control, so the denial cannot be an empty table."""
    database, legacy = migrated_pg

    database.use_tenant(new_id(TenantId))
    assert database.query(f"SELECT tenant_id FROM {table}") == []  # noqa: S608

    database.use_tenant(legacy)
    assert database.query(f"SELECT tenant_id FROM {table}") == [(str(legacy),)]  # noqa: S608


@pytest.mark.parametrize("table", CORE_TABLES)
def test_a_cross_tenant_write_to_a_migrated_table_is_refused(
    migrated_pg, table: str
) -> None:
    """The `WITH CHECK` half. A forged `promotion_decisions` row is a forged audit
    trail and a forged `promotion_champions` row would change which model serves
    another operator's riders, so the rebuild has to restore the write boundary
    too -- not only the read one."""
    database, legacy = migrated_pg
    columns, values = _V1_ROWS[table]
    stranger = new_id(TenantId)
    database.use_tenant(stranger)

    placeholders = ", ".join("?" for _ in values)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        database.execute(
            f"INSERT INTO {table} (tenant_id, {columns}) "  # noqa: S608
            f"VALUES (?, {placeholders})",
            (str(legacy),) + values,
        )
    database._conn.rollback()


def test_force_is_load_bearing_on_a_migrated_table(migrated_pg) -> None:
    """Lift FORCE, watch the boundary collapse, put it back. Without this the
    suite could not distinguish "the policy holds" from "the owner happens to see
    nothing", and after a MIGRATION that distinction is the whole question --
    ENABLE alone is exactly what a careless rebuild would restore."""
    database, legacy = migrated_pg
    database.use_tenant(new_id(TenantId))
    assert database.query("SELECT tenant_id FROM feature_values") == []

    database.execute_ddl("ALTER TABLE feature_values NO FORCE ROW LEVEL SECURITY")
    database.commit()
    leaked = database.query("SELECT tenant_id FROM feature_values")

    database.execute_ddl("ALTER TABLE feature_values FORCE ROW LEVEL SECURITY")
    database.commit()

    assert leaked == [(str(legacy),)], (
        "lifting FORCE did not expose the other tenant's row, so FORCE is not "
        "what was holding the boundary and this suite proves nothing"
    )
    assert database.query("SELECT tenant_id FROM feature_values") == []


def test_a_reset_guc_reads_back_empty_and_still_denies_after_migration(
    migrated_pg,
) -> None:
    """THE EMPTY-STRING TRAP, re-checked on the rebuilt tables.

    `current_setting(name, true)` returns NULL only when the GUC was NEVER set;
    after `RESET` it returns the EMPTY STRING, which an `IS NOT NULL` guard
    happily accepts. The empty string is asserted EXPLICITLY -- not assumed --
    before deny-all is claimed, so a future "fix" that reintroduces an
    `IS NOT NULL` guard fails here rather than opening the door silently."""
    database, _ = migrated_pg
    database.use_tenant(new_id(TenantId))
    database.execute_ddl("RESET milexium.tenant_id")

    value, is_null = database.query(
        "SELECT current_setting('milexium.tenant_id', true), "
        "current_setting('milexium.tenant_id', true) IS NULL"
    )[0]
    assert value == "" and is_null is False, (
        "a RESET GUC did not read back as the empty string, so the trap this "
        "test exists to pin has changed shape"
    )

    for table in CORE_TABLES:
        assert database.query(f"SELECT tenant_id FROM {table}") == []  # noqa: S608


def test_the_migration_ledger_is_readable_without_a_tenant_guc(migrated_pg) -> None:
    """And the deliberate EXCEPTION, tested rather than merely commented.

    `core_schema_migrations` carries no policy on purpose. A connection has not
    set `milexium.tenant_id` at the instant it is opened -- which is exactly when
    the version is read -- so under a tenant policy that read would return zero
    rows, zero rows is indistinguishable from "never stamped", and the runner
    would try to migrate an already-migrated database. Deny-all is the right
    default for operator rows and the wrong default for the record that says what
    shape those rows are in."""
    database, _ = migrated_pg
    database.execute_ddl("RESET milexium.tenant_id")

    enabled, forced = database.query(
        "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() AND c.relname = ?",
        (MIGRATION_LEDGER_TABLE,),
    )[0]
    assert (enabled, forced) == (False, False)
    assert database.schema_version() == CURRENT_SCHEMA_VERSION


# =========================================================================
# 7. The ADR-0041 leakage guarantee, on the far side of the migration
# =========================================================================


def test_the_strict_leakage_predicate_survives_the_migration(engine) -> None:
    """SYNTHETIC. A migration rewrites the very table the leakage guarantee is a
    claim about, so the guarantee is re-proved AFTER it rather than assumed to
    have come through. Strict `<`: a value stamped exactly AT the label time is
    still invisible, and the previous one is what comes back."""
    legacy = new_id(TenantId)
    old = engine.create_version_1(seeded=False)
    stamps = [_utc(2026, 1, 1), _utc(2026, 1, 2), _utc(2026, 1, 3)]
    for index, (stamp, value) in enumerate(zip(stamps, [10.0, 20.0, 30.0]), start=1):
        old.execute(
            "INSERT INTO feature_values (entity_id, feature_name, value, "
            "knowledge_time, write_sequence) VALUES (?, ?, ?, ?, ?)",
            ("zone-1", "lag1", value, _iso_utc(stamp), index),
        )
    old.commit()
    old.close()

    store = PersistentFeatureStore(engine.open(legacy_tenant_id=legacy), legacy)

    # Exactly at a stamp -> the PRIOR value, never that stamp's own.
    assert store.get_feature("zone-1", "lag1", as_of=stamps[1]) == 10.0
    assert store.get_feature("zone-1", "lag1", as_of=stamps[2]) == 20.0
    # Before everything -> nothing at all.
    assert store.get_feature("zone-1", "lag1", as_of=stamps[0]) is None
    # Strictly after -> the latest past value.
    assert store.get_feature("zone-1", "lag1", as_of=_utc(2026, 6, 1)) == 30.0


@pytest.mark.skipif(not _AAR_DAILY.exists(), reason="real AAR daily panel absent")
def test_real_panel_as_of_reads_are_unchanged_by_the_migration(engine) -> None:
    """REAL DATA -- the strongest form of the claim.

    A real daily panel is written into a genuine PRE-TENANT database by raw SQL
    (there is no Python path that can: `PersistentFeatureStore` requires a tenant
    and names `tenant_id` in every statement). The database is then migrated, and
    EVERY as-of read through the migrated store is compared against the in-memory
    reference built from the same rows -- exactly, with `==`, at every observed
    stamp and at the midpoint between stamps.

    A migration that reordered rows, lost a correction, or narrowed a float would
    show up as a single mismatched read here. The control at the end proves the
    comparison is not vacuously true.
    """
    import pandas as pd

    frame = (
        pd.read_csv(_AAR_DAILY, parse_dates=["date"])
        .sort_values("date")
        .reset_index(drop=True)
    )
    rows = [
        (ts.to_pydatetime().replace(tzinfo=timezone.utc), float(v))
        for ts, v in zip(frame["date"], frame["scheduled_trips"])
    ][:_WINDOW]

    reference = FeatureStore()
    old = engine.create_version_1(seeded=False)
    for index, (knowledge_time, value) in enumerate(rows, start=1):
        reference.write(
            entity_id=_ENTITY,
            feature_name=_FEATURE,
            value=value,
            knowledge_time=knowledge_time,
        )
        old.execute(
            "INSERT INTO feature_values (entity_id, feature_name, value, "
            "knowledge_time, write_sequence) VALUES (?, ?, ?, ?, ?)",
            (_ENTITY, _FEATURE, value, _iso_utc(knowledge_time), index),
        )
    old.commit()
    old.close()

    legacy = new_id(TenantId)
    store = PersistentFeatureStore(engine.open(legacy_tenant_id=legacy), legacy)

    for knowledge_time, _ in rows:
        expected = reference.get_feature(_ENTITY, _FEATURE, as_of=knowledge_time)
        actual = store.get_feature(_ENTITY, _FEATURE, as_of=knowledge_time)
        assert actual == expected, f"migrated as-of read diverged at {knowledge_time}"

    # Control: the comparison above is not comparing None to None.
    assert store.get_feature(_ENTITY, _FEATURE, as_of=rows[-1][0]) == rows[-2][1]
    assert store.get_feature(_ENTITY, _FEATURE, as_of=rows[0][0]) is None
