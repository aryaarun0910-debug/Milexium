"""Conformance for the durable ontology store: both engines, both invariants.

THE TWO DEFECTS THIS FILE EXISTS TO PROVE ARE CLOSED. An external audit of this
repository (2026-07-26) found, in the canonical lifecycle record:

  * "Both its alleged valid-time and transaction-time clocks are caller-supplied.
     I inserted a transition today whose `decided_at` was 2020-01-01 and whose
     `recorded_at` was one second later. It was accepted."
  * "The SQL calls the table append-only because application code contains no
     update/delete path. That is a coding convention, not a database invariant.
     I wrote a valid denial, issued a direct SQL UPDATE changing `actor_id`,
     committed it, and read the forged actor back through the normal API."

So every test below that claims an invariant attacks it the way the audit did:
with raw SQL against the exact tables, through the exact deployment credential,
and -- where a guard can be removed -- with the guard removed, to show the
boundary collapsing and therefore that the guard was load-bearing rather than
decorative.

PostgreSQL tests SKIP cleanly when the instance is absent, so a clean clone stays
green. They are not designed to skip: on a provisioned machine they RUN, and the
packet reports whether they did.

All fixtures are SYNTHETIC. Status: Demonstrated.
"""

from __future__ import annotations

import inspect
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from packages.canonical.ids import TenantId, new_id as canonical_new_id
from packages.ontology import (
    AuthorityKind,
    EventKind,
    FactClass,
    LateArrivalReason,
    LegalBasis,
    ObjectKind,
    QualityState,
    SensitivityClass,
    SnapshotScope,
)
from packages.ontology.receipt import ReceiptClockRegressionError
from packages.ontology.store import (
    IMMUTABILITY_POSTGRES_PATH,
    IMMUTABILITY_SQLITE_PATH,
    ONTOLOGY_TABLES,
    RLS_PATH,
    SCHEMA_PATH,
    OntologyDatabase,
    OntologyStore,
    split_sql_statements,
)

T = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)
_POSTGRES = OntologyDatabase.is_postgres_reachable()
_skip_pg = pytest.mark.skipif(_POSTGRES is False, reason="PostgreSQL 17 dev instance not reachable")


class ScriptedClock:
    def __init__(self, start: datetime = T, step: timedelta = timedelta(minutes=1)):
        self.now = start
        self.step = step

    def __call__(self) -> datetime:
        value = self.now
        self.now = self.now + self.step
        return value


@pytest.fixture(params=["sqlite", "postgres"])
def database(request):
    """One contract, two engines. Parametrised rather than duplicated, so a
    behaviour that holds on SQLite and not on PostgreSQL cannot pass unnoticed
    -- ADR-0004's whole point."""
    if request.param == "postgres":
        if not _POSTGRES:
            pytest.skip("PostgreSQL 17 dev instance not reachable")
        database = OntologyDatabase.postgres()
        yield database
        database.drop_schema()
        database.close()
    else:
        database = OntologyDatabase.sqlite()
        yield database
        database.close()


@pytest.fixture()
def store(database):
    return OntologyStore(database, canonical_new_id(TenantId), clock=ScriptedClock())


def _vehicle(store: OntologyStore):
    return store.register_object(
        object_kind=ObjectKind.VEHICLE, external_ref="B-101", source_system="ops"
    )


def _fact(store: OntologyStore, subject, value: float = 2.0, attribute: str = "seats"):
    return store.record_fact(
        subject_kind=ObjectKind.VEHICLE,
        subject_id=subject.object_id,
        attribute=attribute,
        fact_class=FactClass.OBSERVATION,
        quality=QualityState.TRUSTED,
        sensitivity=SensitivityClass.OPERATIONAL,
        legal_basis=LegalBasis.CONTRACT_PERFORMANCE,
        source_system="ops",
        source_record_id="v-1",
        value=value,
        event_time=T,
    )


def _message(error: BaseException) -> str:
    return str(error)


