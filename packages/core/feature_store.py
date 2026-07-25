"""Leakage-safe point-in-time feature store (Program D contract, v0.1 slice).

Program D's adaptive memory needs a place to read features "as they were known
at time t" so a forecast is only ever built from information available strictly
before its label time -- the same mechanical point-in-time discipline
`realdata/leakage_audit.py` proves for the training pipelines, here made a
first-class runtime store rather than a per-pipeline convention.

The one invariant that matters:

    get_features(entity_id, as_of=t) returns, per feature, the latest value
    whose knowledge/valid time is STRICTLY < t.

A value stamped exactly at t -- or later -- is never visible. That strict `<`
is the leakage guarantee: a reading at label time t cannot see a fact that only
became known at t or in its future, so a feature built from this store cannot
secretly depend on the future (the corruption test in
`conformance/property-tests/test_feature_store.py` proves it mechanically, the
way `realdata/leakage_audit.py` does for the AAR / NTD panels).

`FeatureStore` is the IN-MEMORY reference implementation, matching the pattern
`packages/canonical/events.py`'s `HashChainAppender` and
`packages/core/model_registry.py`'s `ModelRegistry` already established.
`PersistentFeatureStore` (below) is the same contract over a real database --
ADR-0034 shipped the reference backend only, so a design partner's feature
values did not survive a process restart, which is the gap a pilot hits first.

Privacy: entity ids are opaque strings only -- never a raw name, mirroring
`ServiceRequest.rider_ref`'s tokenization discipline (blueprint 10 data
minimization). The store neither parses nor validates the id's structure; it is
the caller's job to have tokenized it upstream.

Persistence design notes
------------------------
`CoreDatabase` (below) owns the connection to a database carrying
`packages/core/sql/core_v0_1.sql`, and is shared by this module and
`packages/core/promotion.py`. It is defined HERE rather than in a
`packages/core/persistence.py` because Program D's persistence slice owns
exactly these two modules; a dedicated plumbing module is the natural home once
a third persistent Program D store exists.

`packages/canonical` ships the same contract as TWO classes
(`SqliteCanonicalStore` / `PostgresCanonicalStore`) because its PostgreSQL half
carries row-level security the SQLite half cannot have (ADR-0018), so the two
genuinely diverge. Program D's store logic instead exists ONCE over an
engine-parametrised `CoreDatabase`, opened by `CoreDatabase.sqlite(...)` or
`CoreDatabase.postgres(...)`: the per-engine difference is confined to the
DB-API placeholder, how a connection is opened, and (PostgreSQL only) applying
`core_rls_postgres.sql` and setting the session GUC. Duplicating the store logic
to mirror the canonical file layout would buy nothing and would let the two
copies drift. What the canonical pattern actually asserts -- one contract, two
engines, proven by `[sqlite]`/`[postgres]`-parametrised conformance
(`conformance/property-tests/test_core_persistence.py`) -- is preserved, and
contract drift between engines becomes structurally impossible rather than
merely tested for.

TENANT SCOPING (MX-D-TENANT-ISOLATION-006, closing an ADR-0041 limitation).
`PersistentFeatureStore` is constructed FOR ONE TENANT and cannot be constructed
without one -- `tenant_id` is a required constructor argument, not an optional
per-call parameter, so there is no way to reach the table unscoped. Every
statement it issues names `tenant_id`, and on PostgreSQL every operation also
sets the `milexium.tenant_id` GUC that
`packages/core/sql/core_rls_postgres.sql`'s policies key on, so the boundary is
enforced by the DATABASE and the WHERE clause is the second of two independent
boundaries rather than the only one. See
`conformance/property-tests/test_core_tenant_isolation.py`, which proves the
policy with the WHERE clause deliberately deleted.

The IN-MEMORY `FeatureStore` above stays tenant-free ON PURPOSE. It is a
reference implementation held in one process by one caller, with no shared
table for a second operator's rows to sit in -- the entire gap being closed here
is that a shared TABLE existed. Giving it a tenant parameter would add a
dimension it cannot enforce (a Python dict key is not a boundary) and would
break the method-for-method signature parity `test_core_persistence.py` checks
structurally. The tenant therefore enters through the constructor, which that
parity check already excludes, and the two classes stay honestly comparable.

The leakage guarantee survives persistence because the strict `<` is evaluated
by the DATABASE: `knowledge_time < :as_of` is a SQL predicate over fixed-width
canonical ISO-8601 UTC text (`_iso_utc`), whose lexicographic order is its
chronological order. A future row is never fetched and then filtered in Python
-- it is never fetched at all. `conformance/property-tests/test_core_persistence.py`
re-runs the ADR-0034 mechanical future-corruption discipline through this path.
Tenant scoping does not weaken it: `tenant_id = ?` is an ADDITIONAL conjunct on
the same predicate, so a read returns the INTERSECTION of "my tenant's rows" and
"strictly in the past" and neither conjunct can rescue a row the other excludes.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from packages.canonical.ids import TenantId
from packages.canonical.time import UtcDateTime, _require_utc

# One-directional: this module imports the migration runner, and the runner
# imports `_iso_utc` back from here only INSIDE a function (see
# `packages/core/migrations._now_iso`), so there is no import cycle.
from packages.core.migrations import ALL_CORE_TABLES, migrate, split_statements

CORE_SCHEMA_PATH = Path(__file__).parent / "sql" / "core_v0_1.sql"
# Postgres-only: RLS is not in the portable subset, so it is a separate file
# applied only by `CoreDatabase.postgres`, exactly as packages/canonical splits
# schema_v0_1.sql from rls_postgres.sql.
CORE_RLS_PATH = Path(__file__).parent / "sql" / "core_rls_postgres.sql"

# ADR-0006: the local dev role is `milexium_dev`, never the Postgres superuser,
# and its password is read from the user profile at connection time -- never
# hardcoded, never committed, never logged. Same file, same rule as
# packages/canonical/postgres_storage.py.
_DEFAULT_PASSWORD_FILE = Path.home() / ".milexium_pg_app_password.txt"


def _read_dev_password() -> str:
    return _DEFAULT_PASSWORD_FILE.read_text(encoding="utf-8").strip()


def _iso_utc(value: datetime) -> str:
    """A UTC instant as FIXED-WIDTH ISO-8601 text: the storage form of every
    timestamp in `core_v0_1.sql`.

    Fixed width is the load-bearing part. `datetime.isoformat()` omits the
    fractional part when microseconds are zero, so `...T00:00:00+00:00` and
    `...T00:00:00.500000+00:00` are not reliably comparable as strings across
    every possible pair. Padding microseconds to six digits makes lexicographic
    order identical to chronological order, which is what lets the leakage
    guarantee's strict `knowledge_time < as_of` be a SQL predicate -- evaluated
    identically by SQLite and PostgreSQL -- rather than a Python filter applied
    after an unconstrained fetch.
    """
    v = value.astimezone(timezone.utc)
    return (
        f"{v.year:04d}-{v.month:02d}-{v.day:02d}T"
        f"{v.hour:02d}:{v.minute:02d}:{v.second:02d}.{v.microsecond:06d}+00:00"
    )


class FeatureValue(BaseModel):
    """One (entity, feature) observation stamped with the time it became known.

    `knowledge_time` is a transaction/valid time in the sense of
    `packages/canonical/time.py`: the instant this value first became available
    to be read. An as-of read at label time t admits this value only when
    `knowledge_time < t` (strictly).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: str
    feature_name: str
    value: float
    knowledge_time: UtcDateTime


