"""Conformance tests for the canonical SCHEDULING entity family
(MX-A-SCHEDULING-FAMILY-006): `Block`, `RunPiece`, `DeadheadSegment`.

THE GAP THESE CLOSE. ADR-0031 found that the canonical model was entirely
rider-request-keyed and therefore had no home for operational data. ADR-0035
closed half of it with the TELEMETRY family (`VehicleObservation` /
`StopTimeObservation`): what a vehicle was OBSERVED doing. It closed the other
half explicitly *not at all*, recording in its own consequences section that "the
scheduling operational family TODS needs (Block/RunCut/PieceOfWork) is a
different family again and remains deferred". That deferral is the reason TODS
and NeTEx are still **Specified**: not because the adapters are hard, but because
runs, blocks, pieces-of-work and deadhead segments had nowhere canonical to land,
so an adapter would have routed most of each standard to semantic loss.

WHAT THIS PACKET IS, AND IS NOT. It lands the canonical HOME. It is **not** a
TODS adapter and does not make any TODS claim -- no `app/connect` code is
touched here, no TODS file is parsed, no TODS fixture exists in this repository.
What is proven below is that the concepts TODS describes now have first-class
canonical entities, portable tables, tenant-isolation policies and durable
storage on both engines.

FOUR THINGS ARE UNDER TEST, in four sections:

1. **The entities themselves** -- request-independence (structurally, not by
   convention), time ordering, the closed deadhead vocabulary, and the
   source-refs-are-plain-strings rule inherited from ADR-0035.
2. **Portability** -- `schema_v0_1.sql` still executes unmodified against a bare
   `sqlite3` in-memory connection. That is the ADR-0002 contract, and it is
   asserted explicitly rather than inferred from the stores working.
3. **The round trip, on BOTH engines** through one parametrized fixture, because
   the claim is that `SqliteCanonicalStore` and `PostgresCanonicalStore` expose
   the same method contract (ADR-0004) -- a test that ran only on SQLite would
   prove half of it. Including the handoff to the consumer that has been waiting
   for this entity: `app.replay.teardown`.
4. **Adversarial tenant isolation** on the three new tables, issued as RAW SQL
   with NO WHERE clause after pointing the session GUC elsewhere, so what is
   under test is the POLICY and not any Python filter.

The PostgreSQL halves skip cleanly (never fail) when `milexium_dev` is
unreachable so CI stays green -- but a skip proves nothing, so the packet's
evidence requirement is that they RUN.

Status: **Demonstrated** at most -- these are synthetic scheduling fixtures. No
operator crew or block data exists in this repository (ADR-0038), and nothing
here is Validated.
"""

from __future__ import annotations

import inspect
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import get_args

import psycopg
import pytest

from app.canonical import (
    Block,
    BlockId,
    DeadheadKind,
    DeadheadSegment,
    DeadheadSegmentId,
    RunPiece,
    RunPieceId,
    Tenant,
    TenantId,
    new_id,
)
from app.canonical.postgres_storage import PostgresCanonicalStore
from app.canonical.postgres_storage import is_reachable as pg_is_reachable
from app.canonical.storage import CrossTenantWriteError, SqliteCanonicalStore

_SQL_DIR = Path(__file__).resolve().parents[3] / "app" / "canonical" / "sql"
_SCHEMA_PATH = _SQL_DIR / "schema_v0_1.sql"
_SCHEMA_SQL = _SCHEMA_PATH.read_text(encoding="utf-8")
_RLS_SQL = (_SQL_DIR / "rls_postgres.sql").read_text(encoding="utf-8")

# The executable DDL only. The file's comments legitimately NAME the constructs
# banned from it (they explain that geometry/GiST live in sql/postgis_postgres.sql
# instead), so scanning the raw text would flag the very documentation that keeps
# the rule honest -- the same treatment test_run_reference.py applies.
_SCHEMA_DDL = "\n".join(line.split("--", 1)[0] for line in _SCHEMA_SQL.splitlines()).lower()

_SCHEDULING_TABLES = ("blocks", "run_pieces", "deadhead_segments")

# Every table that existed before this packet. Asserted still present, because
# "additive only" is a promise about what was NOT touched, and a dropped or
# renamed table is the one way an additive change stops being additive.
_PRE_EXISTING_TABLES = (
    "tenants",
    "service_requests",
    "vehicles",
    "drivers",
    "policies",
    "model_versions",
    "forecast_vintages",
    "schedule_runs",
    "decision_alternatives",
    "decision_events",
    "outcomes",
    "outbox",
    "vehicle_observations",
    "stop_time_observations",
)


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _tenant(name: str = "scheduling-conformance") -> Tenant:
    return Tenant(tenant_id=new_id(TenantId), name=name, created_at=_utc(2026, 7, 24))


def _block(tenant_id: TenantId, **overrides) -> Block:
    fields = dict(
        block_id=new_id(BlockId),
        tenant_id=tenant_id,
        block_ref="B-101",
        service_ref="WEEKDAY",
        vehicle_ref="1860",
        garage_ref="ALBANY-GARAGE",
        pull_out_at=_utc(2026, 7, 24, 5, 10),
        pull_in_at=_utc(2026, 7, 24, 19, 40),
        recorded_at=_utc(2026, 7, 24, 4, 0),
    )
    fields.update(overrides)
    return Block(**fields)