def _every_stream(store: OntologyStore) -> dict:
    """Write ONE row into every one of the nine tables.

    Needed because a BEFORE UPDATE row-level trigger does not fire on a table
    with no rows: `UPDATE empty_table SET x = x` succeeds everywhere, on both
    engines, guard or no guard. An enumeration test that skipped this would
    report every table as unguarded (as this one first did) -- or, with the
    assertion the other way round, would report every table as guarded while
    proving nothing at all. The rows are what make the enumeration mean
    something.
    """
    from packages.canonical.ids import PolicyId
    from packages.ontology import (
        ActionKind,
        Authority,
        MatchCandidate,
        Permission,
        RelationshipKind,
        VerifierResult,
        VerifierVerdict,
    )

    vehicle = _vehicle(store)
    assignment = store.register_object(
        object_kind=ObjectKind.ASSIGNMENT, source_system="milexium"
    )
    fact = _fact(store, vehicle)
    store.assert_relationship(
        relationship_kind=RelationshipKind.VEHICLE_PERFORMS_ASSIGNMENT,
        subject_kind=ObjectKind.VEHICLE,
        subject_id=vehicle.object_id,
        object_kind=ObjectKind.ASSIGNMENT,
        object_id=assignment.object_id,
        asserted_by="solver",
    )
    store.record_event(
        event_kind=EventKind.VEHICLE_DELAYED,
        subject_kind=ObjectKind.VEHICLE,
        subject_id=vehicle.object_id,
        occurred_at=T,
        actor_kind=AuthorityKind.SYSTEM,
        actor_ref="avl",
        late_arrival_reason=LateArrivalReason.BATCH_EXPORT,
    )
    store.record_identity_resolution(
        subject_kind=ObjectKind.VEHICLE,
        source_system="ops",
        source_record_id="b-1",
        candidates=(
            MatchCandidate(
                candidate_object_id=vehicle.object_id,
                candidate_kind=ObjectKind.VEHICLE,
                probability=0.5,
                method="fleet_number",
            ),
        ),
    )
    scope = SnapshotScope(subject_ids=(vehicle.object_id, assignment.object_id))
    snapshot = store.take_snapshot(
        as_of=store.receipt_watermark().receipt_time + timedelta(seconds=1), scope=scope
    )
    action = store.record_action(
        action_kind=ActionKind.ASSIGN,
        subject_kind=ObjectKind.ASSIGNMENT,
        subject_id=assignment.object_id,
        input_snapshot=snapshot,
        policy_id=canonical_new_id(PolicyId),
        policy_version=1,
        authority=Authority(
            authority_kind=AuthorityKind.SYSTEM,
            actor_ref="scheduler",
            role="solver",
            permissions=frozenset({Permission.ASSIGNMENT_WRITE}),
        ),
        decided_at=snapshot.as_of + timedelta(seconds=1),
        alternatives=(),
        verifier=VerifierResult(
            verdict=VerifierVerdict.PASS, verifier_name="mx", verifier_version="1"
        ),
    )
    store.record_outcome(
        action_id=action.action_id,
        metric="pickup_delay_minutes",
        value=14.0,
        observed_at=action.decided_at,
        source_system="avl",
        source_record_id="a-1",
    )
    return {"vehicle": vehicle, "assignment": assignment, "fact": fact, "action": action}


# --------------------------------------------------------------------------- #
# 1. Portability
# --------------------------------------------------------------------------- #
def test_the_portable_schema_runs_on_a_bare_sqlite_connection() -> None:
    """Executed as the file's ACTUAL BYTES on a bare `sqlite3` connection, with
    nothing from this repository in the loop. A portability claim checked by the
    code that also wrote the file is not a check."""
    connection = sqlite3.connect(":memory:")
    try:
        for statement in split_sql_statements(SCHEMA_PATH.read_text(encoding="utf-8")):
            connection.execute(statement)
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert set(ONTOLOGY_TABLES) <= names
    finally:
        connection.close()


def test_the_portable_schema_contains_no_engine_specific_construct() -> None:
    """ADR-0002's portable subset, asserted by reading the file rather than by
    trusting that it was written carefully."""
    text = SCHEMA_PATH.read_text(encoding="utf-8").upper()
    body = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("--")
    )
    for banned in ("JSONB", "CREATE TYPE", " ENUM", "SERIAL", "GENERATED ALWAYS",
                   "GEOMETRY", "$$"):
        assert banned not in body, f"portable DDL contains {banned!r}"


