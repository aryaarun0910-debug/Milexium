"""Durable ontology store: one contract, two engines, one receipt order.

WHERE THE INFORMATION-SET BOUNDARY ACTUALLY LIVES.
`take_snapshot` issues `receipt_time < ?` as a WHERE-clause predicate over
fixed-width ISO-8601 UTC text. A row received at or after the decision instant
is excluded by the DATABASE and never reaches Python -- it is not fetched and
then filtered, it is not fetched. That is deliberately the same mechanism, in
the same spelling, that `themis/core/feature_store.PersistentFeatureStore`
uses for `knowledge_time < ?`, and this module imports that module's
`_iso_utc` rather than defining a second timestamp convention.

The object layer re-checks the same rule (`DecisionSnapshot._validate`), which
is redundant on purpose: two independent implementations of one boundary, so a
mutation to either is caught.

WHY THIS PACKAGE HAS ITS OWN `OntologyDatabase` INSTEAD OF REUSING
`themis/core/feature_store.CoreDatabase`.
`CoreDatabase.sqlite/postgres` run `themis.core.migrations.migrate`, which
applies Program D's schema and REFUSES to open a database whose version it does
not recognise. Reusing it would make the ontology's tables depend on Program D's
migration version and would put ontology DDL behind a migration runner in
another package's owned path. The two classes are deliberately near-identical in
shape (same placeholder rewrite, same per-instance PostgreSQL schema, same
`use_tenant` GUC, same `drop_schema` teardown) so the pattern is one pattern; a
conformance test asserts the method surface matches, so the similarity is
checked rather than merely intended.

TENANT SCOPING. `OntologyStore` is constructed FOR ONE TENANT and cannot be
constructed without one. Every statement names `tenant_id`, and on PostgreSQL
every operation first sets the `milexium.tenant_id` GUC that
`sql/ontology_rls_postgres.sql`'s policies key on -- so the boundary is enforced
by the database and the WHERE clause is the second of two independent
boundaries, not the only one. The tenant conjunct sits BESIDE `receipt_time < ?`,
never in place of it: a read returns the intersection of "my tenant's rows" and
"strictly in the past", and neither conjunct can rescue a row the other excludes.

STATUS: Demonstrated. Every fixture is synthetic.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Callable, Sequence

from themis.canonical.events import canonical_json, compute_hash
from themis.canonical.time import _require_utc
from themis.ontology.actions import (
    ActionAlternative,
    ActionOutcome,
    ActionPrediction,
    ActionRecord,
    Authority,
    VerifierResult,
)
from themis.ontology.events import (
    LateArrivalReason,
    OntologyEvent,
)
from themis.ontology.graph import OntologyObject, Relationship
from themis.ontology.ids import (
    ActionId,
    CandidateSetId,
    FactId,
    ObjectId,
    OntologyEventId,
    OutcomeId,
    PolicyId,
    RelationshipId,
    SnapshotId,
    TenantId,
    new_id,
)
from themis.ontology.provenance import (
    IdentityResolution,
    MatchCandidate,
    SnapshotFact,
)
from themis.ontology.receipt import ReceiptStamp, iso_receipt, next_stamp, system_utc_clock
from themis.ontology.snapshot import (
    DecisionSnapshot,
    SnapshotPurpose,
    SnapshotScope,
)
from themis.ontology.vocab import (
    ActionKind,
    AuthorityKind,
    EventKind,
    FactClass,
    LegalBasis,
    MissingnessReason,
    ObjectKind,
    QualityState,
    ReasonCode,
    RelationshipKind,
    RepairKind,
    SensitivityClass,
)

__all__ = [
    "ONTOLOGY_TABLES",
    "OntologyDatabase",
    "OntologyStore",
    "SnapshotDriftError",
    "UnknownSnapshotError",
    "ForgedSnapshotError",
    "IntegrityReport",
    "split_sql_statements",
]

_SQL_DIR = Path(__file__).parent / "sql"
SCHEMA_PATH = _SQL_DIR / "ontology_v0_1.sql"
RLS_PATH = _SQL_DIR / "ontology_rls_postgres.sql"
IMMUTABILITY_SQLITE_PATH = _SQL_DIR / "ontology_immutability_sqlite.sql"
IMMUTABILITY_POSTGRES_PATH = _SQL_DIR / "ontology_immutability_postgres.sql"

# ADR-0006: the local dev role is `milexium_dev`, never the Postgres superuser,
# and its password is read from the user profile at connection time -- never
# hardcoded, never committed, never logged.
_DEFAULT_PASSWORD_FILE = Path.home() / ".milexium_pg_app_password.txt"

ONTOLOGY_TABLES: tuple[str, ...] = (
    "ontology_receipt_log",
    "ontology_objects",
    "ontology_relationships",
    "ontology_facts",
    "ontology_events",
    "ontology_identity_resolutions",
    "ontology_snapshots",
    "ontology_actions",
    "ontology_action_outcomes",
)
"""Every table this package owns. Used by the conformance suite to assert that
each one is tenant-scoped, RLS-guarded and immutability-triggered -- ADR-0037's
"a tenant-scoped table without a policy is a defect, not a to-do", applied by
enumeration rather than by remembering."""


class SnapshotDriftError(RuntimeError):
    """A reloaded snapshot did not reproduce the content hash it was taken with.

    THE MOST IMPORTANT ERROR IN THIS MODULE, because it is the one that should be
    unreachable. `load_snapshot` re-derives a snapshot's content from the store
    using its stored `(as_of, scope, purpose)`; receipt monotonicity is supposed
    to make it impossible for anything to have appeared before an already-taken
    boundary, so the re-derivation must reproduce the same content. If it does
    not, something was written into the past, and every downstream artefact built
    from that snapshot is suspect. Raising is the only safe response -- returning
    the new content would silently rewrite history and returning the old would
    hide that the store is broken.
    """


class UnknownSnapshotError(LookupError):
    """An action cited a snapshot this store never recorded."""


class ForgedSnapshotError(ValueError):
    """A snapshot object's content hash does not match the one recorded when it
    was taken -- the signature of a `model_copy(update=...)` forgery, which
    bypasses pydantic validators by design."""


def split_sql_statements(sql_text: str) -> tuple[str, ...]:
    """Split a `.sql` file into individual statements.

    Needed because the engines disagree about multi-statement execution:
    `sqlite3.Connection.execute` accepts exactly one statement (`executescript`
    takes many but COMMITs first, which would break a schema application into
    pieces), while psycopg accepts many. Splitting for BOTH gives one code path.

    MORE THAN `themis.core.migrations.split_statements` DOES, and the extra is
    required rather than gold-plating: that splitter strips `--` comments and
    splits naively on `;`, which is correct for its files and WRONG for both of
    this package's trigger files. A SQLite trigger body is `BEGIN ... ; END;` and
    a PL/pgSQL function body is `$$ ... ; ... $$`; a naive split truncates the
    first at its inner semicolon and silently installs a trigger that does
    nothing -- which is exactly the false green shape this packet exists not to
    produce. This splitter therefore tracks `$$` dollar-quoting and BEGIN/END
    nesting.

    Still deliberately simple in one respect: `--` comments are stripped
    line-wise BEFORE scanning, so a `--` inside a string literal would be
    mangled. No file in `themis/ontology/sql` contains one, and a conformance
    test pins each file's statement COUNT so a future file that breaks the
    assumption fails loudly rather than silently truncating a schema.
    """
    lines: list[str] = []
    for line in sql_text.splitlines():
        comment = line.find("--")
        if comment >= 0:
            line = line[:comment]
        if line.strip():
            lines.append(line)
    body = "\n".join(lines)

    statements: list[str] = []
    buf: list[str] = []
    i = 0
    in_string = False
    in_dollar = False
    depth = 0  # unmatched BEGIN count, outside strings/dollar quotes
    while i < len(body):
        ch = body[i]
        if in_dollar:
            if body.startswith("$$", i):
                in_dollar = False
                buf.append("$$")
                i += 2
                continue
            buf.append(ch)
            i += 1
            continue
        if in_string:
            buf.append(ch)
            if ch == "'":
                if body.startswith("''", i):
                    buf.append("'")
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if body.startswith("$$", i):
            in_dollar = True
            buf.append("$$")
            i += 2
            continue
        if ch == "'":
            in_string = True
            buf.append(ch)
            i += 1
            continue
        if body.startswith("BEGIN", i) and _is_word_boundary(body, i, 5):
            depth += 1
            buf.append("BEGIN")
            i += 5
            continue
        if body.startswith("END", i) and _is_word_boundary(body, i, 3):
            depth = max(0, depth - 1)
            buf.append("END")
            i += 3
            continue
        if ch == ";" and depth == 0:
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return tuple(statements)


def _is_word_boundary(text: str, start: int, length: int) -> bool:
    before = text[start - 1] if start > 0 else " "
    after = text[start + length] if start + length < len(text) else " "
    return not before.isalnum() and before != "_" and not after.isalnum() and after != "_"


def _read_dev_password() -> str:
    return _DEFAULT_PASSWORD_FILE.read_text(encoding="utf-8").strip()


def _row_digest(columns: Sequence[Any]) -> str:
    """SHA-256 over the exact column values a row is stored with.

    Computed from the VALUE LIST, at write time and again at verification time
    from what was read back, so the two are comparable only if the stored row is
    byte-for-byte what was written. This is the detection layer: a direct SQL
    UPDATE that got past the immutability triggers changes the row but not the
    recorded digest, and `OntologyStore.verify_integrity` sees the mismatch.
    """
    return hashlib.sha256(
        canonical_json({"cols": [None if c is None else c for c in columns]}).encode(
            "utf-8"
        )
    ).hexdigest()


# --------------------------------------------------------------------------- #
# Database adapter: one contract, two engines
# --------------------------------------------------------------------------- #
class OntologyDatabase:
    """A connection to a database carrying `sql/ontology_v0_1.sql`.

    The single point at which SQLite and PostgreSQL differ: the DB-API
    placeholder (`?` vs `%s`), how a connection is opened, (PostgreSQL only) the
    disposable per-instance schema, and which of the two immutability files is
    applied. Every statement above this class is written once with `?`
    placeholders and runs on both engines.
    """

    def __init__(
        self, connection: Any, *, placeholder: str, schema: str | None = None
    ) -> None:
        self._conn = connection
        self._placeholder = placeholder
        self._schema = schema

    # -- construction -------------------------------------------------------- #
    @classmethod
    def sqlite(cls, path: str = ":memory:") -> "OntologyDatabase":
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        # Recursive triggers OFF is the sqlite3 default and is what we want: the
        # immutability triggers must not re-enter each other.
        database = cls(connection, placeholder="?")
        try:
            database._apply_schema()
        except BaseException:
            # A refused database must not leave an open handle behind: on Windows
            # an open SQLite handle blocks the file being inspected or replaced,
            # which is exactly what a refusal invites you to do.
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
    ) -> "OntologyDatabase":
        import psycopg
        from psycopg import sql as pg_sql

        if password is None:
            password = _read_dev_password()
        connection = psycopg.connect(
            host=host, port=port, dbname=dbname, user=user, password=password
        )
        schema_name = schema or f"mx_ont_{uuid.uuid4().hex}"
        ident = pg_sql.Identifier(schema_name)
        with connection.cursor() as cur:
            cur.execute(pg_sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(ident))
            cur.execute(pg_sql.SQL("SET search_path TO {}").format(ident))
        database = cls(connection, placeholder="%s", schema=schema_name)
        try:
            database._apply_schema()
        except BaseException:
            try:
                connection.rollback()
            finally:
                connection.close()
            raise
        return database

    @staticmethod
    def is_postgres_reachable(connect_timeout: float = 2.0) -> bool:
        """Best-effort probe so tests skip cleanly (never fail) on a machine
        where `milexium_dev` was never provisioned."""
        try:
            import psycopg

            conn = psycopg.connect(
                host="localhost",
                port=5432,
                dbname="milexium_dev",
                user="milexium_dev",
                password=_read_dev_password(),
                connect_timeout=connect_timeout,
            )
            conn.close()
            return True
        except Exception:
            return False

    def _apply_schema(self) -> None:
        """Portable DDL, then the engine's immutability file, then (PostgreSQL
        only) row-level security.

        ORDER IS LOAD-BEARING. The immutability triggers must exist before any
        row is written, or a window exists in which the tables are append-only
        only by convention. RLS goes last because it is applied with
        `DROP POLICY IF EXISTS` + `CREATE POLICY` and must not be in force while
        the schema is still being created.
        """
        if not self.table_exists("ontology_receipt_log"):
            for statement in split_sql_statements(
                SCHEMA_PATH.read_text(encoding="utf-8")
            ):
                self.execute_ddl(statement)
            immutability = (
                IMMUTABILITY_SQLITE_PATH
                if self._placeholder == "?"
                else IMMUTABILITY_POSTGRES_PATH
            )
            for statement in split_sql_statements(
                immutability.read_text(encoding="utf-8")
            ):
                self.execute_ddl(statement)
        elif self._placeholder != "?":
            # Reopening an existing PostgreSQL schema: the trigger file is
            # written to be re-appliable (DROP TRIGGER IF EXISTS + CREATE) so a
            # reopen restores anything that was dropped.
            for statement in split_sql_statements(
                IMMUTABILITY_POSTGRES_PATH.read_text(encoding="utf-8")
            ):
                self.execute_ddl(statement)
        self.apply_row_level_security()
        self.commit()

    # -- tenant scoping ------------------------------------------------------ #
    def use_tenant(self, tenant_id: object) -> None:
        """Point the session's RLS key (`milexium.tenant_id`) at `tenant_id`.

        Called before EVERY read and write, so no operation depends on a value
        an earlier one happened to leave behind. Session scope
        (`is_local=false`) because this store commits per operation. The value
        is a BOUND PARAMETER, never string-interpolated. A no-op on SQLite,
        which has no row-level security to key.
        """
        if self._placeholder == "?":
            return
        self._conn.execute(
            "SELECT set_config('milexium.tenant_id', %s, false)", (str(tenant_id),)
        )

    def apply_row_level_security(self) -> None:
        """Apply `ontology_rls_postgres.sql`. A no-op on SQLite."""
        if self._placeholder == "?":
            return
        for statement in split_sql_statements(RLS_PATH.read_text(encoding="utf-8")):
            self._conn.execute(statement)

    def row_security_in_force(self, tables: tuple[str, ...]) -> tuple[str, ...]:
        """Which of `tables` would filter this session's reads through a policy.

        The evidence a test needs BEFORE it believes a row count: under a policy
        with no `milexium.tenant_id` in scope a SELECT returns zero rows, and
        zero rows is a perfectly ordinary answer meaning "empty". The catalog is
        the only thing that tells the two apart. Returns `()` on SQLite, which
        has no row-level security, so there a count is always a count.
        """
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

    def force_row_security_in_force(self, tables: tuple[str, ...]) -> tuple[str, ...]:
        """Which of `tables` apply their policy to the table OWNER too.

        Separate from `row_security_in_force` because ENABLE without FORCE is the
        false green: the application role owns these tables, an owner bypasses
        RLS by default, and every isolation test would then pass without the
        policy constraining anything."""
        if self._placeholder == "?":
            return ()
        forced = {
            row[0]
            for row in self.query(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relforcerowsecurity"
            )
        }
        return tuple(table for table in tables if table in forced)

    # -- introspection ------------------------------------------------------- #
    def table_exists(self, table: str) -> bool:
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
        """Column names in declaration order, portably: a zero-row `SELECT *`
        and the DB-API `cursor.description` both engines must populate. A policy
        filters ROWS, and this deliberately fetches none, so RLS does not
        interfere. `table` is interpolated and must never come from a caller --
        every use passes a name from `ONTOLOGY_TABLES`."""
        cursor = self._conn.execute(f"SELECT * FROM {table} WHERE 1 = 0")  # noqa: S608
        return tuple(column[0] for column in cursor.description)

    # -- statements ----------------------------------------------------------- #
    def execute_ddl(self, statement: str) -> None:
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

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    @property
    def is_postgres(self) -> bool:
        return self._placeholder != "?"

    @property
    def schema(self) -> str | None:
        return self._schema

    def drop_schema(self) -> None:
        """Test/teardown helper. A no-op on SQLite, whose isolation is the
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