def _run_piece(tenant_id: TenantId, **overrides) -> RunPiece:
    fields = dict(
        run_piece_id=new_id(RunPieceId),
        tenant_id=tenant_id,
        run_ref="RUN-7",
        piece_ref="RUN-7/1",
        piece_sequence=0,
        operator_ref="op-tok-9f21",
        block_id=None,
        block_ref="B-101",
        vehicle_ref="1860",
        start_type="report",
        end_type="relief",
        started_at=_utc(2026, 7, 24, 4, 55),
        ended_at=_utc(2026, 7, 24, 11, 30),
        recorded_at=_utc(2026, 7, 24, 4, 0),
    )
    fields.update(overrides)
    return RunPiece(**fields)


def _deadhead(tenant_id: TenantId, **overrides) -> DeadheadSegment:
    fields = dict(
        deadhead_segment_id=new_id(DeadheadSegmentId),
        tenant_id=tenant_id,
        deadhead_ref="DH-0001",
        block_id=None,
        block_ref="B-101",
        run_ref="RUN-7",
        vehicle_ref="1860",
        deadhead_type="pull_out",
        from_stop_ref="ALBANY-GARAGE",
        to_stop_ref="STOP-1042",
        started_at=_utc(2026, 7, 24, 5, 10),
        ended_at=_utc(2026, 7, 24, 5, 31),
        recorded_at=_utc(2026, 7, 24, 4, 0),
    )
    fields.update(overrides)
    return DeadheadSegment(**fields)


_FACTORIES = {"Block": _block, "RunPiece": _run_piece, "DeadheadSegment": _deadhead}


# =========================================================================
# 1. THE ENTITIES -- request-independence, ordering, vocabulary, ref typing
# =========================================================================


@pytest.mark.parametrize("entity_name", sorted(_FACTORIES))
def test_a_rider_request_key_cannot_be_attached_to_a_scheduling_entity(entity_name: str) -> None:
    """The defining property of this family, asserted structurally.

    ADR-0031's failure mode was a synthetic `Outcome.request_id` -- a foreign key
    to a ServiceRequest that did not exist -- minted because request-less data had
    nowhere else to go. A block is published days before any rider asks for
    anything, and a deadhead is by definition time with nobody aboard, so keying
    either on a request would repeat that exact category error. `_Canonical`'s
    `extra="forbid"` makes it impossible rather than merely discouraged: the
    construction raises, so no adapter can quietly add one later.
    """
    factory = _FACTORIES[entity_name]
    with pytest.raises(Exception) as excinfo:
        factory(new_id(TenantId), request_id=str(new_id(BlockId)))
    assert "request_id" in str(excinfo.value)


@pytest.mark.parametrize("entity_name", sorted(_FACTORIES))
def test_no_scheduling_entity_declares_a_request_field_at_all(entity_name: str) -> None:
    """The other half of request-independence: not merely that a request key is
    rejected on the way in, but that the model never asks for one. A field named
    `request_id` appearing here later would silently re-key the family onto the
    rider aggregate this packet exists to escape."""
    model = type(_FACTORIES[entity_name](new_id(TenantId)))
    assert not [name for name in model.model_fields if "request" in name.lower()]


def test_an_unmodelled_personal_field_cannot_be_smuggled_onto_a_run_piece() -> None:
    """`RunPiece.operator_ref` is a PERSON reference and follows
    `ServiceRequest.rider_ref`'s rule: a tokenised badge/signup reference, never a
    name (blueprint 10 data minimisation). `extra="forbid"` is what makes that a
    boundary instead of a convention -- an ingest that tried to carry the
    operator's actual name alongside the token fails at construction."""
    with pytest.raises(Exception):
        _run_piece(new_id(TenantId), operator_name="Jane Doe")


@pytest.mark.parametrize(
    ("entity_name", "overrides"),
    [
        ("Block", {"pull_out_at": _utc(2026, 7, 24, 19, 40), "pull_in_at": _utc(2026, 7, 24, 5, 10)}),
        ("RunPiece", {"started_at": _utc(2026, 7, 24, 11, 30), "ended_at": _utc(2026, 7, 24, 4, 55)}),
        (
            "DeadheadSegment",
            {"started_at": _utc(2026, 7, 24, 5, 31), "ended_at": _utc(2026, 7, 24, 5, 10)},
        ),
    ],
)
def test_reversed_time_ordering_is_rejected_at_construction(
    entity_name: str, overrides: dict
) -> None:
    """A vehicle cannot return before it leaves and a piece of work cannot end
    before it starts. Rejected at construction because a reversed pair is a
    parsing artefact (a date rollover, a local-vs-UTC mix-up) that yields a
    NEGATIVE duration -- which would quietly SUBTRACT from every total derived
    from it, and the headline total of a deadhead teardown is exactly such a
    derivation. `app.replay.teardown.VehicleSegment` applies the same guard
    to its own inputs; this applies it one layer earlier, so a reversed pair
    cannot even be stored."""
    with pytest.raises(Exception) as excinfo:
        _FACTORIES[entity_name](new_id(TenantId), **overrides)
    assert "before it" in str(excinfo.value)