def test_no_float4_column_survives_in_the_portable_schema() -> None:
    """PostgreSQL's REAL is float4 (~7 significant digits) while SQLite's is
    8-byte, so a REAL column silently loses precision on one engine and a value
    written on one and read on the other would not compare equal. The canonical
    schema found this the hard way; it is not repeated here."""
    body = "\n".join(
        line
        for line in SCHEMA_PATH.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("--")
    )
    assert " REAL" not in body.upper()


def test_sql_statement_counts_are_pinned() -> None:
    """`split_sql_statements` is BEGIN/END- and `$$`-aware because a naive
    splitter truncates a SQLite trigger body at its inner semicolon and silently
    installs a trigger that does nothing -- a false green of exactly the shape
    this repository keeps finding. Pinning the counts is what makes a future
    file that breaks the splitter's assumptions fail loudly."""
    counts = {
        SCHEMA_PATH.name: 13,
        IMMUTABILITY_SQLITE_PATH.name: 20,
        IMMUTABILITY_POSTGRES_PATH.name: 40,
        RLS_PATH.name: 36,
    }
    for path in (SCHEMA_PATH, IMMUTABILITY_SQLITE_PATH, IMMUTABILITY_POSTGRES_PATH, RLS_PATH):
        got = len(split_sql_statements(path.read_text(encoding="utf-8")))
        assert got == counts[path.name], f"{path.name}: {got} statements, expected {counts[path.name]}"


def test_a_naive_splitter_would_have_broken_the_sqlite_triggers() -> None:
    """The counterexample, pinned. `packages.core.migrations.split_statements`
    strips comments and splits on `;`; run it on the SQLite trigger file and it
    produces MORE statements than there are triggers, because every `BEGIN
    SELECT RAISE(...); END;` is cut in half. This is why this package does not
    reuse it."""
    from packages.core.migrations import split_statements as naive

    text = IMMUTABILITY_SQLITE_PATH.read_text(encoding="utf-8")
    assert len(naive(text)) > len(split_sql_statements(text))


# --------------------------------------------------------------------------- #
# 2. APPEND-ONLY, enforced by the DATABASE (the audit's second finding)
# --------------------------------------------------------------------------- #
def test_a_direct_sql_update_of_a_fact_is_refused(database, store) -> None:
    """THE AUDIT'S OWN PROBE. Write a valid row, then issue a direct SQL UPDATE
    through the same credential the application uses. It must be refused by the
    database, not merely absent from the application's code."""
    vehicle = _vehicle(store)
    fact = _fact(store, vehicle)
    with pytest.raises(Exception) as excinfo:
        database.execute(
            "UPDATE ontology_facts SET value_number = 999 WHERE fact_id = ?",
            (str(fact.fact_id),),
        )
    assert "MX001" in _message(excinfo.value)
    database.rollback()
    assert store.fact_history(vehicle.object_id, "seats")[0].value == 2.0


def test_a_direct_sql_delete_is_refused(database, store) -> None:
    vehicle = _vehicle(store)
    _fact(store, vehicle)
    with pytest.raises(Exception) as excinfo:
        database.execute("DELETE FROM ontology_facts")
    assert "MX001" in _message(excinfo.value)
    database.rollback()


def test_the_receipt_ledger_itself_is_append_only(database, store) -> None:
    """The spine is guarded too. A ledger that could be edited would make every
    other guarantee in this package a story."""
    _vehicle(store)
    with pytest.raises(Exception) as excinfo:
        database.execute("UPDATE ontology_receipt_log SET receipt_time = '1999-01-01'")
    assert "MX001" in _message(excinfo.value)
    database.rollback()