class IntegrityReport:
    """What `verify_integrity` found. Not a bool, because "the chain is intact"
    and "the chain is intact and covers 412 rows" are different assurances and a
    caller shown only the first cannot tell an empty ledger from a verified one."""

    def __init__(
        self,
        *,
        rows_checked: int,
        chain_breaks: tuple[int, ...],
        row_mismatches: tuple[tuple[str, str], ...],
    ) -> None:
        self.rows_checked = rows_checked
        self.chain_breaks = chain_breaks
        self.row_mismatches = row_mismatches

    @property
    def intact(self) -> bool:
        return not self.chain_breaks and not self.row_mismatches

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return (
            f"IntegrityReport(rows_checked={self.rows_checked}, "
            f"chain_breaks={self.chain_breaks}, row_mismatches={self.row_mismatches})"
        )


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #
class OntologyStore:
    """Ontology writes and point-in-time reads, for ONE tenant.

    THE WRITE SURFACE IS THE ACTION SURFACE. There is no `execute`, no
    `write_row`, no generic upsert. The only methods that change operational
    state are the typed ones below, and the two that record an *effect*
    (`record_action`, `record_outcome`) require an `Authority` holding the
    action's permission and a verified input snapshot. A conformance test
    enumerates this class's public methods and asserts the set, so a future
    generic writer cannot be added quietly.

    THE CLOCK. `clock` is a constructor argument defaulting to the system UTC
    clock. It is the ONLY way a receipt time enters the system: no method takes
    one. See `themis/ontology/receipt.py` for why a construction-time seam is
    categorically different from the per-write `recorded_at` parameter the
    2026-07-26 audit broke, and for what it still does not defend against.
    """

    def __init__(
        self,
        database: OntologyDatabase,
        tenant_id: TenantId,
        *,
        clock: Callable[[], datetime] = system_utc_clock,
    ) -> None:
        self._db = database
        # Validated as a canonical TenantId rather than accepted as any string: a
        # malformed tenant would become a silently distinct, and permanently
        # unreadable, partition of every table.
        self._tenant_id = str(TenantId(str(tenant_id)))
        self._clock = clock

    @property
    def tenant_id(self) -> TenantId:
        """The single tenant this store reads and writes. Read-only: rebinding
        it would turn one object into a cross-tenant path."""
        return TenantId(self._tenant_id)

    @property
    def database(self) -> OntologyDatabase:
        return self._db

    def _scope(self) -> None:
        self._db.use_tenant(self._tenant_id)

    # -- the receipt spine ---------------------------------------------------- #
    def _head(self) -> tuple[ReceiptStamp | None, str | None]:
        rows = self._db.query(
            "SELECT receipt_time, receipt_sequence, hash FROM ontology_receipt_log "
            "WHERE tenant_id = ? ORDER BY receipt_sequence DESC LIMIT 1",
            (self._tenant_id,),
        )
        if not rows:
            return None, None
        receipt_time, sequence, chain_hash = rows[0]
        return (
            ReceiptStamp(
                receipt_time=datetime.fromisoformat(receipt_time),
                receipt_sequence=int(sequence),
            ),
            chain_hash,
        )

    @contextmanager
    def _atomic(self):
        """Commit on success, ROLL BACK on any failure.

        WHY THIS EXISTS RATHER THAN VALIDATING FIRST. An earlier revision of this
        module validated each model against a throwaway stamp before consuming a
        real one. That worked but it called the clock twice per write, which made
        receipt times in tests depend on how many validations a method happened
        to perform -- and a receipt order that depends on internal implementation
        detail is exactly the sort of thing that later gets "optimised" and
        silently changes the boundary.

        Rolling back instead is both simpler and stronger: the ledger row is
        written FIRST, so a failure anywhere afterwards -- a pydantic validator, a
        CHECK constraint, an immutability trigger -- unwinds the receipt sequence
        with it. A rejected write consumes nothing and leaves no gap, and
        `verify_integrity`'s gaplessness assumption stays true.
        """
        try:
            yield
        except BaseException:
            self._db.rollback()
            raise
        self._db.commit()

    def _stamp(
        self, *, stream: str, row_id: str, columns: Sequence[Any]
    ) -> tuple[ReceiptStamp, str | None, str]:
        """Issue the next receipt stamp and append the ledger row.

        Returns `(stamp, prev_hash, chain_hash)`. The caller then writes its own
        row carrying `(receipt_time, receipt_sequence)` -- which is why the
        ledger row is written FIRST: if the second insert fails, the ledger has a
        stamp whose row is missing, which `verify_integrity` reports as a row
        mismatch. The reverse order would leave a row with a stamp that was never
        issued, which nothing would notice.
        """
        self._scope()
        previous, prev_hash = self._head()
        stamp = next_stamp(previous=previous, clock=self._clock)
        row_hash = _row_digest(columns)
        chain_hash = compute_hash(
            prev_hash,
            {"stream": stream, "row_hash": row_hash},
            stamp.receipt_sequence,
            row_id,
            None,
        )
        self._db.execute(
            "INSERT INTO ontology_receipt_log (tenant_id, receipt_sequence, "
            "receipt_time, stream, row_id, row_hash, prev_hash, hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self._tenant_id,
                stamp.receipt_sequence,
                stamp.iso,
                stream,
                row_id,
                row_hash,
                prev_hash,
                chain_hash,
            ),
        )
        return stamp, prev_hash, chain_hash

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def register_object(
        self,
        *,
        object_kind: ObjectKind,
        external_ref: str | None = None,
        source_system: str | None = None,
        object_id: ObjectId | None = None,
    ) -> OntologyObject:
        """Mint (or adopt) an identity. Carries no attributes -- see
        `themis/ontology/graph.py` for why an object holds identity only."""
        oid = object_id or new_id(ObjectId)
        columns = (
            str(oid),
            self._tenant_id,
            object_kind.value,
            external_ref,
            source_system,
        )
        stamp, _, _ = self._stamp(stream="object", row_id=str(oid), columns=columns)
        with self._atomic():
            obj = OntologyObject(
                object_id=oid,
                tenant_id=TenantId(self._tenant_id),
                object_kind=object_kind,
                external_ref=external_ref,
                source_system=source_system,
                receipt=stamp,
            )
            self._db.execute(
                "INSERT INTO ontology_objects (object_id, tenant_id, object_kind, "
                "external_ref, source_system, receipt_time, receipt_sequence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (*columns, stamp.iso, stamp.receipt_sequence),
            )
        return obj

    def assert_relationship(
        self,
        *,
        relationship_kind: RelationshipKind,
        subject_kind: ObjectKind,
        subject_id: ObjectId,
        object_kind: ObjectKind,
        object_id: ObjectId,
        asserted_by: str,
        weight: float | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        retracts_relationship_id: RelationshipId | None = None,
    ) -> Relationship:
        """Assert one edge. Legality is checked by `Relationship`'s validator
        against `RELATIONSHIP_SIGNATURES` inside `_atomic`, so an illegal edge
        rolls the whole write back -- including the receipt-ledger row -- and
        leaves no gap in the tenant's receipt sequence."""
        rid = new_id(RelationshipId)
        columns = (
            str(rid),
            self._tenant_id,
            relationship_kind.value,
            subject_kind.value,
            str(subject_id),
            object_kind.value,
            str(object_id),
            weight,
            None if valid_from is None else iso_receipt(valid_from),
            None if valid_to is None else iso_receipt(valid_to),
            asserted_by,
            None if retracts_relationship_id is None else str(retracts_relationship_id),
        )
        probe = dict(
            relationship_id=rid,
            tenant_id=TenantId(self._tenant_id),
            relationship_kind=relationship_kind,
            subject_kind=subject_kind,
            subject_id=subject_id,
            object_kind=object_kind,
            object_id=object_id,
            weight=weight,
            valid_from=valid_from,
            valid_to=valid_to,
            asserted_by=asserted_by,
            retracts_relationship_id=retracts_relationship_id,
        )
        stamp, _, _ = self._stamp(
            stream="relationship", row_id=str(rid), columns=columns
        )
        with self._atomic():
            relationship = Relationship(**probe, receipt=stamp)
            self._db.execute(
                "INSERT INTO ontology_relationships (relationship_id, tenant_id, "
                "relationship_kind, subject_kind, subject_id, object_kind, object_id, "
                "weight, valid_from, valid_to, asserted_by, retracts_relationship_id, "
                "receipt_time, receipt_sequence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*columns, stamp.iso, stamp.receipt_sequence),
            )
        return relationship

    def record_fact(
        self,
        *,
        subject_kind: ObjectKind,
        subject_id: ObjectId,
        attribute: str,
        fact_class: FactClass,
        quality: QualityState,
        sensitivity: SensitivityClass,
        legal_basis: LegalBasis,
        source_system: str,
        value: float | int | str | bool | None = None,
        missing_reason: MissingnessReason | None = None,
        event_time: datetime | None = None,
        confidence: float | None = None,
        repair_kind: RepairKind = RepairKind.NONE,
        repairs_fact_id: FactId | None = None,
        repair_note: str | None = None,
        special_category: bool = False,
        source_record_id: str | None = None,
    ) -> SnapshotFact:
        """Append one field-level claim.

        NOTE THE ABSENT PARAMETER. There is no `receipt_time`. `event_time` is
        the caller's (only they know when the thing was observed); the receipt is
        the writer's. This signature is read back by
        `aletheia/conformance/property-tests/test_ontology_receipt.py` with
        `inspect.signature`, so the guarantee is checked rather than documented.
        """
        fid = new_id(FactId)
        if value is None:
            value_kind, value_number, value_text, value_bool = "absent", None, None, None
        elif isinstance(value, bool):
            value_kind, value_number, value_text, value_bool = "bool", None, None, int(value)
        elif isinstance(value, (int, float)):
            value_kind, value_number, value_text, value_bool = "number", float(value), None, None
        else:
            value_kind, value_number, value_text, value_bool = "text", None, str(value), None

        columns = (
            str(fid),
            self._tenant_id,
            subject_kind.value,
            str(subject_id),
            attribute,
            fact_class.value,
            value_kind,
            value_number,
            value_text,
            value_bool,
            None if missing_reason is None else missing_reason.value,
            None if event_time is None else iso_receipt(event_time),
            quality.value,
            confidence,
            repair_kind.value,
            None if repairs_fact_id is None else str(repairs_fact_id),
            repair_note,
            sensitivity.value,
            int(special_category),
            legal_basis.value,
            source_system,
            source_record_id,
        )
        payload = dict(
            fact_id=fid,
            tenant_id=TenantId(self._tenant_id),
            subject_kind=subject_kind,
            subject_id=subject_id,
            attribute=attribute,
            value=value,
            missing_reason=missing_reason,
            fact_class=fact_class,
            event_time=event_time,
            quality=quality,
            confidence=confidence,
            repair_kind=repair_kind,
            repairs_fact_id=repairs_fact_id,
            repair_note=repair_note,
            sensitivity=sensitivity,
            special_category=special_category,
            legal_basis=legal_basis,
            source_system=source_system,
            source_record_id=source_record_id,
        )
        stamp, _, _ = self._stamp(stream="fact", row_id=str(fid), columns=columns)
        with self._atomic():
            fact = SnapshotFact(**payload, receipt=stamp)
            self._db.execute(
                "INSERT INTO ontology_facts (fact_id, tenant_id, subject_kind, subject_id, "
                "attribute, fact_class, value_kind, value_number, value_text, value_bool, "
                "missing_reason, event_time, quality, confidence, repair_kind, "
                "repairs_fact_id, repair_note, sensitivity, special_category, legal_basis, "
                "source_system, source_record_id, receipt_time, receipt_sequence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*columns, stamp.iso, stamp.receipt_sequence),
            )
        return fact

    def record_event(
        self,
        *,
        event_kind: EventKind,
        subject_kind: ObjectKind,
        subject_id: ObjectId,
        occurred_at: datetime,
        actor_kind: AuthorityKind,
        actor_ref: str,
        reason_codes: tuple[ReasonCode, ...] = (),
        late_arrival_reason: LateArrivalReason | None = None,
        payload: dict | None = None,
    ) -> OntologyEvent:
        """Append one happening. `occurred_at` is the caller's clock; the receipt
        is the writer's, and their difference is stored as `ingest_lag_seconds`
        rather than left to be derived."""
        eid = new_id(OntologyEventId)
        body = dict(payload or {})
        _require_utc(occurred_at)
        stamp, prev_hash, _ = self._stamp(
            stream="event",
            row_id=str(eid),
            columns=(
                str(eid),
                self._tenant_id,
                event_kind.value,
                subject_kind.value,
                str(subject_id),
                iso_receipt(occurred_at),
                canonical_json(body),
            ),
        )
        lag = (stamp.receipt_time - occurred_at).total_seconds()
        chain = compute_hash(
            prev_hash,
            {"event": canonical_json(body), "kind": event_kind.value},
            stamp.receipt_sequence,
            str(eid),
            None,
        )
        with self._atomic():
            return self._insert_event(
                eid=eid,
                event_kind=event_kind,
                subject_kind=subject_kind,
                subject_id=subject_id,
                occurred_at=occurred_at,
                stamp=stamp,
                lag=lag,
                late_arrival_reason=late_arrival_reason,
                actor_kind=actor_kind,
                actor_ref=actor_ref,
                reason_codes=reason_codes,
                body=body,
                prev_hash=prev_hash,
                chain=chain,
            )

    def _insert_event(
        self,
        *,
        eid: OntologyEventId,
        event_kind: EventKind,
        subject_kind: ObjectKind,
        subject_id: ObjectId,
        occurred_at: datetime,
        stamp: ReceiptStamp,
        lag: float,
        late_arrival_reason: LateArrivalReason | None,
        actor_kind: AuthorityKind,
        actor_ref: str,
        reason_codes: tuple[ReasonCode, ...],
        body: dict,
        prev_hash: str | None,
        chain: str,
    ) -> OntologyEvent:
        event = OntologyEvent(
            event_id=eid,
            tenant_id=TenantId(self._tenant_id),
            event_kind=event_kind,
            subject_kind=subject_kind,
            subject_id=subject_id,
            occurred_at=occurred_at,
            receipt=stamp,
            actor_kind=actor_kind,
            actor_ref=actor_ref,
            reason_codes=reason_codes,
            late_arrival_reason=late_arrival_reason,
            payload=body,
            prev_hash=prev_hash,
            hash=chain,
        )
        self._db.execute(
            "INSERT INTO ontology_events (event_id, tenant_id, event_kind, subject_kind, "
            "subject_id, occurred_at, receipt_time, receipt_sequence, ingest_lag_seconds, "
            "late_arrival_reason, actor_kind, actor_ref, reason_codes, payload, prev_hash, hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(eid),
                self._tenant_id,
                event_kind.value,
                subject_kind.value,
                str(subject_id),
                iso_receipt(occurred_at),
                stamp.iso,
                stamp.receipt_sequence,
                lag,
                None if late_arrival_reason is None else late_arrival_reason.value,
                actor_kind.value,
                actor_ref,
                canonical_json([c.value for c in reason_codes]),
                canonical_json(body),
                prev_hash,
                chain,
            ),
        )
        return event

    def record_identity_resolution(
        self,
        *,
        subject_kind: ObjectKind,
        source_system: str,
        source_record_id: str,
        candidates: tuple[MatchCandidate, ...],
        resolved_object_id: ObjectId | None = None,
        resolution_rule: str | None = None,
    ) -> IdentityResolution:
        """Record a set of identity hypotheses, resolved or not.

        Recording an UNRESOLVED set is the normal case and is not an error. See
        `IdentityResolution` for why forcing a 0.61/0.39 match into one record is
        the one mistake here that cannot be undone later.
        """
        csid = new_id(CandidateSetId)
        candidates_json = canonical_json(
            [
                {
                    "id": str(c.candidate_object_id),
                    "kind": c.candidate_kind.value,
                    "p": c.probability,
                    "method": c.method,
                    "evidence": list(c.evidence),
                }
                for c in candidates
            ]
        )
        columns = (
            str(csid),
            self._tenant_id,
            subject_kind.value,
            source_system,
            source_record_id,
            candidates_json,
            None if resolved_object_id is None else str(resolved_object_id),
            resolution_rule,
        )
        probe = dict(
            candidate_set_id=csid,
            tenant_id=TenantId(self._tenant_id),
            subject_kind=subject_kind,
            source_system=source_system,
            source_record_id=source_record_id,
            candidates=candidates,
            resolved_object_id=resolved_object_id,
            resolution_rule=resolution_rule,
        )
        stamp, _, _ = self._stamp(stream="identity", row_id=str(csid), columns=columns)
        with self._atomic():
            resolution = IdentityResolution(**probe, receipt=stamp)
            self._db.execute(
                "INSERT INTO ontology_identity_resolutions (candidate_set_id, tenant_id, "
                "subject_kind, source_system, source_record_id, candidates_json, "
                "resolved_object_id, resolution_rule, receipt_time, receipt_sequence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*columns, stamp.iso, stamp.receipt_sequence),
            )
        return resolution

    # ------------------------------------------------------------------ #
    # THE POINT-IN-TIME READ
    # ------------------------------------------------------------------ #
    def take_snapshot(
        self,
        *,
        as_of: datetime,
        scope: SnapshotScope,
        purpose: SnapshotPurpose = SnapshotPurpose.OPERATIONAL_DISPATCH,
    ) -> DecisionSnapshot:
        """Materialise and persist the information set as of `as_of`.

        THE BOUNDARY IS THE `receipt_time < ?` IN EVERY QUERY `_select_content`
        ISSUES. Strict `<`, as a SQL predicate over fixed-width ISO-8601 UTC
        text, evaluated identically by SQLite and PostgreSQL. A row stamped at or
        after `as_of` is not fetched and then discarded -- it is never fetched.

        `tenant_id = ?` sits BESIDE it as another conjunct of the same predicate,
        so a result is the intersection of "my tenant's rows" and "strictly in
        the past" and neither conjunct can rescue a row the other excludes.

        FACT RESOLUTION IS LATEST-PER-(subject, attribute, SOURCE). Not
        latest-per-(subject, attribute): two sources disagreeing is a real state
        of the world, and collapsing it here would hide it from the only code
        positioned to handle it. `DecisionSnapshot.conflicts()` surfaces the
        disagreement and `value_of` refuses to guess.
        """
        _require_utc(as_of)
        # ONE implementation of the predicate, shared with `load_snapshot` via
        # `_select_content`. The only difference between taking a snapshot and
        # reloading one must be the persistence, never the boundary -- two copies
        # of the `receipt_time < ?` query would make the drift check compare two
        # things that were never meant to be equal.
        facts, relationships, events, identities = self._select_content(
            as_of=as_of, scope=scope, purpose=purpose
        )
        snapshot_id = new_id(SnapshotId)
        columns = (
            str(snapshot_id),
            self._tenant_id,
            iso_receipt(as_of),
            purpose.value,
            canonical_json(scope.canonical()),
        )
        stamp, _, _ = self._stamp(
            stream="snapshot", row_id=str(snapshot_id), columns=columns
        )
        snapshot = DecisionSnapshot(
            snapshot_id=snapshot_id,
            tenant_id=TenantId(self._tenant_id),
            as_of=as_of,
            taken_receipt=stamp,
            purpose=purpose,
            scope=scope,
            facts=facts,
            relationships=relationships,
            events=events,
            identity_resolutions=identities,
        )
        self._db.execute(
            "INSERT INTO ontology_snapshots (snapshot_id, tenant_id, as_of, purpose, "
            "scope_json, content_hash, receipt_time, receipt_sequence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (*columns, snapshot.content_hash, stamp.iso, stamp.receipt_sequence),
        )
        self._db.commit()
        return snapshot

    def snapshot_content_hash(self, snapshot_id: SnapshotId) -> str | None:
        """The content hash recorded when a snapshot was taken, or None.

        Exposed so a caller holding a snapshot object can check it against the
        record WITHOUT re-deriving it, which is the cheap version of
        `load_snapshot`'s drift check. `record_action` uses the same comparison.
        """
        self._scope()
        rows = self._db.query(
            "SELECT content_hash FROM ontology_snapshots "
            "WHERE tenant_id = ? AND snapshot_id = ?",
            (self._tenant_id, str(snapshot_id)),
        )
        return rows[0][0] if rows else None

    def load_snapshot(self, snapshot_id: SnapshotId) -> DecisionSnapshot:
        """Re-derive a previously taken snapshot and PROVE it is unchanged.

        This is not a cache read. The snapshot's content was never stored -- only
        its boundary, scope, purpose and content hash were. Loading re-runs the
        same point-in-time query and compares hashes.

        That makes this method a LEAK DETECTOR. Receipt monotonicity is supposed
        to make it impossible for anything to appear before an already-taken
        boundary; if the re-derivation differs, something did, and
        `SnapshotDriftError` is raised rather than either answer being returned.
        Storing the fact list instead would have made this a tautology that could
        never fail -- which is the difference between a test and a ritual.
        """
        self._scope()
        rows = self._db.query(
            "SELECT as_of, purpose, scope_json, content_hash, receipt_time, "
            "receipt_sequence FROM ontology_snapshots "
            "WHERE tenant_id = ? AND snapshot_id = ?",
            (self._tenant_id, str(snapshot_id)),
        )
        if not rows:
            raise UnknownSnapshotError(
                f"no snapshot {snapshot_id} recorded for tenant {self._tenant_id}"
            )
        as_of_text, purpose, scope_json, stored_hash, receipt_time, sequence = rows[0]
        scope_data = json.loads(scope_json)
        scope = SnapshotScope(
            subject_ids=tuple(ObjectId(s) for s in scope_data["subject_ids"]),
            attributes=(
                None
                if scope_data["attributes"] is None
                else tuple(scope_data["attributes"])
            ),
        )
        rebuilt = self._derive(
            snapshot_id=snapshot_id,
            as_of=datetime.fromisoformat(as_of_text),
            scope=scope,
            purpose=SnapshotPurpose(purpose),
            taken_receipt=ReceiptStamp(
                receipt_time=datetime.fromisoformat(receipt_time),
                receipt_sequence=int(sequence),
            ),
        )
        if rebuilt.content_hash != stored_hash:
            raise SnapshotDriftError(
                f"snapshot {snapshot_id} re-derived to content hash "
                f"{rebuilt.content_hash} but was recorded as {stored_hash}. Something "
                "has been written into the past: receipt monotonicity should make "
                "this unreachable, so every artefact built from this snapshot is "
                "suspect"
            )
        return rebuilt

    def _derive(
        self,
        *,
        snapshot_id: SnapshotId,
        as_of: datetime,
        scope: SnapshotScope,
        purpose: SnapshotPurpose,
        taken_receipt: ReceiptStamp,
    ) -> DecisionSnapshot:
        """Rebuild a snapshot's content without persisting a new one.

        Delegating to `take_snapshot` would be wrong -- that method stamps and
        persists -- so both go through `_select_content` instead, which is the
        ONLY place the `receipt_time < ?` predicate is written. That is what
        makes the drift check in `load_snapshot` meaningful: the two sides
        compare content selected by the same boundary, so a difference can only
        come from the DATA changing, never from the query.
        """
        taken = self._select_content(as_of=as_of, scope=scope, purpose=purpose)
        return DecisionSnapshot(
            snapshot_id=snapshot_id,
            tenant_id=TenantId(self._tenant_id),
            as_of=as_of,
            taken_receipt=taken_receipt,
            purpose=purpose,
            scope=scope,
            facts=taken[0],
            relationships=taken[1],
            events=taken[2],
            identity_resolutions=taken[3],
        )

    def _select_content(
        self, *, as_of: datetime, scope: SnapshotScope, purpose: SnapshotPurpose
    ) -> tuple[
        tuple[SnapshotFact, ...],
        tuple[Relationship, ...],
        tuple[OntologyEvent, ...],
        tuple[IdentityResolution, ...],
    ]:
        """The one place the `receipt_time < ?` predicate is written.

        `take_snapshot` and `load_snapshot` both go through here, so a
        re-derivation cannot use a different boundary from the one used when the
        snapshot was taken -- which would have made the drift check compare two
        things that were never meant to be equal, and either fail spuriously or
        (worse) pass while both were wrong.
        """
        _require_utc(as_of)
        self._scope()
        boundary = iso_receipt(as_of)
        subject_ids = [str(s) for s in scope.subject_ids]
        placeholders = ", ".join("?" for _ in subject_ids)

        fact_rows = self._db.query(
            "SELECT fact_id, subject_kind, subject_id, attribute, fact_class, "
            "value_kind, value_number, value_text, value_bool, missing_reason, "
            "event_time, quality, confidence, repair_kind, repairs_fact_id, "
            "repair_note, sensitivity, special_category, legal_basis, source_system, "
            "source_record_id, receipt_time, receipt_sequence "
            "FROM ontology_facts "
            f"WHERE tenant_id = ? AND receipt_time < ? AND subject_id IN ({placeholders}) "
            "ORDER BY receipt_sequence",
            (self._tenant_id, boundary, *subject_ids),
        )
        latest: dict[tuple[str, str, str], SnapshotFact] = {}
        for row in fact_rows:
            fact = _fact_from_row(row, TenantId(self._tenant_id))
            if scope.attributes is not None and fact.attribute not in scope.attributes:
                continue
            if purpose is SnapshotPurpose.MODEL_TRAINING and not fact.trainable:
                continue
            latest[(str(fact.subject_id), fact.attribute, fact.source_system)] = fact
        facts = tuple(sorted(latest.values(), key=lambda f: f.receipt.receipt_sequence))

        relationship_rows = self._db.query(
            "SELECT relationship_id, relationship_kind, subject_kind, subject_id, "
            "object_kind, object_id, weight, valid_from, valid_to, asserted_by, "
            "retracts_relationship_id, receipt_time, receipt_sequence "
            "FROM ontology_relationships "
            "WHERE tenant_id = ? AND receipt_time < ? "
            f"AND (subject_id IN ({placeholders}) OR object_id IN ({placeholders})) "
            "ORDER BY receipt_sequence",
            (self._tenant_id, boundary, *subject_ids, *subject_ids),
        )
        retracted = {row[10] for row in relationship_rows if row[10] is not None}
        relationships = tuple(
            _relationship_from_row(row, TenantId(self._tenant_id))
            for row in relationship_rows
            if row[0] not in retracted and row[10] is None
        )

        event_rows = self._db.query(
            "SELECT event_id, event_kind, subject_kind, subject_id, occurred_at, "
            "receipt_time, receipt_sequence, late_arrival_reason, actor_kind, "
            "actor_ref, reason_codes, payload, prev_hash, hash "
            "FROM ontology_events "
            f"WHERE tenant_id = ? AND receipt_time < ? AND subject_id IN ({placeholders}) "
            "ORDER BY receipt_sequence",
            (self._tenant_id, boundary, *subject_ids),
        )
        events = tuple(
            _event_from_row(row, TenantId(self._tenant_id)) for row in event_rows
        )

        identity_rows = self._db.query(
            "SELECT candidate_set_id, subject_kind, source_system, source_record_id, "
            "candidates_json, resolved_object_id, resolution_rule, receipt_time, "
            "receipt_sequence FROM ontology_identity_resolutions "
            "WHERE tenant_id = ? AND receipt_time < ? ORDER BY receipt_sequence",
            (self._tenant_id, boundary),
        )
        scoped = set(subject_ids)
        identities = tuple(
            res
            for res in (
                _identity_from_row(row, TenantId(self._tenant_id))
                for row in identity_rows
            )
            if any(str(c.candidate_object_id) in scoped for c in res.candidates)
        )
        return facts, relationships, events, identities

    # ------------------------------------------------------------------ #
    # Actions: the only way an effect is recorded
    # ------------------------------------------------------------------ #
    def record_action(
        self,
        *,
        action_kind: ActionKind,
        subject_kind: ObjectKind,
        subject_id: ObjectId,
        input_snapshot: DecisionSnapshot,
        policy_id: PolicyId,
        policy_version: int,
        authority: Authority,
        decided_at: datetime,
        alternatives: tuple[ActionAlternative, ...],
        verifier: VerifierResult,
        prediction: ActionPrediction | None = None,
        override_justification: str | None = None,
        reason_codes: tuple[ReasonCode, ...] = (),
    ) -> ActionRecord:
        """Record one typed, permissioned operation.

        THREE GATES, IN THIS ORDER, AND THE ORDER MATTERS.
          1. The snapshot must have been TAKEN BY THIS STORE (its row exists).
             An action citing an information set nobody recorded is unauditable.
          2. The snapshot object's `content_hash` must match the recorded one.
             This is what catches a `model_copy(update=...)` forgery -- pydantic
             skips validators on that path by design, so a snapshot with extra
             facts or a later `as_of` is one line away, and only this comparison
             sees it.
          3. `ActionRecord`'s own validators check the permission, the human-
             authority rule for approve/reject, and `decided_at >= as_of`.

        Gate 2 before gate 3 because a forged snapshot could otherwise satisfy
        gate 3 trivially by moving its own `as_of`.
        """
        _require_utc(decided_at)
        self._scope()
        rows = self._db.query(
            "SELECT content_hash FROM ontology_snapshots "
            "WHERE tenant_id = ? AND snapshot_id = ?",
            (self._tenant_id, str(input_snapshot.snapshot_id)),
        )
        if not rows:
            raise UnknownSnapshotError(
                f"action cites snapshot {input_snapshot.snapshot_id}, which this store "
                "never recorded. An action with no recorded information set is "
                "unauditable and untrainable"
            )
        if rows[0][0] != input_snapshot.content_hash:
            raise ForgedSnapshotError(
                f"snapshot {input_snapshot.snapshot_id} was recorded with content hash "
                f"{rows[0][0]} but the object presented hashes to "
                f"{input_snapshot.content_hash}. It has been modified since it was "
                "taken -- `model_copy(update=...)` skips pydantic validators, which is "
                "exactly what this comparison exists to catch"
            )
        input_snapshot.verify()

        aid = new_id(ActionId)
        alternatives_json = canonical_json(
            [
                {
                    "rank": a.rank,
                    "kind": a.candidate_kind.value,
                    "id": None if a.candidate_id is None else str(a.candidate_id),
                    "feasible": a.feasible,
                    "failed": [c.value for c in a.failed_constraints],
                    "delta": a.objective_delta,
                }
                for a in sorted(alternatives, key=lambda a: a.rank)
            ]
        )
        prediction_json = (
            None
            if prediction is None
            else canonical_json(
                {
                    "metric": prediction.metric,
                    "point": prediction.point_estimate,
                    "low": prediction.interval_low,
                    "high": prediction.interval_high,
                    "model": (
                        None
                        if prediction.model_version_id is None
                        else str(prediction.model_version_id)
                    ),
                }
            )
        )
        columns = (
            str(aid),
            self._tenant_id,
            action_kind.value,
            subject_kind.value,
            str(subject_id),
            str(input_snapshot.snapshot_id),
            input_snapshot.content_hash,
            iso_receipt(input_snapshot.as_of),
            str(policy_id),
            policy_version,
            alternatives_json,
            prediction_json,
            verifier.verdict.value,
            verifier.verifier_name,
            verifier.verifier_version,
            canonical_json(list(verifier.violated_rules)),
            override_justification,
            authority.authority_kind.value,
            authority.actor_ref,
            authority.role,
            canonical_json(sorted(p.value for p in authority.permissions)),
            authority.on_behalf_of,
            iso_receipt(decided_at),
            canonical_json([c.value for c in reason_codes]),
        )
        probe = dict(
            action_id=aid,
            tenant_id=TenantId(self._tenant_id),
            action_kind=action_kind,
            subject_kind=subject_kind,
            subject_id=subject_id,
            input_snapshot_id=input_snapshot.snapshot_id,
            input_snapshot_hash=input_snapshot.content_hash,
            input_snapshot_as_of=input_snapshot.as_of,
            policy_id=policy_id,
            policy_version=policy_version,
            alternatives=alternatives,
            prediction=prediction,
            verifier=verifier,
            override_justification=override_justification,
            authority=authority,
            decided_at=decided_at,
            reason_codes=reason_codes,
        )
        stamp, prev_hash, chain = self._stamp(
            stream="action", row_id=str(aid), columns=columns
        )
        with self._atomic():
            # `ActionRecord`'s validators run HERE: the permission check, the
            # human-authority rule for approve/reject, `decided_at >= as_of` and
            # the verifier-override rule. A refusal rolls back the ledger row too.
            action = ActionRecord(
                **probe, receipt=stamp, prev_hash=prev_hash, hash=chain
            )
            self._db.execute(
                "INSERT INTO ontology_actions (action_id, tenant_id, action_kind, "
                "subject_kind, subject_id, input_snapshot_id, input_snapshot_hash, "
                "input_snapshot_as_of, policy_id, policy_version, alternatives_json, "
                "prediction_json, verifier_verdict, verifier_name, verifier_version, "
                "violated_rules_json, override_justification, authority_kind, authority_ref, "
                "authority_role, authority_permissions_json, authority_on_behalf_of, "
                "decided_at, reason_codes, receipt_time, receipt_sequence, prev_hash, hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*columns, stamp.iso, stamp.receipt_sequence, prev_hash, chain),
            )
        return action

    def record_outcome(
        self,
        *,
        action_id: ActionId,
        metric: str,
        value: float,
        observed_at: datetime,
        source_system: str,
        source_record_id: str | None = None,
    ) -> ActionOutcome:
        """Record what eventually happened after an action.

        A SEPARATE ROW, never a column on the action -- see `ActionOutcome`. Its
        receipt time is necessarily later than the action's, which is the
        mechanism by which a label cannot leak into the features of the decision
        that produced it. `horizon_seconds` is measured from the action's own
        `decided_at`, read back here rather than passed in, so it cannot be
        misstated.
        """
        _require_utc(observed_at)
        self._scope()
        rows = self._db.query(
            "SELECT decided_at FROM ontology_actions WHERE tenant_id = ? AND action_id = ?",
            (self._tenant_id, str(action_id)),
        )
        if not rows:
            raise LookupError(f"no action {action_id} recorded for this tenant")
        decided_at = datetime.fromisoformat(rows[0][0])
        horizon = max(0.0, (observed_at - decided_at).total_seconds())
        oid = new_id(OutcomeId)
        columns = (
            str(oid),
            self._tenant_id,
            str(action_id),
            metric,
            float(value),
            iso_receipt(observed_at),
            horizon,
            source_system,
            source_record_id,
        )
        stamp, _, _ = self._stamp(stream="outcome", row_id=str(oid), columns=columns)
        with self._atomic():
            outcome = ActionOutcome(
                outcome_id=oid,
                tenant_id=TenantId(self._tenant_id),
                action_id=action_id,
                metric=metric,
                value=float(value),
                observed_at=observed_at,
                receipt=stamp,
                horizon_seconds=horizon,
                source_system=source_system,
                source_record_id=source_record_id,
            )
            self._db.execute(
                "INSERT INTO ontology_action_outcomes (outcome_id, tenant_id, action_id, "
                "metric, value, observed_at, horizon_seconds, source_system, "
                "source_record_id, receipt_time, receipt_sequence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*columns, stamp.iso, stamp.receipt_sequence),
            )
        return outcome

    # ------------------------------------------------------------------ #
    # Audit views. NOT on the snapshot -- see below.
    # ------------------------------------------------------------------ #
    def fact_history(
        self, subject_id: ObjectId, attribute: str
    ) -> tuple[SnapshotFact, ...]:
        """Every version of one attribute ever recorded, in receipt order.

        DELIBERATELY APPLIES NO TIME FILTER, and deliberately lives on the STORE
        rather than on `DecisionSnapshot`. This is the audit view: it shows
        everything, including facts a point-in-time read would refuse to show.
        Putting it on the snapshot would have handed every holder of a snapshot a
        method that reaches past the boundary the snapshot exists to enforce --
        which is precisely the "read path other than the obvious one" a leakage
        test must cover. It still applies the TENANT filter; an audit view is an
        audit view of one operator's own writes, never of everyone's.
        """
        self._scope()
        rows = self._db.query(
            "SELECT fact_id, subject_kind, subject_id, attribute, fact_class, "
            "value_kind, value_number, value_text, value_bool, missing_reason, "
            "event_time, quality, confidence, repair_kind, repairs_fact_id, "
            "repair_note, sensitivity, special_category, legal_basis, source_system, "
            "source_record_id, receipt_time, receipt_sequence "
            "FROM ontology_facts WHERE tenant_id = ? AND subject_id = ? AND attribute = ? "
            "ORDER BY receipt_sequence",
            (self._tenant_id, str(subject_id), attribute),
        )
        return tuple(_fact_from_row(row, TenantId(self._tenant_id)) for row in rows)

    def receipt_watermark(self) -> ReceiptStamp | None:
        """The newest stamp issued to this tenant. Nothing may ever be inserted
        before it -- that is the invariant that makes an information set final."""
        self._scope()
        stamp, _ = self._head()
        return stamp

    def verify_integrity(self) -> IntegrityReport:
        """Walk the receipt ledger, recompute every link, and re-derive every
        referenced row's digest from the row as it stands NOW.

        The third and last layer of the append-only defence, and the only one
        that survives an attacker who can drop a trigger. It is tamper EVIDENCE,
        not authentication: there is no secret in the hash, so a party who can
        write can also recompute. What it catches is a row changed WITHOUT
        recomputation -- a direct UPDATE, a backup edited offline, a replica
        diverging, a restore from a tampered dump.
        """
        self._scope()
        rows = self._db.query(
            "SELECT receipt_sequence, receipt_time, stream, row_id, row_hash, "
            "prev_hash, hash FROM ontology_receipt_log WHERE tenant_id = ? "
            "ORDER BY receipt_sequence",
            (self._tenant_id,),
        )
        breaks: list[int] = []
        mismatches: list[tuple[str, str]] = []
        expected_prev: str | None = None
        for sequence, _receipt_time, stream, row_id, row_hash, prev_hash, chain in rows:
            recomputed = compute_hash(
                prev_hash,
                {"stream": stream, "row_hash": row_hash},
                int(sequence),
                row_id,
                None,
            )
            if recomputed != chain or prev_hash != expected_prev:
                breaks.append(int(sequence))
            expected_prev = chain
            current = self._row_columns(stream, row_id)
            if current is None:
                mismatches.append((stream, row_id))
            elif _row_digest(current) != row_hash:
                mismatches.append((stream, row_id))
        return IntegrityReport(
            rows_checked=len(rows),
            chain_breaks=tuple(breaks),
            row_mismatches=tuple(mismatches),
        )

    def _row_columns(self, stream: str, row_id: str) -> tuple | None:
        """Read back the exact column list a stream's digest was computed over.

        The column ORDER here must match the write path's `columns` tuple
        exactly; a conformance test writes one row per stream and asserts
        `verify_integrity` reports zero mismatches, so a drift between the two
        lists fails loudly rather than turning verification into a no-op that
        always reports tampering (or, worse, one that always reports none).
        """
        select = {
            "object": (
                "SELECT object_id, tenant_id, object_kind, external_ref, source_system "
                "FROM ontology_objects WHERE tenant_id = ? AND object_id = ?"
            ),
            "relationship": (
                "SELECT relationship_id, tenant_id, relationship_kind, subject_kind, "
                "subject_id, object_kind, object_id, weight, valid_from, valid_to, "
                "asserted_by, retracts_relationship_id FROM ontology_relationships "
                "WHERE tenant_id = ? AND relationship_id = ?"
            ),
            "fact": (
                "SELECT fact_id, tenant_id, subject_kind, subject_id, attribute, "
                "fact_class, value_kind, value_number, value_text, value_bool, "
                "missing_reason, event_time, quality, confidence, repair_kind, "
                "repairs_fact_id, repair_note, sensitivity, special_category, "
                "legal_basis, source_system, source_record_id FROM ontology_facts "
                "WHERE tenant_id = ? AND fact_id = ?"
            ),
            "event": (
                "SELECT event_id, tenant_id, event_kind, subject_kind, subject_id, "
                "occurred_at, payload FROM ontology_events "
                "WHERE tenant_id = ? AND event_id = ?"
            ),
            "identity": (
                "SELECT candidate_set_id, tenant_id, subject_kind, source_system, "
                "source_record_id, candidates_json, resolved_object_id, resolution_rule "
                "FROM ontology_identity_resolutions "
                "WHERE tenant_id = ? AND candidate_set_id = ?"
            ),
            "snapshot": (
                "SELECT snapshot_id, tenant_id, as_of, purpose, scope_json "
                "FROM ontology_snapshots WHERE tenant_id = ? AND snapshot_id = ?"
            ),
            "action": (
                "SELECT action_id, tenant_id, action_kind, subject_kind, subject_id, "
                "input_snapshot_id, input_snapshot_hash, input_snapshot_as_of, policy_id, "
                "policy_version, alternatives_json, prediction_json, verifier_verdict, "
                "verifier_name, verifier_version, violated_rules_json, "
                "override_justification, authority_kind, authority_ref, authority_role, "
                "authority_permissions_json, authority_on_behalf_of, decided_at, "
                "reason_codes FROM ontology_actions WHERE tenant_id = ? AND action_id = ?"
            ),
            "outcome": (
                "SELECT outcome_id, tenant_id, action_id, metric, value, observed_at, "
                "horizon_seconds, source_system, source_record_id "
                "FROM ontology_action_outcomes WHERE tenant_id = ? AND outcome_id = ?"
            ),
        }[stream]
        rows = self._db.query(select, (self._tenant_id, row_id))
        return tuple(rows[0]) if rows else None