@pytest.mark.parametrize("entity_name", sorted(_FACTORIES))
def test_a_zero_length_interval_is_accepted_not_treated_as_reversed(entity_name: str) -> None:
    """The boundary of the rule above, pinned so it cannot drift into
    over-rejection. Equal timestamps are a degenerate but real export (a
    zero-second relief, a block recorded at one-minute resolution); only
    end < start is impossible. Rejecting equality would quarantine valid rows."""
    instant = _utc(2026, 7, 24, 6, 0)
    if entity_name == "Block":
        entity = _block(new_id(TenantId), pull_out_at=instant, pull_in_at=instant)
        assert entity.pull_in_at == entity.pull_out_at
    else:
        entity = _FACTORIES[entity_name](new_id(TenantId), started_at=instant, ended_at=instant)
        assert entity.ended_at == entity.started_at


@pytest.mark.parametrize("kind", sorted(get_args(DeadheadKind)))
def test_every_declared_deadhead_kind_is_constructible(kind: str) -> None:
    """The five named kinds plus `other` are the vocabulary a consumer branches
    on: pull-out and pull-in are what a depot-location change moves, interlining
    is what block-building minimises, relief is empty for a crew reason rather
    than a schedule reason."""
    assert _deadhead(new_id(TenantId), deadhead_type=kind).deadhead_type == kind


def test_an_unrecognised_deadhead_kind_is_rejected_rather_than_stored_verbatim() -> None:
    """Deliberately UNLIKE the telemetry family's `current_status` /
    `schedule_relationship`, which keep the source string because they are
    lossless detail. `deadhead_type` is the field a consumer switches on, so an
    unrecognised value would not be detail -- it would be a silently unhandled
    branch. A source that did not classify the movement maps to `other`, which
    counts the time honestly without asserting a kind nobody recorded."""
    with pytest.raises(Exception):
        _deadhead(new_id(TenantId), deadhead_type="pull-out")  # hyphen, not the enum value


def test_deadhead_type_is_the_one_mandatory_descriptive_field() -> None:
    """Everything else is optional so a thin source ("this vehicle was empty from
    06:12 to 06:31") still produces a usable row; the classification is not,
    because an unclassified movement is still a classification decision."""
    minimal = DeadheadSegment(
        deadhead_segment_id=new_id(DeadheadSegmentId),
        tenant_id=new_id(TenantId),
        deadhead_type="other",
        started_at=_utc(2026, 7, 24, 6, 12),
        ended_at=_utc(2026, 7, 24, 6, 31),
        recorded_at=_utc(2026, 7, 24, 6, 40),
    )
    assert minimal.run_ref is None and minimal.block_id is None

    with pytest.raises(Exception):
        DeadheadSegment(
            deadhead_segment_id=new_id(DeadheadSegmentId),
            tenant_id=new_id(TenantId),
            started_at=_utc(2026, 7, 24, 6, 12),
            ended_at=_utc(2026, 7, 24, 6, 31),
            recorded_at=_utc(2026, 7, 24, 6, 40),
        )


@pytest.mark.parametrize(
    ("entity_name", "field"),
    [
        ("Block", "block_ref"),
        ("Block", "vehicle_ref"),
        ("Block", "garage_ref"),
        ("Block", "service_ref"),
        ("RunPiece", "run_ref"),
        ("RunPiece", "operator_ref"),
        ("RunPiece", "vehicle_ref"),
        ("RunPiece", "block_ref"),
        ("DeadheadSegment", "run_ref"),
        ("DeadheadSegment", "vehicle_ref"),
        ("DeadheadSegment", "from_stop_ref"),
        ("DeadheadSegment", "to_stop_ref"),
    ],
)
def test_source_system_references_stay_plain_strings(entity_name: str, field: str) -> None:
    """ADR-0035's first design call, applied unchanged. These name an EXTERNAL
    agency's entities -- their block number, their run, their vehicle, their
    garage, their operator badge -- not Milexium aggregates. Typing `vehicle_ref`
    as `VehicleId` would assert a canonical `Vehicle` row that no operator export
    creates, which is the same category error the whole family exists to remove
    (and would additionally force every ref through UUIDv7 validation that real
    agency identifiers like "B-101" cannot satisfy)."""
    model = type(_FACTORIES[entity_name](new_id(TenantId)))
    assert model.model_fields[field].annotation == (str | None)


@pytest.mark.parametrize("entity_name", ["RunPiece", "DeadheadSegment"])
def test_the_block_reference_is_typed_to_its_parent_not_left_a_bare_string(
    entity_name: str,
) -> None:
    """The counterpart to the rule above, and the reason this family mints THREE
    id kinds where ADR-0035's telemetry family shares one. `block_id` points at a
    `Block` this repository actually minted, so it is typed `BlockId` -- distinct
    from `RunPieceId` and `DeadheadSegmentId`, so a type checker rejects passing
    one where another belongs. (Runtime cross-tenant safety is a separate
    boundary, proven by the CrossTenantWriteError test below.)"""
    model = type(_FACTORIES[entity_name](new_id(TenantId)))
    assert model.model_fields["block_id"].annotation == (BlockId | None)
    assert len({BlockId, RunPieceId, DeadheadSegmentId}) == 3


# =========================================================================
# 2. PORTABILITY -- the portable DDL must stay portable (ADR-0002)
# =========================================================================