class FeatureStore:
    """In-memory reference point-in-time feature store.

    Values are appended, never mutated -- a correction is a new `FeatureValue`
    with a later (or equal) `knowledge_time`, never an in-place edit, mirroring
    the append-only discipline of the canonical event log. Reads are resolved
    as-of a label time with the strict past-only rule above.
    """

    def __init__(self) -> None:
        # (entity_id, feature_name) -> observations in append order.
        self._series: dict[tuple[str, str], list[FeatureValue]] = {}

    def write(
        self,
        *,
        entity_id: str,
        feature_name: str,
        value: float,
        knowledge_time: datetime,
    ) -> FeatureValue:
        """Append one observation. `knowledge_time` must be timezone-aware UTC
        (the same rule every canonical timestamp obeys)."""
        _require_utc(knowledge_time)
        observation = FeatureValue(
            entity_id=entity_id,
            feature_name=feature_name,
            value=float(value),
            knowledge_time=knowledge_time,
        )
        self._series.setdefault((entity_id, feature_name), []).append(observation)
        return observation

    def _feature_names(self, entity_id: str) -> tuple[str, ...]:
        return tuple(
            name for (eid, name) in self._series if eid == entity_id
        )

    def get_feature(
        self, entity_id: str, feature_name: str, *, as_of: datetime
    ) -> float | None:
        """The latest value for one feature whose `knowledge_time` is STRICTLY
        earlier than `as_of`, or `None` if no such value exists.

        Ties on `knowledge_time` resolve to the last-written value (a correction
        recorded at the same instant supersedes what it corrects), matching the
        canonical bitemporal "latest recorded version wins" rule.
        """
        _require_utc(as_of)
        series = self._series.get((entity_id, feature_name))
        if not series:
            return None
        latest: FeatureValue | None = None
        for observation in series:  # append order, so ties keep the last write
            if observation.knowledge_time < as_of and (
                latest is None or observation.knowledge_time >= latest.knowledge_time
            ):
                latest = observation
        return latest.value if latest is not None else None

    def get_features(self, entity_id: str, *, as_of: datetime) -> dict[str, float]:
        """Every feature known for `entity_id` as-of `as_of`, each resolved by
        the strict past-only rule of `get_feature`. Features with no value
        strictly before `as_of` are omitted."""
        _require_utc(as_of)
        result: dict[str, float] = {}
        for feature_name in self._feature_names(entity_id):
            value = self.get_feature(entity_id, feature_name, as_of=as_of)
            if value is not None:
                result[feature_name] = value
        return result

    def history(self, entity_id: str, feature_name: str) -> tuple[FeatureValue, ...]:
        """Every recorded observation for one (entity, feature), in append
        order -- the audit view, distinct from the as-of read."""
        return tuple(self._series.get((entity_id, feature_name), ()))

    def entities(self) -> frozenset[str]:
        return frozenset(entity_id for entity_id, _ in self._series)