# --------------------------------------------------------------------------- #
# Row -> model reconstruction. Free functions so both `take_snapshot` and
# `load_snapshot` reach the same code and cannot drift.
# --------------------------------------------------------------------------- #
def _fact_from_row(row: Sequence[Any], tenant_id: TenantId) -> SnapshotFact:
    (
        fact_id,
        subject_kind,
        subject_id,
        attribute,
        fact_class,
        value_kind,
        value_number,
        value_text,
        value_bool,
        missing_reason,
        event_time,
        quality,
        confidence,
        repair_kind,
        repairs_fact_id,
        repair_note,
        sensitivity,
        special_category,
        legal_basis,
        source_system,
        source_record_id,
        receipt_time,
        receipt_sequence,
    ) = row
    if value_kind == "number":
        value: Any = float(value_number)
    elif value_kind == "text":
        value = value_text
    elif value_kind == "bool":
        value = bool(value_bool)
    else:
        value = None
    return SnapshotFact(
        fact_id=FactId(fact_id),
        tenant_id=tenant_id,
        subject_kind=ObjectKind(subject_kind),
        subject_id=ObjectId(subject_id),
        attribute=attribute,
        value=value,
        missing_reason=(
            None if missing_reason is None else MissingnessReason(missing_reason)
        ),
        fact_class=FactClass(fact_class),
        event_time=None if event_time is None else datetime.fromisoformat(event_time),
        receipt=ReceiptStamp(
            receipt_time=datetime.fromisoformat(receipt_time),
            receipt_sequence=int(receipt_sequence),
        ),
        quality=QualityState(quality),
        confidence=None if confidence is None else float(confidence),
        repair_kind=RepairKind(repair_kind),
        repairs_fact_id=None if repairs_fact_id is None else FactId(repairs_fact_id),
        repair_note=repair_note,
        sensitivity=SensitivityClass(sensitivity),
        special_category=bool(special_category),
        legal_basis=LegalBasis(legal_basis),
        source_system=source_system,
        source_record_id=source_record_id,
    )