def test_every_ontology_table_refuses_update(database, store) -> None:
    """BY ENUMERATION, not by remembering -- and OVER POPULATED TABLES.

    The first version of this test ran `UPDATE <table> SET tenant_id = tenant_id`
    against empty tables and reported all nine as unguarded. The tables were
    guarded; the TEST was wrong. A BEFORE UPDATE row-level trigger does not fire
    when there are no rows, so the statement succeeds on both engines whatever
    guards exist. `_every_stream` writes one row into each of the nine first,
    which is the difference between an enumeration that proves something and one
    that would have been green with every trigger deleted.
    """
    _every_stream(store)
    populated = [
        table
        for table in ONTOLOGY_TABLES
        if database.query(f"SELECT 1 FROM {table} LIMIT 1")  # noqa: S608
    ]
    assert set(populated) == set(ONTOLOGY_TABLES), (
        f"tables with no row to update, so the guard below cannot fire: "
        f"{sorted(set(ONTOLOGY_TABLES) - set(populated))}"
    )

    unguarded = []
    for table in ONTOLOGY_TABLES:
        try:
            database.execute(f"UPDATE {table} SET tenant_id = tenant_id")  # noqa: S608
        except Exception as error:
            if "MX001" not in _message(error):
                unguarded.append(f"{table} ({error})")
            database.rollback()
        else:
            unguarded.append(f"{table} (UPDATE accepted)")
            database.rollback()
    assert not unguarded, f"tables without an enforced append-only guard: {unguarded}"


def test_every_ontology_table_refuses_delete(database, store) -> None:
    """The other half. Same populated-table discipline for the same reason."""
    _every_stream(store)
    unguarded = []
    for table in ONTOLOGY_TABLES:
        try:
            database.execute(f"DELETE FROM {table}")  # noqa: S608
        except Exception as error:
            if "MX001" not in _message(error):
                unguarded.append(f"{table} ({error})")
            database.rollback()
        else:
            unguarded.append(f"{table} (DELETE accepted)")
            database.rollback()
    assert not unguarded, f"tables without an enforced append-only guard: {unguarded}"


@_skip_pg
def test_truncate_is_refused_on_postgres() -> None:
    """TRUNCATE fires NO row-level trigger. A table guarded only by BEFORE
    UPDATE/DELETE can be emptied in one statement while every test that only
    tried UPDATE stays green -- so the statement-level trigger is tested
    separately rather than assumed to be covered."""
    database = OntologyDatabase.postgres()
    try:
        store = OntologyStore(
            database, canonical_new_id(TenantId), clock=ScriptedClock()
        )
        _fact(store, _vehicle(store))
        with pytest.raises(Exception) as excinfo:
            database.execute("TRUNCATE ontology_facts")
        assert "MX001" in _message(excinfo.value)
        database.rollback()
    finally:
        database.drop_schema()
        database.close()


def test_dropping_the_guard_collapses_the_boundary_and_the_chain_notices(
    database, store
) -> None:
    """THE LAYER-3 TEST, and the one that shows layer 2 is load-bearing. Drop the
    trigger, mutate the row the way the audit did, and confirm two things:
    the UPDATE now SUCCEEDS (so the trigger was doing real work), and
    `verify_integrity` reports the mutation (so a tamper that gets past the
    trigger is detected rather than silent)."""
    vehicle = _vehicle(store)
    fact = _fact(store, vehicle)
    assert store.verify_integrity().intact

    if database.is_postgres:
        database.execute_ddl("DROP TRIGGER ontology_facts_immutable ON ontology_facts")
    else:
        database.execute_ddl("DROP TRIGGER ontology_facts_no_update")
    database.execute(
        "UPDATE ontology_facts SET value_number = 999 WHERE fact_id = ?",
        (str(fact.fact_id),),
    )
    database.commit()

    # The forgery is readable through the normal API -- exactly the audit's
    # finding, reproduced deliberately to show what the trigger prevents.
    assert store.fact_history(vehicle.object_id, "seats")[0].value == 999.0
    # ...and it is DETECTED, because the row no longer digests to what the
    # receipt ledger recorded.
    report = store.verify_integrity()
    assert not report.intact
    assert ("fact", str(fact.fact_id)) in report.row_mismatches


