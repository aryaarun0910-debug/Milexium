"""Ordered, versioned schema migrations for the Program D (core) tables.

WHAT THIS CLOSES
----------------
ADR-0048 recorded the gap in its own limitations, and named the exact condition
under which it stops being tolerable:

    "No migration path. Every CREATE is IF NOT EXISTS, so a pre-tenant ADR-0041
    database is not upgraded by reopening. Acceptable **only** because these
    tables have never held operator data -- and that ceases to be true the moment
    they do."

A design partner's export is that moment. `CREATE TABLE IF NOT EXISTS` is not a
weak migration mechanism, it is the ABSENCE of one: it makes reopening an
out-of-date database SUCCEED, quietly, with application code running against a
shape it was not written for. The failure that produces is not a clean crash --
`PersistentFeatureStore` would issue `WHERE tenant_id = ?` against a table with
no `tenant_id` column and get an error on SQLite, while a half-updated database
could satisfy some statements and not others. Silent divergence between code and
schema is the failure mode this module exists to prevent, so its central
behaviour is REFUSAL, not repair.

THE THREE PARTS
---------------
1. **A version record.** `core_schema_migrations` (packages/core/sql/
   core_schema_migrations.sql) -- one row per version the database has reached.
   A database that cannot say what version it is at cannot be migrated safely,
   because every decision a migration makes is a decision about where it is
   starting FROM.

2. **Ordered, idempotent migrations.** `_MIGRATIONS` below, applied in version
   order, each one moving the database from version N-1 to N. Running `migrate()`
   on an already-current database does nothing at all -- not "re-applies
   harmlessly", but takes no action, because the ledger says there is nothing to
   do. The migration that exists today is 1 -> 2: the ADR-0041 pre-tenant shape
   to the ADR-0048 tenant-scoped one.

3. **Detection and refusal.** A version NEWER than this code understands, a
   version that is not a version this code knows, or a database whose actual
   SHAPE contradicts its recorded version, all raise. None of them proceed.

WHY A DATABASE MUST ALSO BE ABLE TO SAY ITS VERSION WITHOUT THE LEDGER
----------------------------------------------------------------------
Every Program D database that exists today predates the ledger, so the first
thing this module has to do is classify a database that has no version record at
all. It does that STRUCTURALLY, from the columns actually present:

    no core tables at all           -> version 0 (empty; create at current)
    the seven tables, no tenant_id  -> version 1 (ADR-0041)
    the seven tables, with tenant_id-> version 2 (ADR-0048)
    anything else                   -> UNKNOWN -> refuse

and then STAMPS what it found, so the guess happens exactly once in a database's
life and every later open reads a recorded fact instead of re-inferring one.
Where a version IS recorded, the shape is still checked against it: a ledger
saying 2 over a table shaped like 1 is a half-finished migration or a hand-edited
ledger, and both must stop the process rather than be run against.

THE TENANT OF PRE-EXISTING ROWS -- A DECISION, MADE EXPLICITLY
---------------------------------------------------------------
Migration 1 -> 2 adds `tenant_id TEXT NOT NULL` to seven tables. Rows that
already exist must get a value, and this code CANNOT KNOW WHICH. Every available
shortcut is wrong in a way that would be discovered late:

  * inventing a UUID gives operator data a tenant that names nobody, and the
    rows become unreadable by every real tenant while still counting against
    every scan;
  * reusing the ADR-0040 platform tenant would declare an operator's private
    feature values and promotion history to be PLATFORM-OWNED -- and the platform
    tenant's models are readable by every tenant;
  * the empty string is the one value that would defeat the RLS policies in
    `core_rls_postgres.sql`, whose deny-all default rests on no row's tenant_id
    ever being `''` (see the empty-string trap in
    packages/canonical/sql/rls_postgres.sql).

So `migrate()` REFUSES. If any of the seven tables holds a row, the caller must
pass `legacy_tenant_id=` naming whose data it is; if they all hold none -- which
is the only case ADR-0048 claims to have ever existed -- no attribution is
needed and none is invented. The declared tenant is validated as a canonical
`TenantId` (a typo would otherwise become a permanently unreadable partition)
and is WRITTEN INTO THE LEDGER, so "we decided these rows belong to X" survives
as a recorded decision rather than as an inference from the data it produced.

PORTABILITY (ADR-0002) AND ROW-LEVEL SECURITY (ADR-0018/0048)
--------------------------------------------------------------
The migration runs on SQLite and PostgreSQL 17 from one code path. It cannot use
`ALTER TABLE ... ADD COLUMN ... NOT NULL` (SQLite rejects it without a default)
and it cannot alter a primary key on SQLite at all, so it uses the one technique
both engines support: **rebuild** -- rename the old table aside, create the new
one from the current DDL, `INSERT ... SELECT` the rows through with the declared
tenant, drop the old table.

That rebuild has a consequence that is the single most dangerous thing in this
module: on PostgreSQL the new table is a NEW RELATION, and a new relation has no
row-level security and no policy. A migration that stopped there would leave
seven tables holding real operator data with tenant isolation SILENTLY REMOVED --
strictly worse than the un-migrated database it started from, and passing every
test that only checks the data arrived. So `migrate()` re-applies
`core_rls_postgres.sql` at the end of every PostgreSQL run, and
conformance/property-tests/test_core_migrations.py asserts `relrowsecurity` AND
`relforcerowsecurity` out of `pg_class` for all seven tables afterwards, plus a
cross-tenant read that must still come back empty.

Order matters and is load-bearing: the rows are copied BEFORE the policies are
installed. Reversed, the `WITH CHECK` half would reject every inserted row (the
GUC is unset during a migration) and the migration would move nothing while
appearing to succeed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from packages.canonical.ids import TenantId

if TYPE_CHECKING:  # pragma: no cover - typing only
    from packages.core.feature_store import CoreDatabase

_SQL_DIR = Path(__file__).parent / "sql"

#: The version ledger's own DDL. Applied before anything else -- the place a
#: version is recorded must exist before a version can be read.
CORE_MIGRATIONS_SCHEMA_PATH = _SQL_DIR / "core_schema_migrations.sql"

#: The CURRENT shape. A database created empty is created from this file
#: directly and stamped at `CURRENT_SCHEMA_VERSION`; it does not walk the
#: migration chain to get there.
CORE_SCHEMA_V2_PATH = _SQL_DIR / "core_v0_1.sql"

#: Schema version 1 (ADR-0041), kept only to specify what version 1 IS and to
#: let the conformance suite build a genuine one. Never applied to a new
#: database by anything in packages/core.
CORE_SCHEMA_V1_PATH = _SQL_DIR / "legacy" / "core_v0_1_pre_tenant.sql"

MIGRATION_LEDGER_TABLE = "core_schema_migrations"

#: The version this code writes and understands. Opening a database stamped
#: higher than this is refused: newer code may have changed the meaning of a
#: column this code still reads, and "it looked fine" is not a safety argument.
CURRENT_SCHEMA_VERSION = 2

#: Every version this code can recognise. A stamped version outside this set is
#: refused even if it is lower than CURRENT -- an unknown 1.5 is not "close
#: enough to 1".
KNOWN_SCHEMA_VERSIONS = (1, 2)

#: The seven Program D tables, in the order core_v0_1.sql declares them.
CORE_TABLES = (
    "feature_values",
    "promotion_decisions",
    "promotion_rollbacks",
    "promotion_champions",
    "promotion_champion_history",
    "promotion_challengers",
    "promotion_canaries",
)

#: Schema version 1's columns, per table, exactly as ADR-0041 shipped them.
#: This is the DETECTOR: a database whose seven tables carry precisely these
#: columns is a version-1 database, and one that carries nearly-these is not
#: recognised at all.
_V1_COLUMNS: dict[str, tuple[str, ...]] = {
    "feature_values": (
        "entity_id",
        "feature_name",
        "value",
        "knowledge_time",
        "write_sequence",
    ),
    "promotion_decisions": (
        "decision_sequence",
        "task",
        "challenger_id",
        "incumbent_id",
        "metric_name",
        "challenger_metric",
        "incumbent_metric",
        "higher_is_better",
        "min_improvement",
        "margin",
        "promoted",
        "decided_at",
        "rationale",
    ),
    "promotion_rollbacks": (
        "rollback_sequence",
        "task",
        "from_champion_id",
        "to_champion_id",
        "decided_at",
        "reason",
    ),
    "promotion_champions": ("task", "champion_id"),
    "promotion_champion_history": ("task", "stack_position", "champion_id"),
    "promotion_challengers": ("task", "model_version_id", "enrol_sequence"),
    "promotion_canaries": ("task", "model_version_id", "traffic_fraction"),
}

#: Schema version 2 is version 1 plus `tenant_id` on every table -- derived
#: rather than restated, because that IS what migration 2 does. Writing the
#: version-2 column lists out by hand would create a second place for them to be
#: wrong.
_V2_COLUMNS: dict[str, tuple[str, ...]] = {
    table: ("tenant_id",) + columns for table, columns in _V1_COLUMNS.items()
}

_SHAPES: dict[int, dict[str, tuple[str, ...]]] = {1: _V1_COLUMNS, 2: _V2_COLUMNS}

#: Indexes that must be dropped before the table they sit on is rebuilt. Both
#: engines keep an index attached to a RENAMED table under its original NAME, so
#: re-creating it on the new table collides -- on SQLite with "index
#: ix_feature_values_as_of already exists", on PostgreSQL with a duplicate
#: relation. `IF NOT EXISTS` on the CREATE would hide the collision by SKIPPING
#: the new index, leaving the as-of read unindexed and the ADR-0048 claim that
#: one index serves both the tenant and the leakage predicate quietly false.
_V1_INDEXES = ("ix_feature_values_as_of",)

#: Prefix for the transient tables a rebuild renames the originals to. Visible
#: on purpose: if a migration dies half-way, these are where the data still is,
#: and the refusal that follows names them.
_REBUILD_PREFIX = "mx_core_v1_"

#: The packet/ADR each version corresponds to. Version numbers order; names
#: identify, and a ledger row quoting `adr_0048_tenant_isolation` is far more
#: use to whoever reads it in a year than one quoting `2`.
_VERSION_NAMES = {1: "adr_0041_core_persistence", 2: "adr_0048_tenant_isolation"}


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #
class CoreSchemaError(RuntimeError):
    """Base for every refusal to operate on a database of uncertain shape.

    A `RuntimeError` rather than a `ValueError`: nothing about the CALL is
    wrong: the database is in a state this code will not act on."""


class FutureSchemaVersionError(CoreSchemaError):
    """The database is stamped at a version NEWER than this code understands.

    Proceeding would mean running today's statements against tomorrow's schema
    on the strength of the columns happening to still be there. A newer version
    may have re-interpreted a column this code still reads with the old meaning,
    and no amount of "it worked" would reveal that."""


class UnknownSchemaVersionError(CoreSchemaError):
    """The database's version cannot be established.

    Either it is stamped with a version this code has never heard of, or it is
    unstamped and its shape matches no known version -- a partially-created
    database, a half-finished migration, or a schema Program D does not own."""


class SchemaShapeMismatchError(CoreSchemaError):
    """The recorded version and the actual shape disagree.

    This is the exact condition the ledger exists to catch. It means a migration
    stopped part-way, or a ledger row was written by hand, and it is far more
    dangerous than an unstamped database because everything downstream would
    otherwise TRUST the stamp."""


class LegacyTenantRequiredError(CoreSchemaError):
    """Pre-tenant rows exist and nobody has said whose they are.

    Raised INSTEAD of choosing a tenant. See the module docstring for why every
    available default is wrong; the correct response is for a human to state the
    tenant, which is then recorded permanently in the migration ledger."""


# --------------------------------------------------------------------------- #
# SQL text handling
# --------------------------------------------------------------------------- #
def split_statements(sql_text: str) -> tuple[str, ...]:
    """Split a `.sql` file into individual statements.

    Needed because the two engines disagree about multi-statement execution:
    `sqlite3.Connection.execute` accepts exactly one statement (only
    `executescript` takes many, and it COMMITs first, which would silently break
    a migration into pieces), while psycopg accepts many. Splitting for BOTH
    engines gives one code path and means the splitter is exercised against
    PostgreSQL too rather than only against the reference engine.

    Deliberately simple: strips `--` comments and splits on `;`. That is correct
    for the files in packages/core/sql/**, none of which contains a semicolon or
    a `--` inside a string literal, and it is checked rather than assumed --
    conformance/property-tests/test_core_migrations.py pins the statement COUNT
    of every file this is used on, so a future file that breaks the assumption
    fails there instead of silently truncating a schema.
    """
    lines: list[str] = []
    for line in sql_text.splitlines():
        comment = line.find("--")
        if comment >= 0:
            line = line[:comment]
        if line.strip():
            lines.append(line)
    body = "\n".join(lines)
    return tuple(
        statement.strip() for statement in body.split(";") if statement.strip()
    )


def _run_script(database: "CoreDatabase", path: Path) -> None:
    for statement in split_statements(path.read_text(encoding="utf-8")):
        database.execute_ddl(statement)


def _now_iso() -> str:
    # Deferred import: packages.core.feature_store imports THIS module (it runs
    # migrations when a database is opened), so a module-level import here would
    # be a cycle. `_iso_utc` is imported rather than re-implemented because a
    # second copy of the fixed-width canonical form is a second thing to get
    # wrong.
    from packages.core.feature_store import _iso_utc

    return _iso_utc(datetime.now(timezone.utc))


# --------------------------------------------------------------------------- #
# Version detection
# --------------------------------------------------------------------------- #
def _ensure_ledger(database: "CoreDatabase") -> None:
    """Create `core_schema_migrations` if it is absent. Idempotent, and safe on a
    database of ANY version -- it touches none of the Program D tables."""
    _run_script(database, CORE_MIGRATIONS_SCHEMA_PATH)


def stamped_version(database: "CoreDatabase") -> int | None:
    """The version the database SAYS it is at, or `None` if it has never been
    stamped. `MAX(version)`, because the ledger keeps one row per version
    reached rather than a single mutable row."""
    if not database.table_exists(MIGRATION_LEDGER_TABLE):
        return None
    rows = database.query(f"SELECT MAX(version) FROM {MIGRATION_LEDGER_TABLE}")
    value = rows[0][0] if rows else None
    return None if value is None else int(value)


def detect_shape(database: "CoreDatabase") -> int | None:
    """The version the database's ACTUAL COLUMNS correspond to.

    Returns 0 for a database with none of the seven tables, 1 or 2 for a
    recognised shape, and `None` when the shape matches no known version --
    which includes the dangerous middle cases: some tables present and some
    absent, or a table carrying columns from two different versions.

    Compares column NAMES only. It does not compare types, primary keys, CHECK
    constraints or indexes: those have no portable introspection that works
    identically on SQLite and PostgreSQL, and for the versions that exist the
    column sets already separate them (version 2 differs from version 1 by a
    column on every table). Named as a limitation rather than implied -- a
    database whose columns match version 2 but whose PRIMARY KEY does not would
    be adopted as version 2.
    """
    present = {table: database.table_exists(table) for table in CORE_TABLES}
    if not any(present.values()):
        return 0
    if not all(present.values()):
        return None  # partially created: no version ever looked like this
    actual = {table: frozenset(database.column_names(table)) for table in CORE_TABLES}
    for version, expected in _SHAPES.items():
        if all(actual[table] == frozenset(columns) for table, columns in expected.items()):
            return version
    return None


def _leftover_rebuild_tables(database: "CoreDatabase") -> tuple[str, ...]:
    """Tables a previously-crashed rebuild left behind. Their presence means the
    data may still be in them, so a fresh rebuild must not start on top."""
    return tuple(
        f"{_REBUILD_PREFIX}{table}"
        for table in CORE_TABLES
        if database.table_exists(f"{_REBUILD_PREFIX}{table}")
    )


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #
def _stamp(
    database: "CoreDatabase", version: int, applied_by: str, note: str, name: str
) -> None:
    database.execute(
        f"INSERT INTO {MIGRATION_LEDGER_TABLE} "
        "(version, name, applied_at, applied_by, note) VALUES (?, ?, ?, ?, ?)",
        (version, name, _now_iso(), applied_by, note),
    )


@dataclass(frozen=True)
class AppliedMigration:
    """One row of the ledger, as read back."""

    version: int
    name: str
    applied_at: str
    applied_by: str
    note: str


def applied_migrations(database: "CoreDatabase") -> tuple[AppliedMigration, ...]:
    """The ledger, in version order -- the audit view of how this database got
    to the shape it has."""
    if not database.table_exists(MIGRATION_LEDGER_TABLE):
        return ()
    return tuple(
        AppliedMigration(int(v), n, a, b, note)
        for v, n, a, b, note in database.query(
            f"SELECT version, name, applied_at, applied_by, note "
            f"FROM {MIGRATION_LEDGER_TABLE} ORDER BY version"
        )
    )


# --------------------------------------------------------------------------- #
# The migrations themselves
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Migration:
    """One step forward.

    `version` is the version the database is AT once `apply` has run. `apply`
    returns the ledger note describing what it did, because the interesting part
    of a migration is the decisions it had to make, not the fact that it ran.

    `precheck` is every refusal this migration can raise, factored out so it can
    run BEFORE the runner writes anything at all -- including before the version
    ledger is created. A migration that discovers half-way through that it needs
    a human decision leaves a database in a state only this code understands;
    one that discovers it first leaves the database exactly as it found it."""

    version: int
    name: str
    apply: Callable[["CoreDatabase", TenantId | None], str]
    # Returns whatever its own `apply` finds useful (the 1 -> 2 pair share row
    # counts); the runner only cares that it either raises or does not.
    precheck: Callable[["CoreDatabase", TenantId | None], object]


def _precheck_1_to_2(
    database: "CoreDatabase", legacy_tenant_id: TenantId | None
) -> dict[str, int]:
    """Everything that can stop the 1 -> 2 migration, checked before it starts.

    Returns the per-table row counts so `_migrate_1_to_2` does not recount --
    but it is safe to call twice, and IS called twice (once by the runner before
    any write, once by the migration itself, so calling the migration directly is
    no less guarded than going through `migrate`)."""
    leftovers = _leftover_rebuild_tables(database)
    if leftovers:
        raise CoreSchemaError(
            "this database already contains rebuild tables from an earlier, "
            f"unfinished migration: {', '.join(leftovers)}. Their rows have NOT "
            "been discarded -- resolve them by hand (copy anything needed into "
            "the live tables, then drop them) before migrating again. Starting a "
            "second rebuild on top of them would overwrite the only surviving "
            "copy of that data."
        )

    counts = {
        table: int(database.query(f"SELECT COUNT(*) FROM {table}")[0][0])
        for table in CORE_TABLES
    }
    total = sum(counts.values())

    # THE DECISION THIS MIGRATION REFUSES TO MAKE ON ITS OWN.
    if total and legacy_tenant_id is None:
        populated = ", ".join(f"{table}={n}" for table, n in counts.items() if n)
        raise LegacyTenantRequiredError(
            "this pre-tenant (schema version 1) database already holds rows "
            f"({populated}), and schema version 2 requires every row to name the "
            "tenant it belongs to. This code will NOT choose one: an invented "
            "uuid makes the rows unreadable by every real operator, the ADR-0040 "
            "platform tenant would declare an operator's private feature values "
            "and promotion history platform-owned (and platform-owned rows are "
            "readable by every tenant), and the empty string is precisely the "
            "value the row-level-security policies' deny-all default assumes no "
            "row ever holds. Re-open with legacy_tenant_id=<the operator whose "
            "data this is>; the value you pass is recorded permanently in "
            f"{MIGRATION_LEDGER_TABLE}."
        )

    # Validated HERE, in the precheck, so a typo is refused before anything is
    # written rather than after six of the seven tables have been rebuilt.
    if legacy_tenant_id is not None:
        TenantId(str(legacy_tenant_id))
    return counts


def _migrate_1_to_2(database: "CoreDatabase", legacy_tenant_id: TenantId | None) -> str:
    """ADR-0041's pre-tenant shape -> ADR-0048's tenant-scoped shape.

    Rebuild, not `ALTER`: SQLite will not add a `NOT NULL` column without a
    default and cannot change a primary key at all, and every one of the seven
    tables needs `tenant_id` to LEAD its primary key (ADR-0048: under RLS the
    `MAX()` that assigns each sequence sees only the acting tenant's rows, so a
    global counter would collide). Rename aside, create from the current DDL,
    copy through, drop.
    """
    counts = _precheck_1_to_2(database, legacy_tenant_id)
    total = sum(counts.values())
    tenant = None if legacy_tenant_id is None else str(TenantId(str(legacy_tenant_id)))

    for table in CORE_TABLES:
        database.execute_ddl(
            f"ALTER TABLE {table} RENAME TO {_REBUILD_PREFIX}{table}"
        )
    # Before the new tables are created, not after: an index follows its table
    # through a rename but keeps its NAME, so the name is still taken.
    for index in _V1_INDEXES:
        database.execute_ddl(f"DROP INDEX IF EXISTS {index}")

    _run_script(database, CORE_SCHEMA_V2_PATH)

    for table in CORE_TABLES:
        if not counts[table]:
            continue
        columns = ", ".join(_V1_COLUMNS[table])
        database.execute(
            f"INSERT INTO {table} (tenant_id, {columns}) "
            f"SELECT ?, {columns} FROM {_REBUILD_PREFIX}{table}",
            (tenant,),
        )

    for table in CORE_TABLES:
        database.execute_ddl(f"DROP TABLE {_REBUILD_PREFIX}{table}")

    if not total:
        return (
            "no rows existed in any of the seven Program D tables, so no tenant "
            "attribution was required and none was invented"
        )
    return (
        f"{total} pre-tenant row(s) were attributed to tenant {tenant}, declared "
        "by the caller via legacy_tenant_id ("
        + ", ".join(f"{table}={n}" for table, n in counts.items() if n)
        + ")"
    )


_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=2,
        name=_VERSION_NAMES[2],
        apply=_migrate_1_to_2,
        precheck=_precheck_1_to_2,
    ),
)


# --------------------------------------------------------------------------- #
# The entry point
# --------------------------------------------------------------------------- #
def migrate(
    database: "CoreDatabase", *, legacy_tenant_id: TenantId | None = None
) -> tuple[int, int]:
    """Bring `database` to `CURRENT_SCHEMA_VERSION`, or refuse.

    Returns `(version_before, version_after)`. `(2, 2)` means nothing was done,
    which is the normal case for every open after the first.

    `legacy_tenant_id` is required ONLY when migrating a version-1 database that
    already holds rows -- see `_migrate_1_to_2`. Passing it when it is not needed
    is harmless and changes nothing; omitting it when it IS needed raises
    `LegacyTenantRequiredError` before anything has been modified.

    On PostgreSQL, `core_rls_postgres.sql` is applied at the END of every call,
    migration or no migration. Unconditionally, because a rebuilt table is a new
    relation with no policy and no FORCE, and re-applying is idempotent (the RLS
    file drops each policy before creating it) -- so the cheap, always-correct
    option is to never let a call return with a Program D table unguarded.

    EVERY REFUSAL HAPPENS BEFORE ANYTHING IS WRITTEN, including before the
    version ledger itself is created. A database this function refuses is left
    byte-identical to how it was found -- so a refusal can be investigated
    against the actual database, and a caller that retries after fixing nothing
    gets the same refusal rather than a different one.
    """
    stamped = stamped_version(database)
    shape = detect_shape(database)

    if stamped is None and shape is None:
        leftovers = _leftover_rebuild_tables(database)
        hint = (
            " Rebuild tables from an unfinished migration are present "
            f"({', '.join(leftovers)}), so this looks like a migration that "
            "stopped part-way; the rows are still in them."
            if leftovers
            else ""
        )
        raise UnknownSchemaVersionError(
            "this database carries no Program D schema-version record and its "
            "shape matches no version this code knows (expected either the seven "
            "ADR-0041 tables without tenant_id, or the seven ADR-0048 tables with "
            "it, or none of them at all)." + hint + " Refusing to migrate: "
            "guessing at the starting shape is how a migration destroys data."
        )
    if stamped is not None:
        if stamped > CURRENT_SCHEMA_VERSION:
            raise FutureSchemaVersionError(
                f"this database is at Program D schema version {stamped}, but this "
                f"code understands at most version {CURRENT_SCHEMA_VERSION}. It was "
                "written by a newer Milexium. Refusing to open it: a newer version "
                "may have changed what a column this code still reads MEANS, and "
                "the columns being present is not evidence that it has not. "
                "Upgrade the code, do not downgrade the database."
            )
        if stamped not in KNOWN_SCHEMA_VERSIONS:
            raise UnknownSchemaVersionError(
                f"this database records Program D schema version {stamped}, which is "
                f"not a version this code knows (known: "
                f"{', '.join(str(v) for v in KNOWN_SCHEMA_VERSIONS)}). Refusing to "
                "open it rather than treating an unrecognised version as the "
                "nearest one it resembles."
            )
        if shape != stamped:
            described = "no version this code knows" if shape is None else f"version {shape}"
            raise SchemaShapeMismatchError(
                f"this database records Program D schema version {stamped} but its "
                f"tables are shaped like {described}. The version record and the "
                "schema have diverged -- a migration that stopped part-way, or a "
                "ledger row written by hand. Refusing to act: everything downstream "
                "trusts the recorded version, so a wrong record is more dangerous "
                "than no record at all."
            )

    creating = stamped is None and shape == 0
    version_before = 0 if creating else (stamped if stamped is not None else shape)
    assert version_before is not None  # every None-shape case raised above

    # Every pending migration gets to refuse BEFORE the first write. This is why
    # a database that needs a human decision (see `_precheck_1_to_2`) is left
    # byte-identical rather than stamped-then-abandoned.
    if not creating:
        for migration in _MIGRATIONS:
            if migration.version > version_before:
                migration.precheck(database, legacy_tenant_id)

    # Past every refusal: from here the database is modified.
    _ensure_ledger(database)
    if creating:
        _run_script(database, CORE_SCHEMA_V2_PATH)
        _stamp(
            database,
            CURRENT_SCHEMA_VERSION,
            "created",
            "database created empty at the current schema version; no earlier "
            "shape ever existed and no rows were moved",
            _VERSION_NAMES[CURRENT_SCHEMA_VERSION],
        )
        started_at = CURRENT_SCHEMA_VERSION
        database.commit()
    elif stamped is None:
        # Recognised, but never stamped -- which every Program D database written
        # before this module existed is. Record what it is ONCE, so no later open
        # has to infer it again, then let the chain below carry it forward from a
        # recorded fact rather than a fresh guess.
        _stamp(
            database,
            shape,
            "adopted",
            "database predates the schema-version ledger; its shape was "
            f"recognised as version {shape} and stamped without being changed",
            _VERSION_NAMES[shape],
        )
        started_at = shape
        database.commit()
    else:
        started_at = stamped

    for migration in _MIGRATIONS:
        if migration.version <= started_at:
            continue
        note = migration.apply(database, legacy_tenant_id)
        _stamp(database, migration.version, "migrated", note, migration.name)
        database.commit()

    # Always, on PostgreSQL: a rebuilt table is a new relation and a new relation
    # has no policy. This is the line that keeps a migration from silently
    # removing tenant isolation from tables that now hold operator data.
    database.apply_row_level_security()
    database.commit()
    return (version_before, CURRENT_SCHEMA_VERSION)