# --------------------------------------------------------------------------- #
# Persistence: one database adapter, two engines
# --------------------------------------------------------------------------- #
class CoreDatabase:
    """A connection to a database carrying `packages/core/sql/core_v0_1.sql`.

    The single point at which SQLite and PostgreSQL differ for Program D: the
    DB-API placeholder (`?` vs `%s`), how the DDL is applied, (PostgreSQL only)
    the disposable per-instance schema, and (PostgreSQL only) row-level
    security. Every statement above this class is written once, with `?`
    placeholders, and runs on both engines.

    PostgreSQL instances get a dedicated schema (`mx_core_<uuid>` by default),
    created at construction and torn down by `drop_schema()` -- the same
    test-isolation strategy `packages/canonical/postgres_storage.py` uses,
    because a real server is a shared persistent process rather than SQLite's
    disposable `:memory:` default.

    OPENING A DATABASE RUNS ITS MIGRATIONS (MX-D-MIGRATIONS-008), and that is
    what makes reopening a named schema -- or an on-disk SQLite file -- safe
    rather than merely non-erroring. It used to rest on the DDL's own `CREATE
    ... IF NOT EXISTS`, which ADR-0048 recorded honestly as the absence of a
    migration path: a database created before `tenant_id` existed was NOT
    upgraded by reopening it, the old tables simply stayed as they were, and the
    code then ran against a shape it was not written for. `packages/core/
    migrations.py` replaces that with a recorded version, an ordered upgrade
    from it, and -- the part `IF NOT EXISTS` could never provide -- a REFUSAL to
    open a database whose version this code does not understand.

    TENANT ISOLATION IS ASYMMETRIC BETWEEN THE ENGINES, and that asymmetry is
    stated rather than papered over. On PostgreSQL, `postgres()` applies
    `core_rls_postgres.sql` after the portable DDL and `use_tenant()` sets the
    `milexium.tenant_id` GUC its policies key on, so the tenant boundary is
    enforced by the database. SQLite has no row-level security to apply, so
    there the boundary is the stores' `tenant_id = ?` predicates alone --
    `use_tenant()` is a deliberate no-op. This is the same split ADR-0018 made
    for the canonical stores: SQLite is the demo/reference engine, PostgreSQL is
    the production target, and only the production target is claimed to enforce
    isolation below the application.
    """

    def __init__(
        self,
        connection: object,
        *,
        placeholder: str,
        schema: str | None = None,
    ) -> None:
        self._conn = connection
        self._placeholder = placeholder
        self._schema = schema

    # -- construction ------------------------------------------------------- #
    @classmethod
    def sqlite(
        cls, path: str = ":memory:", *, legacy_tenant_id: TenantId | None = None
    ) -> "CoreDatabase":
        """Open (or create) a SQLite database and bring it to the current schema
        version. A path other than `:memory:` is what makes the store outlive the
        process -- and is therefore the only case where a database can be found
        at an OLDER version than this code writes.

        `legacy_tenant_id` is forwarded to `packages/core/migrations.migrate` and
        is needed only when an ADR-0041 pre-tenant database that already holds
        rows is being upgraded; see that module for why the migration refuses to
        pick a tenant for those rows itself.
        """
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        database = cls(connection, placeholder="?")
        try:
            migrate(database, legacy_tenant_id=legacy_tenant_id)
        except BaseException:
            # A refused database must not leave an open handle behind: the
            # caller never received the object, so nobody else can close it, and
            # on Windows an open SQLite handle blocks the file being inspected or
            # replaced -- which is exactly what a refusal invites you to do.
            connection.close()
            raise
        return database

    @classmethod
    def postgres(
        cls,
        *,
        host: str = "localhost",
        port: int = 5432,
        dbname: str = "milexium_dev",
        user: str = "milexium_dev",
        password: str | None = None,
        schema: str | None = None,
        legacy_tenant_id: TenantId | None = None,
    ) -> "CoreDatabase":
        """Open the natively installed PostgreSQL 17 dev instance (ADR-0006) and
        bring the schema to the current version with the SAME migration code path
        SQLite uses -- the portability claim (ADR-0002) is that neither the DDL
        nor the upgrade needs a per-engine edit -- then apply the Postgres-only
        `core_rls_postgres.sql` on top.

        Both are applied INSIDE the same schema (search_path is already set), so
        unqualified table names resolve to the tables just created, and both are
        written to be re-appliable because this classmethod is how a named schema
        is REOPENED.

        The RLS file is applied by `migrate()` at the END of its run rather than
        here, and that ordering is load-bearing: migrating rebuilds tables, a
        rebuilt table is a NEW relation with no policy and no FORCE, and the rows
        must be copied through before any `WITH CHECK` clause exists to reject
        them."""
        import psycopg
        from psycopg import sql as pg_sql

        if password is None:
            password = _read_dev_password()
        connection = psycopg.connect(
            host=host, port=port, dbname=dbname, user=user, password=password
        )
        schema_name = schema or f"mx_core_{uuid.uuid4().hex}"
        ident = pg_sql.Identifier(schema_name)
        with connection.cursor() as cur:
            cur.execute(pg_sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(ident))
            cur.execute(pg_sql.SQL("SET search_path TO {}").format(ident))
        database = cls(connection, placeholder="%s", schema=schema_name)
        try:
            migrate(database, legacy_tenant_id=legacy_tenant_id)
        except BaseException:
            # Roll back first: a refusal raised mid-statement would otherwise
            # leave the connection in PostgreSQL's aborted-transaction state, and
            # closing it there discards the work silently rather than visibly.
            try:
                connection.rollback()
            finally:
                connection.close()
            raise
        return database

    # -- tenant scoping ----------------------------------------------------- #
    def use_tenant(self, tenant_id: object) -> None:
        """Point the session's RLS key (`milexium.tenant_id`) at `tenant_id`.

        Called by both Program D stores before EVERY read and write, so no
        operation ever depends on a value some earlier operation happened to
        leave behind, and two stores sharing one connection for two different
        tenants cannot read each other's rows by accident of ordering. Session
        scope (`is_local=false`) because these stores commit per operation.

        A NO-OP ON SQLITE, deliberately: there is no row-level security to key,
        so the stores' own `tenant_id = ?` predicates are the whole boundary
        there. Same GUC name as `packages/canonical/postgres_storage.py`, so a
        connection carrying both contracts cannot be scoped to two different
        tenants at once.

        `set_config` takes the value as a BOUND PARAMETER -- never
        string-interpolated into SQL.
        """
        if self._placeholder == "?":
            return
        self._conn.execute(
            "SELECT set_config('milexium.tenant_id', %s, false)", (str(tenant_id),)
        )

    # -- schema version ----------------------------------------------------- #
    def apply_row_level_security(self) -> None:
        """Apply `core_rls_postgres.sql`. A NO-OP ON SQLITE, which has no
        row-level security to apply.

        Called by `packages/core/migrations.migrate` at the end of EVERY run,
        not only when a migration ran. Migrating rebuilds tables (SQLite cannot
        add a `NOT NULL` column or change a primary key in place), and a rebuilt
        table is a new relation: `relrowsecurity`, `relforcerowsecurity` and the
        `tenant_isolation` policy do not survive it. A migration that forgot this
        would leave seven tables holding real operator data with tenant isolation
        SILENTLY REMOVED -- worse than the database it started from, and green on
        every test that only checks the rows arrived."""
        if self._placeholder == "?":
            return
        for statement in split_statements(CORE_RLS_PATH.read_text(encoding="utf-8")):
            self._conn.execute(statement)

    def row_security_in_force(self, tables: tuple[str, ...]) -> tuple[str, ...]:
        """Which of `tables` would filter this session's reads through a
        row-level-security policy, in `tables` order.

        The evidence a migration needs BEFORE it believes a row count, and the
        reason it cannot get that evidence from the rows themselves: under a
        policy with no `milexium.tenant_id` in scope a `SELECT` returns zero
        rows, and zero rows is a perfectly ordinary answer meaning "empty". The
        table's catalog state is the only thing that tells the two apart.

        `relrowsecurity` only, not `relforcerowsecurity` -- see
        `packages.core.migrations._require_countable_rows` for why a
        force-aware check would be resting on who owns the table.

        Returns `()` on SQLite, which has no row-level security: there, nothing
        can hide a row from a statement that asked for it, so a count is always
        a count."""
        if self._placeholder == "?":
            return ()
        guarded = {
            row[0]
            for row in self.query(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relrowsecurity"
            )
        }
        return tuple(table for table in tables if table in guarded)

    def suspend_row_level_security(self) -> None:
        """Take row-level security out of the way for the REST OF THIS
        TRANSACTION, so a migration can see the rows it has to reason about.

        WHY A MIGRATION NEEDS THIS AND AN APPLICATION NEVER DOES. Every store in
        this package acts FOR one tenant and sets the GUC to say so. A migration
        acts for the database: there is no tenant it could name, and naming one
        would be worse than naming none, because then it would see exactly one
        operator's rows and confidently report on all of them. The policies have
        to come off, and the only question is whether that is done deliberately
        and provably or discovered later.

        TWO STATEMENTS, and the second is the one that makes this safe to get
        wrong. `DISABLE ROW LEVEL SECURITY` lifts the filter; `SET LOCAL
        row_security = off` tells PostgreSQL to RAISE rather than filter if any
        table this missed is read anyway. Silence is what a policy does; an
        error is what a migration needs. `SET LOCAL` expires at the end of the
        transaction with no cleanup to forget.

        WHAT THIS DOES NOT DO IS OPEN A WINDOW. The `DISABLE` is DDL, it is
        transactional on PostgreSQL, and every caller re-applies
        `core_rls_postgres.sql` before its own commit -- so no other session ever
        observes an unguarded table (they cannot even try: `ALTER TABLE` holds
        ACCESS EXCLUSIVE for the duration), and a migration that raises has the
        `DISABLE` rolled back with everything else it did. It also grants nothing:
        this connection OWNS these tables and could have issued `NO FORCE` at any
        moment. What is bought is that the lowering is written down, bounded, and
        checked (`row_security_in_force`) rather than assumed.

        A no-op on SQLite, which has no policies to suspend."""
        if self._placeholder == "?":
            return
        self._conn.execute("SET LOCAL row_security = off")
        for table in ALL_CORE_TABLES:
            self._conn.execute(
                f"ALTER TABLE IF EXISTS {table} DISABLE ROW LEVEL SECURITY"
            )

    def schema_version(self) -> int | None:
        """The Program D schema version this database records, or `None` if it
        has never been stamped. After a successful open this is always
        `packages.core.migrations.CURRENT_SCHEMA_VERSION` -- an open that could
        not reach it raised instead of returning."""
        from packages.core.migrations import stamped_version

        return stamped_version(self)

    # -- schema introspection (portable) ------------------------------------ #
    def table_exists(self, table: str) -> bool:
        """Whether `table` exists in the schema this database writes into.

        The one place a catalog has to be consulted per engine -- there is no
        portable spelling -- so it is confined here beside the placeholder, next
        to the other genuine engine differences, rather than leaking into
        `migrations.py`. On PostgreSQL the lookup is scoped to `current_schema()`
        so a table of the same name in another `mx_core_<uuid>` schema is not
        mistaken for this one's."""
        if self._placeholder == "?":
            rows = self.query(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            )
        else:
            rows = self.query(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = ?",
                (table,),
            )
        return bool(rows)

    def column_names(self, table: str) -> tuple[str, ...]:
        """The column names of `table`, in declaration order.

        Portable by construction: a zero-row `SELECT *` and the DB-API
        `cursor.description` both engines are required to populate -- no
        `PRAGMA table_info` on one side and `information_schema.columns` on the
        other, which would be two chances to disagree about what a column is.
        Row-level security does not interfere: a policy filters ROWS, and this
        deliberately fetches none.

        `table` is interpolated, so it must never come from a caller: every use
        passes a name from `packages.core.migrations.CORE_TABLES`."""
        cursor = self._conn.execute(f"SELECT * FROM {table} WHERE 1 = 0")  # noqa: S608
        return tuple(column[0] for column in cursor.description)

    # -- statement execution ------------------------------------------------ #
    def execute_ddl(self, statement: str) -> None:
        """Execute ONE schema statement verbatim.

        Separate from `execute` because DDL takes no parameters and must not go
        through the `?` -> `%s` rewrite: a schema statement has nothing to
        substitute, and passing it through a parameter-shaped path would invite
        one to be added."""
        self._conn.execute(statement)

    def _cursor(self, statement: str, params: tuple):
        text = (
            statement
            if self._placeholder == "?"
            else statement.replace("?", self._placeholder)
        )
        if params:
            return self._conn.execute(text, params)
        return self._conn.execute(text)

    def query(self, statement: str, params: tuple = ()) -> list[tuple]:
        return list(self._cursor(statement, params).fetchall())

    def execute(self, statement: str, params: tuple = ()) -> None:
        self._cursor(statement, params)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- teardown ----------------------------------------------------------- #
    @property
    def schema(self) -> str | None:
        """The PostgreSQL schema this database writes into, or None on SQLite.
        Reopening the same schema is how the persistence tests prove state
        survives a connection being closed."""
        return self._schema

    def drop_schema(self) -> None:
        """Test/teardown helper: drops this instance's dedicated PostgreSQL
        schema and everything in it. A no-op on SQLite, whose isolation is the
        temporary file (or `:memory:`) itself. Never called from non-test code."""
        if self._schema is None:
            return
        from psycopg import sql as pg_sql

        with self._conn.cursor() as cur:
            cur.execute(
                pg_sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    pg_sql.Identifier(self._schema)
                )
            )
        self._conn.commit()