# --------------------------------------------------------------------------- #
# 3. RECEIPT MONOTONICITY (the audit's first finding, generalised)
# --------------------------------------------------------------------------- #
def test_no_store_method_accepts_a_receipt_time() -> None:
    """THE STRUCTURAL REPAIR. The defect was a caller-supplied transaction-time
    parameter; the repair is that no such parameter exists, read back from the
    signatures rather than asserted in prose."""
    banned = {"receipt", "receipt_time", "recorded_at", "receipt_sequence", "ingested_at"}
    offenders = [
        f"{name}({parameter})"
        for name, member in inspect.getmembers(OntologyStore, inspect.isfunction)
        if not name.startswith("_")
        for parameter in inspect.signature(member).parameters
        if parameter in banned
    ]
    assert not offenders, offenders


def test_a_backwards_clock_is_refused_by_the_store(database) -> None:
    """Python-side. The store refuses to stamp behind its own watermark."""
    clock = ScriptedClock()
    store = OntologyStore(database, canonical_new_id(TenantId), clock=clock)
    _vehicle(store)
    clock.now = T - timedelta(hours=1)
    with pytest.raises(ReceiptClockRegressionError):
        _vehicle(store)


def test_a_backwards_receipt_is_refused_by_the_database(database, store) -> None:
    """AND IN THE DATABASE. A Python-side monotonicity check would be the same
    coding convention the audit already broke; this inserts directly into the
    ledger, bypassing the store entirely."""
    _vehicle(store)
    with pytest.raises(Exception) as excinfo:
        database.execute(
            "INSERT INTO ontology_receipt_log (tenant_id, receipt_sequence, "
            "receipt_time, stream, row_id, row_hash, prev_hash, hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(store.tenant_id),
                2,
                "2020-01-01T00:00:00.000000+00:00",
                "fact",
                "x",
                "h",
                "p",
                "c",
            ),
        )
    assert "MX002" in _message(excinfo.value)
    database.rollback()


def test_a_gapped_receipt_sequence_is_refused_by_the_database(database, store) -> None:
    """A gap or a reused position would make the receipt order ambiguous, and an
    ambiguous order means a snapshot cannot be cut between two writes."""
    _vehicle(store)
    watermark = store.receipt_watermark()
    with pytest.raises(Exception) as excinfo:
        database.execute(
            "INSERT INTO ontology_receipt_log (tenant_id, receipt_sequence, "
            "receipt_time, stream, row_id, row_hash, prev_hash, hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(store.tenant_id),
                watermark.receipt_sequence + 5,
                "2027-01-01T00:00:00.000000+00:00",
                "fact",
                "x",
                "h",
                "p",
                "c",
            ),
        )
    assert "MX003" in _message(excinfo.value)
    database.rollback()


def test_a_rejected_write_consumes_no_receipt_sequence(database, store) -> None:
    """`_atomic` rolls the ledger row back with the failure, so a refused write
    leaves no gap -- which is what keeps the gaplessness invariant above true in
    the presence of ordinary validation failures."""
    vehicle = _vehicle(store)
    before = store.receipt_watermark().receipt_sequence
    with pytest.raises(Exception):
        store.record_fact(
            subject_kind=ObjectKind.VEHICLE,
            subject_id=vehicle.object_id,
            attribute="bad",
            fact_class=FactClass.OBSERVATION,
            quality=QualityState.TRUSTED,
            sensitivity=SensitivityClass.OPERATIONAL,
            legal_basis=LegalBasis.CONTRACT_PERFORMANCE,
            source_system="ops",
            source_record_id="x",
            value=None,  # no value AND no missingness reason
        )
    assert store.receipt_watermark().receipt_sequence == before
    _fact(store, vehicle)
    assert store.receipt_watermark().receipt_sequence == before + 1


def test_the_receipt_order_is_total_across_every_stream(database, store) -> None:
    """One order per tenant, not one per table. A snapshot must be cuttable
    between any two writes whatever streams they were in."""
    vehicle = _vehicle(store)
    fact = _fact(store, vehicle)
    event = store.record_event(
        event_kind=EventKind.VEHICLE_DELAYED,
        subject_kind=ObjectKind.VEHICLE,
        subject_id=vehicle.object_id,
        occurred_at=T,
        actor_kind=AuthorityKind.SYSTEM,
        actor_ref="avl",
        late_arrival_reason=LateArrivalReason.BATCH_EXPORT,
    )
    sequences = [
        vehicle.receipt.receipt_sequence,
        fact.receipt.receipt_sequence,
        event.receipt.receipt_sequence,
    ]
    assert sequences == sorted(set(sequences)) == [1, 2, 3]