def test_schema_v0_1_executes_unmodified_on_a_bare_sqlite_connection() -> None:
    """THE PORTABILITY CONTRACT, asserted explicitly rather than inferred.

    `schema_v0_1.sql` is the one DDL file both engines load unmodified
    (ADR-0002/0004). This runs the file's ACTUAL BYTES through a plain
    `sqlite3` connection with no store class involved -- the store could in
    principle preprocess the file, so only a bare connection proves a
    Postgres-only construct did not arrive with the three new tables. Row-level
    security for them is Postgres-only and lives in sql/rls_postgres.sql, applied
    separately; that separation is what keeps this file executable here.
    """
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(_SCHEMA_SQL)  # raises if anything here is not portable
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()

    for table in _SCHEDULING_TABLES:
        assert table in tables, f"{table} is missing after executing the portable schema"


def test_the_scheduling_tables_are_purely_additive() -> None:
    """"Additive only" is a promise about what was NOT touched. Every table that
    existed before this packet must still exist after it -- a renamed or dropped
    table is the one way an additive change stops being additive, and it would
    break every other store method in the repository."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(_SCHEMA_SQL)
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()

    missing = [t for t in _PRE_EXISTING_TABLES if t not in tables]
    assert not missing, f"pre-existing tables disappeared from the portable schema: {missing}"


@pytest.mark.parametrize(
    "construct",
    ["jsonb", "serial", "geometry", "timestamptz", "generated always", "gist", "on conflict"],
)
def test_portable_schema_contains_no_postgres_only_construct(construct: str) -> None:
    """A regression guard naming the specific constructs that would break the
    SQLite execution above, so a future edit to this family fails with a readable
    reason rather than an opaque `sqlite3.OperationalError`. Note the closed
    deadhead vocabulary is spelled `CHECK ... IN (...)` and NOT a Postgres ENUM
    type for exactly this reason."""
    assert construct not in _SCHEMA_DDL, (
        f"schema_v0_1.sql contains the Postgres-only construct {construct!r}; it must run "
        "unmodified on SQLite -- Postgres-only DDL belongs in sql/rls_postgres.sql or "
        "sql/postgis_postgres.sql"
    )


def test_the_sql_deadhead_vocabulary_matches_the_python_literal_exactly() -> None:
    """Two declarations of one vocabulary can drift, and the failure would be
    silent in the worst direction: a kind Python accepts but the CHECK rejects
    fails loudly, while a kind the CHECK accepts but Python does not would let raw
    SQL write a row that can never be read back as an entity. Pinned in both
    directions."""
    match = re.search(
        r"deadhead_type\s+TEXT NOT NULL CHECK \(deadhead_type IN\s*\(([^)]*)\)", _SCHEMA_SQL
    )
    assert match is not None, "the deadhead_type CHECK constraint has been removed or reshaped"
    in_sql = set(re.findall(r"'([^']+)'", match.group(1)))

    assert in_sql == set(get_args(DeadheadKind))


def test_the_new_tables_reference_only_tenants_and_blocks() -> None:
    """No `REFERENCES vehicles(vehicle_id)` anywhere: a source-system vehicle
    number is not a canonical `Vehicle` aggregate, so an FK there would force
    every operator export to first mint canonical rows it has no data for. The
    only foreign keys are to `tenants` (the isolation boundary) and to `blocks`
    (a genuine canonical parent this repository mints)."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(_SCHEMA_SQL)
        referenced = {
            table: {row[2] for row in conn.execute(f"PRAGMA foreign_key_list({table})")}
            for table in _SCHEDULING_TABLES
        }
    finally:
        conn.close()

    assert referenced["blocks"] == {"tenants"}
    assert referenced["run_pieces"] == {"tenants", "blocks"}
    assert referenced["deadhead_segments"] == {"tenants", "blocks"}