def _relationship_from_row(row: Sequence[Any], tenant_id: TenantId) -> Relationship:
    (
        relationship_id,
        relationship_kind,
        subject_kind,
        subject_id,
        object_kind,
        object_id,
        weight,
        valid_from,
        valid_to,
        asserted_by,
        retracts,
        receipt_time,
        receipt_sequence,
    ) = row
    return Relationship(
        relationship_id=RelationshipId(relationship_id),
        tenant_id=tenant_id,
        relationship_kind=RelationshipKind(relationship_kind),
        subject_kind=ObjectKind(subject_kind),
        subject_id=ObjectId(subject_id),
        object_kind=ObjectKind(object_kind),
        object_id=ObjectId(object_id),
        weight=None if weight is None else float(weight),
        valid_from=None if valid_from is None else datetime.fromisoformat(valid_from),
        valid_to=None if valid_to is None else datetime.fromisoformat(valid_to),
        asserted_by=asserted_by,
        retracts_relationship_id=(
            None if retracts is None else RelationshipId(retracts)
        ),
        receipt=ReceiptStamp(
            receipt_time=datetime.fromisoformat(receipt_time),
            receipt_sequence=int(receipt_sequence),
        ),
    )


def _event_from_row(row: Sequence[Any], tenant_id: TenantId) -> OntologyEvent:
    (
        event_id,
        event_kind,
        subject_kind,
        subject_id,
        occurred_at,
        receipt_time,
        receipt_sequence,
        late_arrival_reason,
        actor_kind,
        actor_ref,
        reason_codes,
        payload,
        prev_hash,
        chain,
    ) = row
    return OntologyEvent(
        event_id=OntologyEventId(event_id),
        tenant_id=tenant_id,
        event_kind=EventKind(event_kind),
        subject_kind=ObjectKind(subject_kind),
        subject_id=ObjectId(subject_id),
        occurred_at=datetime.fromisoformat(occurred_at),
        receipt=ReceiptStamp(
            receipt_time=datetime.fromisoformat(receipt_time),
            receipt_sequence=int(receipt_sequence),
        ),
        actor_kind=AuthorityKind(actor_kind),
        actor_ref=actor_ref,
        reason_codes=tuple(ReasonCode(c) for c in json.loads(reason_codes)),
        late_arrival_reason=(
            None if late_arrival_reason is None else LateArrivalReason(late_arrival_reason)
        ),
        payload=json.loads(payload),
        prev_hash=prev_hash,
        hash=chain,
    )


def _identity_from_row(row: Sequence[Any], tenant_id: TenantId) -> IdentityResolution:
    (
        candidate_set_id,
        subject_kind,
        source_system,
        source_record_id,
        candidates_json,
        resolved_object_id,
        resolution_rule,
        receipt_time,
        receipt_sequence,
    ) = row
    candidates = tuple(
        MatchCandidate(
            candidate_object_id=ObjectId(c["id"]),
            candidate_kind=ObjectKind(c["kind"]),
            probability=float(c["p"]),
            method=c["method"],
            evidence=tuple(c["evidence"]),
        )
        for c in json.loads(candidates_json)
    )
    return IdentityResolution(
        candidate_set_id=CandidateSetId(candidate_set_id),
        tenant_id=tenant_id,
        subject_kind=ObjectKind(subject_kind),
        source_system=source_system,
        source_record_id=source_record_id,
        candidates=candidates,
        resolved_object_id=(
            None if resolved_object_id is None else ObjectId(resolved_object_id)
        ),
        resolution_rule=resolution_rule,
        receipt=ReceiptStamp(
            receipt_time=datetime.fromisoformat(receipt_time),
            receipt_sequence=int(receipt_sequence),
        ),
    )