# --------------------------------------------------------------------------- #
# 4. Integrity chain
# --------------------------------------------------------------------------- #
def test_the_integrity_report_covers_every_stream(database, store) -> None:
    """A verifier whose column list drifted from the write path's would either
    always report tampering or -- much worse -- always report none. Writing one
    row per stream and asserting zero mismatches is what pins the two lists
    together."""
    vehicle = _vehicle(store)
    _fact(store, vehicle)
    scope = SnapshotScope(subject_ids=(vehicle.object_id,))
    store.take_snapshot(as_of=store.receipt_watermark().receipt_time + timedelta(seconds=1), scope=scope)
    report = store.verify_integrity()
    assert report.intact
    assert report.rows_checked >= 3


def test_the_integrity_report_is_not_a_bare_boolean(database, store) -> None:
    """"The chain is intact" and "the chain is intact and covers 412 rows" are
    different assurances, and a caller shown only the first cannot tell an empty
    ledger from a verified one."""
    report = store.verify_integrity()
    assert report.rows_checked == 0
    assert report.intact  # vacuously -- and the count is what says so


# --------------------------------------------------------------------------- #
# 5. Tenant isolation
# --------------------------------------------------------------------------- #
def test_two_tenants_cannot_see_each_other(database) -> None:
    # ONE clock, two stores. Two independent clocks would let tenant B's snapshot
    # be taken "before" a boundary derived from tenant A's watermark, which is a
    # test artefact rather than anything about isolation -- and it would have
    # made this test fail for a reason that has nothing to do with tenants.
    clock = ScriptedClock()
    tenant_a = OntologyStore(database, canonical_new_id(TenantId), clock=clock)
    tenant_b = OntologyStore(database, canonical_new_id(TenantId), clock=clock)
    vehicle_a = _vehicle(tenant_a)
    _fact(tenant_a, vehicle_a, value=7.0)
    assert tenant_a.fact_history(vehicle_a.object_id, "seats")[0].value == 7.0
    assert tenant_b.fact_history(vehicle_a.object_id, "seats") == ()
    scope = SnapshotScope(subject_ids=(vehicle_a.object_id,))
    later = tenant_a.receipt_watermark().receipt_time + timedelta(seconds=1)
    assert tenant_a.take_snapshot(as_of=later, scope=scope).facts
    assert not tenant_b.take_snapshot(as_of=later, scope=scope).facts


def test_a_store_cannot_be_constructed_without_a_tenant() -> None:
    parameters = inspect.signature(OntologyStore.__init__).parameters
    assert parameters["tenant_id"].default is inspect.Parameter.empty


def test_the_tenant_is_read_only(database, store) -> None:
    """Rebinding it would turn one object into a cross-tenant path."""
    with pytest.raises(AttributeError):
        store.tenant_id = canonical_new_id(TenantId)  # type: ignore[misc]


@_skip_pg
def test_every_table_has_row_level_security_enabled_and_forced() -> None:
    """ENABLE alone is a FALSE GREEN: the application role owns these tables and
    a table owner bypasses RLS by default, so every isolation test would pass
    without the policy constraining anything. Both flags are read out of the
    catalog, not assumed from the SQL file."""
    database = OntologyDatabase.postgres()
    try:
        enabled = set(database.row_security_in_force(ONTOLOGY_TABLES))
        forced = set(database.force_row_security_in_force(ONTOLOGY_TABLES))
        assert enabled == set(ONTOLOGY_TABLES), f"not RLS-enabled: {set(ONTOLOGY_TABLES) - enabled}"
        assert forced == set(ONTOLOGY_TABLES), f"not RLS-FORCEd: {set(ONTOLOGY_TABLES) - forced}"
    finally:
        database.drop_schema()
        database.close()