def test_only_the_columns_that_must_be_present_are_not_null() -> None:
    """Nullability is a semantic claim, not a formality. `deadhead_type` is NOT
    NULL because an unclassified movement is still a classification decision;
    every source reference is nullable because absence must be recordable as
    absence -- an export that named no run leaves the segment unattributable, and
    a NOT NULL there would force a fabricated value into the one field a teardown
    attributes empty time by."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(_SCHEMA_SQL)
        columns = {
            table: {row[1]: row for row in conn.execute(f"PRAGMA table_info({table})")}
            for table in _SCHEDULING_TABLES
        }
    finally:
        conn.close()

    assert columns["deadhead_segments"]["deadhead_type"][3] == 1, "deadhead_type must be NOT NULL"
    for table, nullable_ref in (
        ("blocks", "block_ref"),
        ("blocks", "vehicle_ref"),
        ("run_pieces", "run_ref"),
        ("run_pieces", "operator_ref"),
        ("deadhead_segments", "run_ref"),
        ("deadhead_segments", "vehicle_ref"),
    ):
        _, _, declared_type, not_null, default, _ = columns[table][nullable_ref]
        assert declared_type == "TEXT", f"{table}.{nullable_ref} should be portable TEXT"
        assert not_null == 0, f"{table}.{nullable_ref} must stay nullable"
        assert default is None, f"{table}.{nullable_ref} must not invent a default value"


@pytest.mark.parametrize("table", _SCHEDULING_TABLES)
def test_every_new_tenant_scoped_table_has_an_rls_policy(table: str) -> None:
    """The defect ADR-0037 had to fix retroactively, guarded against here so it is
    not repeated. The observation tables sat in `schema_v0_1.sql` for two packets
    with NO policy because they were added after `rls_postgres.sql` was written --
    and a tenant-scoped table with no policy is precisely the false assurance
    ADR-0018 exists to prevent. This is a static check on the file's text, so it
    fails even on a machine with no PostgreSQL at all; the behavioural proof is in
    section 4."""
    assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" in _RLS_SQL
    assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;" in _RLS_SQL, (
        f"{table} has ENABLE but not FORCE -- the application role OWNS these tables and a "
        "table owner bypasses RLS by default, so every isolation test would pass for the "
        "wrong reason (ADR-0018)"
    )
    assert f"CREATE POLICY tenant_isolation ON {table}" in _RLS_SQL


# =========================================================================
# 3. ROUND TRIP -- both engines, one contract
# =========================================================================


@pytest.fixture(params=["sqlite", "postgres"])
def store(request):
    """The same tests, both engines. `params` (not two copies of each test) is
    what makes "identical method contract" a property under test rather than a
    claim in a docstring -- the same fixture shape
    evidence/conformance/property-tests/test_run_reference.py uses."""
    if request.param == "sqlite":
        st = SqliteCanonicalStore()
        try:
            yield st
        finally:
            st.close()
        return

    if not pg_is_reachable():
        pytest.skip(
            "PostgreSQL (milexium_dev) is not reachable on this machine; "
            "skipping the PostgreSQL half of the scheduling-family contract"
        )
    st = PostgresCanonicalStore.connect()
    try:
        yield st
    finally:
        st.drop_schema()
        st.close()


def test_both_stores_expose_the_same_scheduling_contract() -> None:
    """The mirrored-contract claim, checked structurally rather than trusted:
    same method names, same signatures, on both stores (ADR-0004)."""
    for name in (
        "record_block",
        "blocks",
        "record_run_piece",
        "run_pieces",
        "record_deadhead_segment",
        "deadhead_segments",
        "_resolve_block_for_tenant",
    ):
        sqlite_method = getattr(SqliteCanonicalStore, name)
        postgres_method = getattr(PostgresCanonicalStore, name)
        assert inspect.signature(sqlite_method) == inspect.signature(postgres_method), (
            f"{name} has diverged between the SQLite and PostgreSQL stores"
        )


def test_block_round_trips_with_every_field_intact(store) -> None:
    """Equality is asserted on the whole reconstructed entity, so a stored column
    that no longer validates as a `Block` fails here rather than in whatever
    consumer trusted it."""
    tenant = _tenant()
    store.create_tenant(tenant)

    block = _block(tenant.tenant_id)
    store.record_block(block)

    assert store.blocks(tenant.tenant_id) == (block,)


def test_run_piece_round_trips_with_every_field_intact(store) -> None:
    tenant = _tenant()
    store.create_tenant(tenant)

    block = _block(tenant.tenant_id)
    store.record_block(block)
    piece = _run_piece(tenant.tenant_id, block_id=block.block_id)
    store.record_run_piece(piece)

    assert store.run_pieces(tenant.tenant_id) == (piece,)


@pytest.mark.parametrize("kind", sorted(get_args(DeadheadKind)))
def test_every_deadhead_kind_survives_a_write_and_read_back(store, kind: str) -> None:
    """The classification is what a consumer branches on, so every value of it
    must survive storage -- including `other`, whose whole purpose is to carry an
    unclassified movement without inventing a kind for it."""
    tenant = _tenant()
    store.create_tenant(tenant)

    segment = _deadhead(tenant.tenant_id, deadhead_type=kind)
    store.record_deadhead_segment(segment)

    (stored,) = store.deadhead_segments(tenant.tenant_id)
    assert stored.deadhead_type == kind
    assert stored == segment


def test_a_sparse_row_reads_back_absent_rather_than_as_a_placeholder(store) -> None:
    """The honesty property, and the one most easily broken by a storage layer.
    A crew export that named no run, no block and no operator is *unattributable*;
    absent must come back absent -- never `''`, never the string `'None'`, never
    back-filled from a neighbouring column. A fabricated run reference would
    attribute empty time to a run that did not incur it."""
    tenant = _tenant()
    store.create_tenant(tenant)

    piece = _run_piece(
        tenant.tenant_id,
        run_ref=None,
        piece_ref=None,
        piece_sequence=None,
        operator_ref=None,
        block_ref=None,
        vehicle_ref=None,
        start_type=None,
        end_type=None,
    )
    store.record_run_piece(piece)
    segment = _deadhead(
        tenant.tenant_id,
        deadhead_ref=None,
        block_ref=None,
        run_ref=None,
        vehicle_ref=None,
        from_stop_ref=None,
        to_stop_ref=None,
    )
    store.record_deadhead_segment(segment)

    (stored_piece,) = store.run_pieces(tenant.tenant_id)
    (stored_segment,) = store.deadhead_segments(tenant.tenant_id)
    assert stored_piece == piece
    assert stored_piece.run_ref is None and stored_piece.piece_sequence is None
    assert stored_segment == segment
    assert stored_segment.run_ref is None


def test_a_run_piece_can_be_stored_before_its_block_is_known(store) -> None:
    """`block_id` is a NULLABLE foreign key on purpose: a crew export legitimately
    arrives before the vehicle assignment it references. The source's own
    `block_ref` is preserved meanwhile, so the link is not lost -- it is simply
    not yet resolved to a canonical row."""
    tenant = _tenant()
    store.create_tenant(tenant)

    piece = _run_piece(tenant.tenant_id, block_id=None, block_ref="B-101")
    store.record_run_piece(piece)

    (stored,) = store.run_pieces(tenant.tenant_id)
    assert stored.block_id is None
    assert stored.block_ref == "B-101"


def test_a_run_piece_may_not_reference_another_tenants_block(store) -> None:
    """FAILURE INJECTION. A foreign key alone does NOT keep this reference inside
    the tenant: PostgreSQL evaluates referential integrity with RLS bypassed by
    design, and the table's own WITH CHECK constrains only `tenant_id`. So the
    parent block is resolved UNDER the acting tenant before the insert, exactly as
    `append_decision_alternative` resolves its parent schedule run -- and both
    stores raise the identical `CrossTenantWriteError`, never accept the row."""
    tenant_a = _tenant("a")
    tenant_b = _tenant("b")
    store.create_tenant(tenant_a)
    store.create_tenant(tenant_b)

    foreign_block = _block(tenant_a.tenant_id)
    store.record_block(foreign_block)

    with pytest.raises(CrossTenantWriteError):
        store.record_run_piece(_run_piece(tenant_b.tenant_id, block_id=foreign_block.block_id))
    with pytest.raises(CrossTenantWriteError):
        store.record_deadhead_segment(_deadhead(tenant_b.tenant_id, block_id=foreign_block.block_id))

    assert store.run_pieces(tenant_b.tenant_id) == ()
    assert store.deadhead_segments(tenant_b.tenant_id) == ()


@pytest.mark.parametrize(
    ("write", "read"),
    [
        ("record_block", "blocks"),
        ("record_run_piece", "run_pieces"),
        ("record_deadhead_segment", "deadhead_segments"),
    ],
)
def test_scheduling_reads_are_tenant_scoped(store, write: str, read: str) -> None:
    """The tenant filter is applied in SQL, never in Python after an unfiltered
    fetch. Two agencies sharing a corridor legitimately use the SAME block number
    and the same run id, so this must separate them on tenant alone."""
    factory = {"blocks": _block, "run_pieces": _run_piece, "deadhead_segments": _deadhead}[read]
    tenant_a = _tenant("a")
    tenant_b = _tenant("b")
    store.create_tenant(tenant_a)
    store.create_tenant(tenant_b)

    getattr(store, write)(factory(tenant_a.tenant_id))
    getattr(store, write)(factory(tenant_b.tenant_id))

    rows = getattr(store, read)(tenant_a.tenant_id)
    assert len(rows) == 1
    assert rows[0].tenant_id == tenant_a.tenant_id


def test_deadhead_segments_are_returned_in_valid_time_order(store) -> None:
    """Both stores write the same ORDER BY, so the two engines return the same
    SEQUENCE, not merely the same set -- the property that keeps them from
    drifting into "equivalent but different" implementations. Valid-time order is
    also the order a teardown wants to consume them in."""
    tenant = _tenant()
    store.create_tenant(tenant)

    starts = [_utc(2026, 7, 24, 19, 20), _utc(2026, 7, 24, 5, 10), _utc(2026, 7, 24, 12, 0)]
    for started_at in starts:
        store.record_deadhead_segment(
            _deadhead(
                tenant.tenant_id,
                started_at=started_at,
                ended_at=started_at + timedelta(minutes=10),
            )
        )

    assert [s.started_at for s in store.deadhead_segments(tenant.tenant_id)] == sorted(starts)


def test_stored_deadhead_segments_feed_the_teardown_field_for_field(store) -> None:
    """THE CONSUMER THIS ENTITY WAS SHAPED FOR.

    `app/replay/teardown.py` measures where empty vehicle time sat, but until
    now it could only be handed `VehicleSegment`s built in memory from a
    Connect-layer export -- deadhead had no canonical home to be read back out of,
    so a teardown could not be re-derived from stored state. This test reads the
    segments back from the database and maps them with NO translation
    (`started_at`/`ended_at`/`run_ref` are deliberately the teardown's own field
    names), then checks the two properties that matter: the minutes reconcile, and
    the segment whose export named no run lands in `unattributable` instead of
    being guessed onto the run beside it.

    `app/replay` is READ-ONLY here -- it is another packet's path and is not
    modified.
    """
    from app.replay.teardown import VehicleSegment, teardown_deadhead

    tenant = _tenant("teardown-handoff")
    store.create_tenant(tenant)

    store.record_deadhead_segment(
        _deadhead(
            tenant.tenant_id,
            deadhead_type="pull_out",
            run_ref="RUN-7",
            started_at=_utc(2026, 7, 24, 5, 10),
            ended_at=_utc(2026, 7, 24, 5, 31),  # 21 min
        )
    )
    store.record_deadhead_segment(
        _deadhead(
            tenant.tenant_id,
            deadhead_type="interline",
            run_ref="RUN-7",
            started_at=_utc(2026, 7, 24, 12, 0),
            ended_at=_utc(2026, 7, 24, 12, 12),  # 12 min
        )
    )
    store.record_deadhead_segment(
        _deadhead(
            tenant.tenant_id,
            deadhead_type="pull_in",
            run_ref=None,  # the export did not say which run
            started_at=_utc(2026, 7, 24, 19, 20),
            ended_at=_utc(2026, 7, 24, 19, 40),  # 20 min
        )
    )

    segments = tuple(
        VehicleSegment(
            started_at=stored.started_at,
            ended_at=stored.ended_at,
            kind="deadhead",
            run_ref=stored.run_ref,
        )
        for stored in store.deadhead_segments(tenant.tenant_id)
    )
    result = teardown_deadhead(
        segments,
        dataset_label="scheduling-family conformance fixture",
        data_provenance="synthetic",
        run_ref_source="deadhead_segments.run_ref",
    )

    assert result.total_deadhead_minutes == 53.0
    assert [(r.run_ref, r.deadhead_minutes) for r in result.top_runs] == [("RUN-7", 33.0)]
    assert result.unattributable is not None
    assert result.unattributable.deadhead_minutes == 20.0
    assert result.causal_proof is False


# =========================================================================
# 4. ADVERSARIAL TENANT ISOLATION -- the policy, not a Python filter
# =========================================================================

# Raw INSERTs, one per table: the isolation tests must not go through any store
# method, because what is under test is the DATABASE POLICY. Each names only the
# columns that table requires plus a source reference or two.
_RAW_INSERTS: dict[str, tuple[str, type]] = {
    "blocks": (
        "INSERT INTO blocks (block_id, tenant_id, block_ref, vehicle_ref, pull_out_at, "
        "pull_in_at, recorded_at) VALUES (%s, %s, 'B-101', '1860', "
        "'2026-07-24T05:10:00+00:00', '2026-07-24T19:40:00+00:00', '2026-07-24T04:00:00+00:00')",
        BlockId,
    ),
    "run_pieces": (
        "INSERT INTO run_pieces (run_piece_id, tenant_id, run_ref, operator_ref, started_at, "
        "ended_at, recorded_at) VALUES (%s, %s, 'RUN-7', 'op-tok-9f21', "
        "'2026-07-24T04:55:00+00:00', '2026-07-24T11:30:00+00:00', '2026-07-24T04:00:00+00:00')",
        RunPieceId,
    ),
    "deadhead_segments": (
        "INSERT INTO deadhead_segments (deadhead_segment_id, tenant_id, run_ref, deadhead_type, "
        "started_at, ended_at, recorded_at) VALUES (%s, %s, 'RUN-7', 'pull_out', "
        "'2026-07-24T05:10:00+00:00', '2026-07-24T05:31:00+00:00', '2026-07-24T04:00:00+00:00')",
        DeadheadSegmentId,
    ),
}


@pytest.fixture
def rls_store() -> PostgresCanonicalStore:
    """`PostgresCanonicalStore` is the store that applies sql/rls_postgres.sql, so
    it is what proves the new scheduling-table policies."""
    if not pg_is_reachable():
        pytest.skip(
            "PostgreSQL (milexium_dev) is not reachable on this machine; "
            "skipping the scheduling-table RLS conformance tests"
        )
    store = PostgresCanonicalStore.connect()
    try:
        yield store
    finally:
        store.drop_schema()
        store.close()


def _set_session_tenant(store: PostgresCanonicalStore, tenant_id: object) -> None:
    """Set the RLS session key directly on the connection -- exactly what an
    attacker holding the app credential, or a plain bug, could do -- so the raw
    reads below are governed only by the policy."""
    store._conn.execute("SELECT set_config('milexium.tenant_id', %s, false)", (str(tenant_id),))


def _raw_insert_scheduling_rows(store: PostgresCanonicalStore, tenant: Tenant) -> None:
    """Register `tenant` and write it one row in EACH scheduling table, by raw SQL."""
    store.create_tenant(tenant)  # also points the GUC at this tenant
    for statement, id_kind in _RAW_INSERTS.values():
        store._conn.execute(statement, (str(new_id(id_kind)), str(tenant.tenant_id)))
    store._conn.commit()


@pytest.mark.parametrize("table", _SCHEDULING_TABLES)
def test_scheduling_tables_have_rls_enabled_and_forced(rls_store, table: str) -> None:
    """The precondition every other test in this section rests on, asserted rather
    than assumed. ENABLE alone would be a false green: `milexium_dev` OWNS these
    tables and a table owner bypasses RLS by default (ADR-0018), so
    `relforcerowsecurity` is the bit that actually matters."""
    cur = rls_store._conn.execute(
        "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = %s",
        (rls_store._schema, table),
    )
    enabled, forced = cur.fetchone()
    rls_store._conn.commit()

    assert enabled is True, f"{table} does not have ROW LEVEL SECURITY enabled"
    assert forced is True, (
        f"{table} has ENABLE but not FORCE -- the owning role bypasses the policy and every "
        "isolation test below would pass for the wrong reason"
    )


@pytest.mark.parametrize("table", _SCHEDULING_TABLES)
def test_cross_tenant_scheduling_read_is_blocked_by_the_policy(rls_store, table: str) -> None:
    """Core proof: acting as tenant B, a raw table scan with NO WHERE clause
    returns none of tenant A's rows. These three tables together are an operator's
    crew roster and depot geography -- who worked which vehicle, out of which
    garage, at what hour -- which is commercially sensitive to the agency and
    personal to the driver."""
    tenant_a = _tenant("sched-tenant-a")
    tenant_b = _tenant("sched-tenant-b")
    _raw_insert_scheduling_rows(rls_store, tenant_a)
    _raw_insert_scheduling_rows(rls_store, tenant_b)

    _set_session_tenant(rls_store, tenant_b.tenant_id)
    cur = rls_store._conn.execute(f"SELECT tenant_id FROM {table}")
    visible = {row[0] for row in cur.fetchall()}
    rls_store._conn.commit()

    assert visible == {str(tenant_b.tenant_id)}, (
        f"a raw scan of {table} as tenant B leaked another tenant's rows"
    )


@pytest.mark.parametrize("table", _SCHEDULING_TABLES)
def test_own_tenant_scheduling_rows_are_still_visible(rls_store, table: str) -> None:
    """Positive control: the policy must not over-block. Acting as A, A's own row
    is there -- otherwise the test above would pass on an empty table and prove
    nothing at all."""
    tenant_a = _tenant("sched-tenant-a")
    _raw_insert_scheduling_rows(rls_store, tenant_a)

    _set_session_tenant(rls_store, tenant_a.tenant_id)
    cur = rls_store._conn.execute(f"SELECT count(*) FROM {table}")
    (count,) = cur.fetchone()
    rls_store._conn.commit()

    assert count == 1


@pytest.mark.parametrize("table", _SCHEDULING_TABLES)
def test_a_reset_session_tenant_denies_all_scheduling_rows(rls_store, table: str) -> None:
    """Default-DENY, proven for the case that actually occurs.

    THE TRAP THIS ASSERTS AROUND (documented above the `model_versions` policy in
    sql/rls_postgres.sql): `current_setting(name, true)` returns NULL only when the
    GUC was NEVER set in the session. After a `RESET` -- which is what a pooled
    connection handed back and reused looks like -- it returns the EMPTY STRING,
    and an `IS NOT NULL` guard would happily accept that. So this asserts the GUC
    reads as `''` and NOT as None *first*, and only then that zero rows come back:
    otherwise the test would be proving the NULL branch, which is not the branch
    a reset session takes. These policies survive it because `tenant_id = ''` is
    false for any real UUID -- incidental, and therefore worth pinning.
    """
    _raw_insert_scheduling_rows(rls_store, _tenant("sched-tenant-a"))
    _raw_insert_scheduling_rows(rls_store, _tenant("sched-tenant-b"))

    rls_store._conn.execute("RESET milexium.tenant_id")
    cur = rls_store._conn.execute("SELECT current_setting('milexium.tenant_id', true)")
    (guc,) = cur.fetchone()
    assert guc == "", (
        "a RESET session was expected to read the GUC back as the EMPTY STRING (the "
        f"documented trap), got {guc!r} -- if this is now None the empty-string case is "
        "going untested"
    )

    cur = rls_store._conn.execute(f"SELECT count(*) FROM {table}")
    (count,) = cur.fetchone()
    rls_store._conn.commit()

    assert count == 0, (
        f"a reset milexium.tenant_id exposed {count} {table} rows -- the policy defaults to "
        "allow-all, which is backwards"
    )


@pytest.mark.parametrize("table", _SCHEDULING_TABLES)
def test_a_scheduling_write_stamped_with_a_foreign_tenant_is_rejected(rls_store, table: str) -> None:
    """The WITH CHECK half: acting as an unrelated tenant, an INSERT stamped with
    A's tenant id is refused at the DATABASE layer. A compromised ingest path
    cannot smuggle a fabricated block or crew assignment into another operator's
    evidence -- and this holds with the Python store bypassed entirely."""
    tenant_a = _tenant("sched-tenant-a")
    _raw_insert_scheduling_rows(rls_store, tenant_a)
    _set_session_tenant(rls_store, new_id(TenantId))

    statement, id_kind = _RAW_INSERTS[table]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        rls_store._conn.execute(statement, (str(new_id(id_kind)), str(tenant_a.tenant_id)))
    rls_store._conn.rollback()


@pytest.mark.parametrize("table", _SCHEDULING_TABLES)
def test_force_row_level_security_is_load_bearing_on_scheduling_tables(
    rls_store, table: str
) -> None:
    """Proves FORCE -- not ENABLE alone -- is what binds the OWNING role on these
    three tables specifically. The boundary is shown COLLAPSING the instant FORCE
    is lifted, then restored: without that middle step, a passing isolation test
    is indistinguishable from one passing for the wrong reason."""
    tenant_a = _tenant("sched-tenant-a")
    _raw_insert_scheduling_rows(rls_store, tenant_a)
    _set_session_tenant(rls_store, new_id(TenantId))  # an empty, unrelated tenant

    cur = rls_store._conn.execute(f"SELECT count(*) FROM {table}")
    assert cur.fetchone()[0] == 0, f"FORCE RLS should hide tenant A's {table} rows"

    rls_store._conn.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    cur = rls_store._conn.execute(f"SELECT count(*) FROM {table}")
    assert cur.fetchone()[0] == 1, (
        f"without FORCE the owning role bypasses RLS on {table} -- this is exactly why FORCE "
        "is required, and why an ENABLE-only setup would be a false green"
    )

    rls_store._conn.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    cur = rls_store._conn.execute(f"SELECT count(*) FROM {table}")
    assert cur.fetchone()[0] == 0
    rls_store._conn.commit()