class PersistentFeatureStore:
    """Durable point-in-time feature store: `FeatureStore`'s contract, backed by
    `feature_values` in `packages/core/sql/core_v0_1.sql`.

    Method-for-method identical to the in-memory reference, so a caller can be
    handed either without changing a line (proved structurally by
    `test_core_persistence.py`). Append-only in the same sense: this class
    issues no UPDATE and no DELETE against `feature_values` at all -- a
    correction is a new row at a later (or equal) knowledge time.

    THE LEAKAGE GUARANTEE, THROUGH PERSISTENCE. `get_feature`'s
    `knowledge_time < ?` is a SQL predicate over `_iso_utc` text, so a value
    stamped at or after the label time is excluded by the DATABASE and never
    reaches Python. Ties at an identical knowledge time resolve to the last
    write via `write_sequence DESC` -- the same "latest recorded version wins"
    rule the in-memory store applies by scanning in append order.

    TENANT SCOPING. The store is bound to ONE tenant at construction and there
    is no unscoped way to reach the table: `tenant_id` is required, every
    statement below names it, and on PostgreSQL every operation first points the
    `milexium.tenant_id` GUC at it so the `core_rls_postgres.sql` policy is the
    outer boundary and the predicate the inner one. The tenant conjunct is added
    ALONGSIDE `knowledge_time < ?`, never in place of it, so the leakage
    guarantee is unchanged in strength -- a cross-tenant as-of read returns
    nothing however permissive the timestamp is.
    """

    def __init__(self, database: CoreDatabase, tenant_id: TenantId) -> None:
        self._db = database
        # Validated as a canonical TenantId rather than accepted as any string:
        # a malformed tenant would otherwise become a silently distinct, and
        # permanently unreadable, partition of the table.
        self._tenant_id = str(TenantId(str(tenant_id)))

    @property
    def tenant_id(self) -> TenantId:
        """The single tenant this store reads and writes. Read-only: rebinding
        it would turn one object into a cross-tenant path."""
        return TenantId(self._tenant_id)

    def _scope(self) -> None:
        """Point the session at this store's tenant before any statement."""
        self._db.use_tenant(self._tenant_id)

    # -- writes ------------------------------------------------------------- #
    def write(
        self,
        *,
        entity_id: str,
        feature_name: str,
        value: float,
        knowledge_time: datetime,
    ) -> FeatureValue:
        """Append one observation. `knowledge_time` must be timezone-aware UTC
        (the same rule every canonical timestamp obeys).

        `write_sequence` is assigned here, not by the engine: SERIAL/AUTOINCREMENT
        are spelled differently per engine and would break the portable-DDL rule,
        and an application-assigned sequence makes append order a property of the
        stored rows -- readable by anything, not just this class.
        """
        _require_utc(knowledge_time)
        observation = FeatureValue(
            entity_id=entity_id,
            feature_name=feature_name,
            value=float(value),
            knowledge_time=knowledge_time,
        )
        self._scope()
        next_sequence = int(
            self._db.query(
                "SELECT COALESCE(MAX(write_sequence), 0) + 1 FROM feature_values "
                "WHERE tenant_id = ? AND entity_id = ? AND feature_name = ?",
                (self._tenant_id, entity_id, feature_name),
            )[0][0]
        )
        self._db.execute(
            "INSERT INTO feature_values (tenant_id, entity_id, feature_name, value, "
            "knowledge_time, write_sequence) VALUES (?, ?, ?, ?, ?, ?)",
            (
                self._tenant_id,
                entity_id,
                feature_name,
                observation.value,
                _iso_utc(observation.knowledge_time),
                next_sequence,
            ),
        )
        self._db.commit()
        return observation

    # -- as-of reads -------------------------------------------------------- #
    def get_feature(
        self, entity_id: str, feature_name: str, *, as_of: datetime
    ) -> float | None:
        """The latest value for one feature whose `knowledge_time` is STRICTLY
        earlier than `as_of`, or `None` if no such value exists.

        The strict `<` is in the WHERE clause, so a row stamped exactly at
        `as_of` (or later) is never returned by the engine -- the leakage
        guarantee is enforced at the storage layer, not re-implemented above it.

        `tenant_id = ?` sits BESIDE it, as another conjunct of the same
        predicate, so the result is the intersection of the two rules: another
        tenant's value is invisible at every `as_of`, and this tenant's future
        value is invisible whatever the tenant.
        """
        _require_utc(as_of)
        self._scope()
        rows = self._db.query(
            "SELECT value FROM feature_values "
            "WHERE tenant_id = ? AND entity_id = ? AND feature_name = ? "
            "AND knowledge_time < ? "
            "ORDER BY knowledge_time DESC, write_sequence DESC LIMIT 1",
            (self._tenant_id, entity_id, feature_name, _iso_utc(as_of)),
        )
        return float(rows[0][0]) if rows else None

    def get_features(self, entity_id: str, *, as_of: datetime) -> dict[str, float]:
        """Every feature known for `entity_id` as-of `as_of`, each resolved by
        the strict past-only rule of `get_feature`. Features with no value
        strictly before `as_of` are omitted.

        One query, not one per feature: the same `knowledge_time < ?` predicate
        selects only strictly-past rows, and ASCENDING (knowledge_time,
        write_sequence) order means the last row seen per feature is the winner
        -- identical resolution to `get_feature`, run once.
        """
        _require_utc(as_of)
        self._scope()
        rows = self._db.query(
            "SELECT feature_name, value FROM feature_values "
            "WHERE tenant_id = ? AND entity_id = ? AND knowledge_time < ? "
            "ORDER BY feature_name, knowledge_time, write_sequence",
            (self._tenant_id, entity_id, _iso_utc(as_of)),
        )
        result: dict[str, float] = {}
        for feature_name, value in rows:
            result[feature_name] = float(value)
        return result

    # -- audit views -------------------------------------------------------- #
    def history(self, entity_id: str, feature_name: str) -> tuple[FeatureValue, ...]:
        """Every recorded observation for one (entity, feature), in append
        order -- the audit view, distinct from the as-of read. Unlike the as-of
        read this deliberately applies NO time filter: the audit view shows
        everything that was ever written, including values a point-in-time read
        would refuse to show. It applies no time filter; it does still apply the
        TENANT filter -- an audit view is an audit view of one operator's own
        writes, never of everyone's."""
        self._scope()
        rows = self._db.query(
            "SELECT value, knowledge_time FROM feature_values "
            "WHERE tenant_id = ? AND entity_id = ? AND feature_name = ? "
            "ORDER BY write_sequence",
            (self._tenant_id, entity_id, feature_name),
        )
        return tuple(
            FeatureValue(
                entity_id=entity_id,
                feature_name=feature_name,
                value=float(value),
                knowledge_time=datetime.fromisoformat(knowledge_time),
            )
            for value, knowledge_time in rows
        )

    def entities(self) -> frozenset[str]:
        """Every entity THIS TENANT has written a value for.

        The tenant filter matters more here than anywhere else in the class: an
        unscoped `SELECT DISTINCT entity_id` would enumerate every operator's
        entity ids -- which is a membership disclosure even though the ids are
        opaque, because it says how many entities another operator runs.
        """
        self._scope()
        return frozenset(
            row[0]
            for row in self._db.query(
                "SELECT DISTINCT entity_id FROM feature_values WHERE tenant_id = ?",
                (self._tenant_id,),
            )
        )