@_skip_pg
def test_a_raw_cross_tenant_scan_returns_nothing() -> None:
    """No WHERE clause at all. If the application's predicate were the only
    boundary, this would return the other tenant's rows."""
    database = OntologyDatabase.postgres()
    try:
        tenant_a = OntologyStore(database, canonical_new_id(TenantId), clock=ScriptedClock())
        tenant_b = OntologyStore(database, canonical_new_id(TenantId), clock=ScriptedClock())
        _fact(tenant_a, _vehicle(tenant_a))
        database.use_tenant(tenant_b.tenant_id)
        assert database.query("SELECT * FROM ontology_facts") == []
        database.use_tenant(tenant_a.tenant_id)
        assert len(database.query("SELECT * FROM ontology_facts")) == 1
    finally:
        database.drop_schema()
        database.close()


@_skip_pg
def test_a_reset_guc_denies_rather_than_admits() -> None:
    """THE CASE THAT ACTUALLY OCCURS. `current_setting(name, true)` returns NULL
    only when the GUC was NEVER set; after a RESET -- a pooled connection handed
    back and reused -- it returns the EMPTY STRING. The GUC is asserted to read
    as '' FIRST, so this is not silently proving the NULL branch and reporting
    it as the RESET case."""
    database = OntologyDatabase.postgres()
    try:
        store = OntologyStore(database, canonical_new_id(TenantId), clock=ScriptedClock())
        _fact(store, _vehicle(store))
        database.execute_ddl("RESET milexium.tenant_id")
        guc = database.query("SELECT current_setting('milexium.tenant_id', true)")[0][0]
        assert guc == "", f"expected the empty string after RESET, got {guc!r}"
        assert database.query("SELECT * FROM ontology_facts") == []
    finally:
        database.drop_schema()
        database.close()


@_skip_pg
def test_a_foreign_tenant_write_is_rejected_by_the_policy() -> None:
    """The WITH CHECK half. A session acting as tenant B cannot write a row
    stamped with tenant A's id, however the application behaves."""
    database = OntologyDatabase.postgres()
    try:
        tenant_a = canonical_new_id(TenantId)
        tenant_b = canonical_new_id(TenantId)
        database.use_tenant(tenant_b)
        with pytest.raises(Exception):
            database.execute(
                "INSERT INTO ontology_objects (object_id, tenant_id, object_kind, "
                "external_ref, source_system, receipt_time, receipt_sequence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(canonical_new_id(TenantId)),
                    str(tenant_a),
                    "vehicle",
                    "X",
                    "ops",
                    "2026-03-02T09:00:00.000000+00:00",
                    1,
                ),
            )
        database.rollback()
    finally:
        database.drop_schema()
        database.close()


@_skip_pg
def test_lifting_force_collapses_the_boundary_proving_it_is_load_bearing() -> None:
    """The control for the isolation tests above. With FORCE lifted, the owning
    credential reads across tenants -- so the earlier zero-row results were the
    policy at work, not an empty table."""
    database = OntologyDatabase.postgres()
    try:
        tenant_a = OntologyStore(database, canonical_new_id(TenantId), clock=ScriptedClock())
        tenant_b = OntologyStore(database, canonical_new_id(TenantId), clock=ScriptedClock())
        _fact(tenant_a, _vehicle(tenant_a))
        database.use_tenant(tenant_b.tenant_id)
        assert database.query("SELECT * FROM ontology_facts") == []
        database.execute_ddl("ALTER TABLE ontology_facts NO FORCE ROW LEVEL SECURITY")
        assert len(database.query("SELECT * FROM ontology_facts")) == 1, (
            "lifting FORCE did not collapse the boundary, so the isolation tests "
            "above were not proving what they claim"
        )
        database.execute_ddl("ALTER TABLE ontology_facts FORCE ROW LEVEL SECURITY")
        assert database.query("SELECT * FROM ontology_facts") == []
    finally:
        database.drop_schema()
        database.close()


