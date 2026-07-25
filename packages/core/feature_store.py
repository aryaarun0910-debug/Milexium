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
genuinely diverge. Program D's stores have no tenant dimension and therefore no
RLS: the ONLY engine difference is the DB-API placeholder and how a connection
is opened. Duplicating the SQL to mirror the canonical file layout would buy
nothing and would let the two copies drift; instead the store logic exists once
over an engine-parametrised `CoreDatabase`, opened by
`CoreDatabase.sqlite(...)` or `CoreDatabase.postgres(...)`. What the canonical
pattern actually asserts -- one contract, two engines, proven by
`[sqlite]`/`[postgres]`-parametrised conformance
(`conformance/property-tests/test_core_persistence.py`) -- is preserved, and
contract drift between engines becomes structurally impossible rather than
merely tested for.

The leakage guarantee survives persistence because the strict `<` is evaluated
by the DATABASE: `knowledge_time < :as_of` is a SQL predicate over fixed-width
canonical ISO-8601 UTC text (`_iso_utc`), whose lexicographic order is its
chronological order. A future row is never fetched and then filtered in Python
-- it is never fetched at all. `conformance/property-tests/test_core_persistence.py`
re-runs the ADR-0034 mechanical future-corruption discipline through this path.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from packages.canonical.time import UtcDateTime, _require_utc

CORE_SCHEMA_PATH = Path(__file__).parent / "sql" / "core_v0_1.sql"

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
    DB-API placeholder (`?` vs `%s`), how the DDL is applied, and (PostgreSQL
    only) the disposable per-instance schema. Every statement above this class
    is written once, with `?` placeholders, and runs on both engines.

    PostgreSQL instances get a dedicated schema (`mx_core_<uuid>` by default),
    created at construction and torn down by `drop_schema()` -- the same
    test-isolation strategy `packages/canonical/postgres_storage.py` uses,
    because a real server is a shared persistent process rather than SQLite's
    disposable `:memory:` default. `CREATE SCHEMA IF NOT EXISTS` plus the DDL's
    own `IF NOT EXISTS` means REOPENING a named schema (or an on-disk SQLite
    file) is idempotent -- which is exactly the persistence claim under test.
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
    def sqlite(cls, path: str = ":memory:") -> "CoreDatabase":
        """Open (or create) a SQLite database and apply the core DDL. A path
        other than `:memory:` is what makes the store outlive the process."""
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(CORE_SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.commit()
        return cls(connection, placeholder="?")

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
    ) -> "CoreDatabase":
        """Open the natively installed PostgreSQL 17 dev instance (ADR-0006) and
        apply the SAME `core_v0_1.sql`, unmodified -- the portability claim
        (ADR-0002) is that the file needs no per-engine edit."""
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
            cur.execute(CORE_SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.commit()
        return cls(connection, placeholder="%s", schema=schema_name)

    # -- statement execution ------------------------------------------------ #
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
    """

    def __init__(self, database: CoreDatabase) -> None:
        self._db = database

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
        next_sequence = int(
            self._db.query(
                "SELECT COALESCE(MAX(write_sequence), 0) + 1 FROM feature_values "
                "WHERE entity_id = ? AND feature_name = ?",
                (entity_id, feature_name),
            )[0][0]
        )
        self._db.execute(
            "INSERT INTO feature_values (entity_id, feature_name, value, "
            "knowledge_time, write_sequence) VALUES (?, ?, ?, ?, ?)",
            (
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
        """
        _require_utc(as_of)
        rows = self._db.query(
            "SELECT value FROM feature_values "
            "WHERE entity_id = ? AND feature_name = ? AND knowledge_time < ? "
            "ORDER BY knowledge_time DESC, write_sequence DESC LIMIT 1",
            (entity_id, feature_name, _iso_utc(as_of)),
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
        rows = self._db.query(
            "SELECT feature_name, value FROM feature_values "
            "WHERE entity_id = ? AND knowledge_time < ? "
            "ORDER BY feature_name, knowledge_time, write_sequence",
            (entity_id, _iso_utc(as_of)),
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
        would refuse to show."""
        rows = self._db.query(
            "SELECT value, knowledge_time FROM feature_values "
            "WHERE entity_id = ? AND feature_name = ? ORDER BY write_sequence",
            (entity_id, feature_name),
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
        return frozenset(
            row[0] for row in self._db.query("SELECT DISTINCT entity_id FROM feature_values")
        )