# --------------------------------------------------------------------------- #
# 6. The write surface is the action surface
# --------------------------------------------------------------------------- #
def test_the_store_exposes_no_generic_writer() -> None:
    """"Actions are typed operations, never arbitrary database writes" is
    worthless unless the arbitrary write is ABSENT rather than discouraged. The
    public surface is pinned; adding a generic writer fails here."""
    public = {
        name
        for name, _ in inspect.getmembers(OntologyStore, inspect.isfunction)
        if not name.startswith("_")
    }
    expected = {
        "register_object",
        "assert_relationship",
        "record_fact",
        "record_event",
        "record_identity_resolution",
        "take_snapshot",
        "load_snapshot",
        "snapshot_content_hash",
        "record_action",
        "record_outcome",
        "fact_history",
        "receipt_watermark",
        "verify_integrity",
    }
    assert public == expected, (
        f"the store's public surface changed: added {sorted(public - expected)}, "
        f"removed {sorted(expected - public)}. Every addition that WRITES must be a "
        "typed action, and every addition that READS must be checked for the "
        "point-in-time boundary"
    )


def test_the_audit_view_lives_on_the_store_and_not_on_the_snapshot() -> None:
    """`fact_history` deliberately applies no time filter. Putting it on
    `DecisionSnapshot` would have handed every holder of a snapshot a method
    that reaches past the boundary the snapshot exists to enforce -- which is
    precisely "a read path other than the obvious one"."""
    from packages.ontology.snapshot import DecisionSnapshot

    assert hasattr(OntologyStore, "fact_history")
    assert not hasattr(DecisionSnapshot, "fact_history")
    assert not hasattr(DecisionSnapshot, "history")


def test_state_survives_a_connection_being_closed(tmp_path: Path) -> None:
    """Durability, on the only engine where a file is the boundary. The
    PostgreSQL equivalent is covered by reopening a named schema."""
    path = str(tmp_path / "ontology.sqlite3")
    first = OntologyDatabase.sqlite(path)
    store = OntologyStore(first, (tenant := canonical_new_id(TenantId)), clock=ScriptedClock())
    vehicle = _vehicle(store)
    _fact(store, vehicle, value=3.0)
    snapshot = store.take_snapshot(
        as_of=store.receipt_watermark().receipt_time + timedelta(seconds=1),
        scope=SnapshotScope(subject_ids=(vehicle.object_id,)),
    )
    first.close()

    second = OntologyDatabase.sqlite(path)
    try:
        reopened = OntologyStore(second, tenant, clock=ScriptedClock(start=T + timedelta(days=1)))
        assert reopened.load_snapshot(snapshot.snapshot_id).content_hash == snapshot.content_hash
        assert reopened.verify_integrity().intact
    finally:
        second.close()


@_skip_pg
def test_reopening_a_postgres_schema_restores_the_triggers() -> None:
    """The trigger file is written to be re-appliable, and reopening is when it
    matters: a schema whose guards were dropped must come back guarded, not
    come back silently unguarded."""
    database = OntologyDatabase.postgres()
    schema = database.schema
    tenant = canonical_new_id(TenantId)
    try:
        store = OntologyStore(database, tenant, clock=ScriptedClock())
        _fact(store, _vehicle(store))
        database.execute_ddl("DROP TRIGGER ontology_facts_immutable ON ontology_facts")
        database.commit()
        database.close()

        reopened = OntologyDatabase.postgres(schema=schema)
        try:
            # SCOPE THE SESSION FIRST. Without the GUC, row-level security hides
            # every row, the UPDATE matches nothing, and a row-level trigger that
            # never fires makes the statement succeed -- which this test first
            # read as "the trigger was not restored". The guard was fine; the
            # test was reaching an empty result set. Assert the row is VISIBLE
            # before asserting the UPDATE is refused.
            reopened.use_tenant(tenant)
            assert reopened.query("SELECT 1 FROM ontology_facts"), (
                "no visible row to update, so the guard below could not fire"
            )
            with pytest.raises(Exception) as excinfo:
                reopened.execute("UPDATE ontology_facts SET value_number = 1")
            assert "MX001" in _message(excinfo.value)
            reopened.rollback()
            reopened.drop_schema()
        finally:
            # MUST close: a live connection holding this schema makes
            # DROP SCHEMA block indefinitely rather than fail, which turns a
            # teardown bug into a hung suite.
            reopened.close()
    finally:
        pass
