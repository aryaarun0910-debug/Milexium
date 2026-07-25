"""Conformance for Program D persistence (MX-D-PERSISTENCE-004).

ADR-0034 landed the adaptive-memory slice -- the leakage-safe point-in-time
feature store and the champion/challenger/canary promotion controller -- as
IN-MEMORY reference backends. A design partner's feature values, promotion
decisions and rollback history did not survive a process restart, which is the
gap a real pilot hits first. `PersistentFeatureStore` and
`PersistentPromotionController` close it over `packages/core/sql/core_v0_1.sql`.

Four claims are under test here:

1. **Same contract.** The persistent classes are method-for-method identical to
   the in-memory references (checked structurally by signature, then
   differentially by running the same script through both and comparing every
   observable).
2. **Portable DDL (ADR-0002).** `core_v0_1.sql` runs UNMODIFIED on SQLite and on
   PostgreSQL 17, so every behavioural test below is parametrised `[sqlite]` /
   `[postgres]` -- the same discipline
   conformance/property-tests/test_decision_alternatives.py applies to the
   canonical stores. A test that only ran on SQLite would prove half of it.
3. **THE LEAKAGE GUARANTEE SURVIVES PERSISTENCE.** The load-bearing invariant is
   that an as-of read at label time t returns only values whose knowledge_time
   is STRICTLY < t. It is re-proved through the persistent path with the same
   mechanical future-corruption discipline ADR-0034 used (and
   realdata/leakage_audit.py before it) on the same REAL aggregate panel --
   twice: once by rebuilding from corrupted rows, and once by corrupting the
   STORED ROWS IN PLACE with raw SQL, which only a persistent backend can be
   asked to survive.
4. **The promotion ledger is an audit trail.** Decisions (promoted AND rejected)
   and rollback records persist and read back complete and in order across a
   reopen.

EXTENDED BY MX-D-TENANT-ISOLATION-006. Both persistent classes now require a
`tenant_id` at construction (see `TENANT` below), because ADR-0041's tables
carried no tenant column and no row-level security -- the limitation that ADR
named as "must be closed before a second operator's data lands in them". Every
test in this file therefore runs as one tenant; the isolation itself (the
policy, the cross-tenant denials, the FORCE-lifted collapse) is proved in
`conformance/property-tests/test_core_tenant_isolation.py`, which is the
adversarial half. What is added HERE is the part that belongs here: that the
four claims above are unchanged under tenant scoping -- in particular that the
leakage guarantee still holds when the as-of predicate is conjoined with a
tenant predicate, re-run below rather than assumed.

The PostgreSQL parameter SKIPS cleanly (never fails) when the `milexium_dev`
instance is unreachable, so this suite stays green on a machine where it was
never provisioned. The SQLite parameter always runs, against a real on-disk file
in tmp_path -- `:memory:` would make "survives a reopen" unprovable.

REAL vs SYNTHETIC is labelled per test. The real panel is NYC Access-A-Ride
daily scheduled trips (realdata/panels/aar_daily.csv), public aggregate data.
Status: Demonstrated, never operator-Validated.
"""

from __future__ import annotations

import inspect
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import psycopg
import pytest

from packages.canonical import ModelVersion, ModelVersionId, TenantId, new_id
from packages.canonical.postgres_storage import is_reachable as pg_is_reachable
from packages.core.feature_store import (
    CORE_SCHEMA_PATH,
    CoreDatabase,
    FeatureStore,
    PersistentFeatureStore,
)
from packages.core.model_registry import ModelRegistry
from packages.core.promotion import (
    NoRollbackTargetError,
    PersistentPromotionController,
    PromotionController,
    RoleAssignmentError,
    TrafficFractionError,
)

# --- REAL aggregate panel (labelled): NYC Access-A-Ride daily scheduled trips.
_AAR_DAILY = Path(__file__).resolve().parents[2] / "realdata" / "panels" / "aar_daily.csv"

TASK = "forecast.demand"

# The single operator every test in this file acts as. A canonical `TenantId`
# (UUIDv7), minted once per session -- the persistent stores refuse to be built
# without one, which is the point: there is no unscoped way to reach the tables.
TENANT = new_id(TenantId)

# Every table core_v0_1.sql defines, in the order the file declares them.
_CORE_TABLES = (
    "feature_values",
    "promotion_decisions",
    "promotion_rollbacks",
    "promotion_champions",
    "promotion_champion_history",
    "promotion_challengers",
    "promotion_canaries",
)

# The DB-API exception both engines raise for a violated CHECK / PRIMARY KEY.
_INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg.IntegrityError)


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Engine fixture: the same tests, both engines, with reopen support
# --------------------------------------------------------------------------- #
class _Engine:
    """A durable storage location that can be opened more than once.

    `open()` returns a NEW `CoreDatabase` over the SAME underlying storage -- an
    on-disk SQLite file, or one named PostgreSQL schema. That is how a process
    restart is modelled: the first connection is closed and a second one is
    opened over storage the first one left behind. An in-memory store cannot
    pass such a test at all, which is precisely the point.
    """

    def __init__(self, kind: str, tmp_path: Path) -> None:
        self.kind = kind
        self._path = str(tmp_path / "core_v0_1.db")
        self._schema = f"mx_core_test_{uuid.uuid4().hex}"
        self._opened: list[CoreDatabase] = []

    def open(self) -> CoreDatabase:
        database = (
            CoreDatabase.sqlite(self._path)
            if self.kind == "sqlite"
            else CoreDatabase.postgres(schema=self._schema)
        )
        self._opened.append(database)
        return database

    def dispose(self) -> None:
        for database in self._opened:
            try:
                database.close()
            except Exception:  # pragma: no cover - teardown must never mask a failure
                pass
        if self.kind == "postgres":
            # A dedicated connection for teardown: a test may have deliberately
            # aborted the transaction on its own (the CHECK-violation test does),
            # and the schema must be dropped regardless.
            cleanup = CoreDatabase.postgres(schema=self._schema)
            cleanup.drop_schema()
            cleanup.close()


@pytest.fixture(params=["sqlite", "postgres"])
def engine(request, tmp_path):
    """`params` (not two copies of each test) is what makes "the same DDL and the
    same store run on both engines" a property under test rather than a claim in
    a docstring."""
    if request.param == "postgres" and not pg_is_reachable():
        pytest.skip(
            "PostgreSQL (milexium_dev) is not reachable on this machine; "
            "skipping the PostgreSQL half of the Program D persistence contract"
        )
    eng = _Engine(request.param, tmp_path)
    try:
        yield eng
    finally:
        eng.dispose()


def _model_version(**overrides) -> ModelVersion:
    """SYNTHETIC model-version fixture (the controller logic is what is tested)."""
    fields = dict(
        model_version_id=new_id(ModelVersionId),
        tenant_id=new_id(TenantId),
        task=TASK,
        training_data_manifest_hash="deadbeef" * 8,
        feature_schema_version="zone_hour_demand_v1",
        evaluation_window_start=_utc(2026, 3, 2),
        evaluation_window_end=_utc(2026, 5, 31),
        artifact_hash="cafebabe" * 8,
    )
    fields.update(overrides)
    return ModelVersion(**fields)


def _registry_with(*versions: ModelVersion) -> ModelRegistry:
    registry = ModelRegistry()
    for version in versions:
        registry.register(version)
    return registry


# --------------------------------------------------------------------------- #
# 1. The contract is the SAME contract (structural, engine-independent)
# --------------------------------------------------------------------------- #
def test_persistent_feature_store_mirrors_the_in_memory_contract() -> None:
    """The whole claim is that a caller can be handed either backend without
    changing a line. Checked structurally rather than trusted: same method names,
    same signatures. `__init__` is excluded -- one takes a database, the other
    takes nothing, and that is the only difference there is meant to be."""
    for name in ("write", "get_feature", "get_features", "history", "entities"):
        reference = getattr(FeatureStore, name)
        persistent = getattr(PersistentFeatureStore, name)
        assert inspect.signature(reference) == inspect.signature(persistent), (
            f"FeatureStore.{name} has diverged from PersistentFeatureStore.{name}"
        )


def test_persistent_promotion_controller_mirrors_the_in_memory_contract() -> None:
    for name in (
        "register_challenger",
        "demote_challenger",
        "set_canary",
        "clear_canary",
        "route",
        "evaluate_and_maybe_promote",
        "rollback",
        "champion",
        "challengers",
        "canary",
        "rollout",
        "decisions",
        "rollbacks",
    ):
        reference = getattr(PromotionController, name)
        persistent = getattr(PersistentPromotionController, name)
        assert inspect.signature(reference) == inspect.signature(persistent), (
            f"PromotionController.{name} has diverged from "
            f"PersistentPromotionController.{name}"
        )


def test_core_schema_declares_no_postgres_only_or_sqlite_only_constructs() -> None:
    """A cheap static guard on the portable-DDL rule (ADR-0002). The real proof
    is that every test below runs the file unmodified on BOTH engines; this
    catches the common regressions at the point they are written."""
    ddl = CORE_SCHEMA_PATH.read_text(encoding="utf-8").upper()
    body = "\n".join(
        line for line in ddl.splitlines() if not line.strip().startswith("--")
    )
    for banned in ("JSONB", "SERIAL", "AUTOINCREMENT", "CREATE TYPE", "GEOMETRY", "UUID "):
        assert banned not in body, f"{banned} is not in the portable SQL subset"
    # REAL is float4 on PostgreSQL and float8 on SQLite -- the same write would
    # read back with different precision per engine, which would break the
    # bit-identical claim the leakage tests make.
    assert " REAL" not in body, "use DOUBLE PRECISION, not REAL (float4 on PostgreSQL)"


# --------------------------------------------------------------------------- #
# 2. The portable DDL applies, on both engines, more than once
# --------------------------------------------------------------------------- #
def test_core_schema_applies_unmodified_on_this_engine(engine) -> None:
    """The portability claim: one file, no per-engine edit, every table present
    and queryable afterwards."""
    database = engine.open()
    for table in _CORE_TABLES:
        assert database.query(f"SELECT COUNT(*) FROM {table}")[0][0] == 0


def test_every_program_d_table_carries_a_not_null_tenant_id(engine) -> None:
    """MX-D-TENANT-ISOLATION-006, at the schema layer, on both engines.

    ADR-0041 shipped these seven tables with no tenant column at all. A NULLABLE
    one would have been barely better: `tenant_id = current_setting(...)` is
    never true for NULL, so a null-tenant row would be invisible under the
    PostgreSQL policy and simultaneously present in the table -- unreadable,
    undeletable through the store, and permanently unattributable. NOT NULL is
    what makes "every row belongs to exactly one operator" a property of the
    storage rather than of the code that happened to write it.

    Read out of each engine's own catalog, so a column that exists only in the
    file's text (or only on one engine) fails here.
    """
    database = engine.open()
    for table in _CORE_TABLES:
        if engine.kind == "sqlite":
            columns = {
                row[1]: bool(row[3])  # name -> notnull
                for row in database.query(f"PRAGMA table_info({table})")
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


def test_tenant_id_leads_every_program_d_primary_key(engine) -> None:
    """The tenant column is FIRST in every primary key, not merely present.

    Two things follow from the ordering, and only from it. Uniqueness becomes
    per-tenant -- two operators can each hold a champion for `forecast.demand`,
    which they must, since the task name is not customer-specific -- and the
    tenant predicate leads the index that serves the as-of read, so conjoining
    it does not demote `knowledge_time < t` to a filter over a wider scan.
    """
    database = engine.open()
    for table in _CORE_TABLES:
        if engine.kind == "sqlite":
            # PRAGMA's `pk` column is the 1-based position within the key.
            key = sorted(
                ((row[5], row[1]) for row in database.query(f"PRAGMA table_info({table})") if row[5]),
            )
            first = key[0][1]
        else:
            rows = database.query(
                "SELECT a.attname FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_attribute a ON a.attrelid = c.oid "
                "AND a.attnum = i.indkey[0] "
                "WHERE n.nspname = ? AND c.relname = ? AND i.indisprimary",
                (database.schema, table),
            )
            first = rows[0][0]
        assert first == "tenant_id", (
            f"{table}'s primary key starts with {first!r}, not tenant_id -- uniqueness "
            "would be global rather than per-tenant"
        )


def test_reopening_the_same_storage_is_idempotent_and_keeps_data(engine) -> None:
    """Reopening applies the DDL again (IF NOT EXISTS): it must neither fail nor
    wipe what is already there. This is the precondition for every
    survives-a-restart test below."""
    first = PersistentFeatureStore(engine.open(), TENANT)
    first.write(entity_id="z-1", feature_name="f", value=7.0, knowledge_time=_utc(2026, 1, 1))

    second = PersistentFeatureStore(engine.open(), TENANT)  # re-applies core_v0_1.sql
    assert second.get_feature("z-1", "f", as_of=_utc(2026, 1, 2)) == 7.0


# --------------------------------------------------------------------------- #
# 3. Feature store: the strict past-only read, through persistence (SYNTHETIC)
# --------------------------------------------------------------------------- #
def test_asof_read_returns_latest_strictly_past_value(engine) -> None:
    store = PersistentFeatureStore(engine.open(), TENANT)
    store.write(entity_id="z-1", feature_name="lag1", value=10.0, knowledge_time=_utc(2026, 1, 1))
    store.write(entity_id="z-1", feature_name="lag1", value=20.0, knowledge_time=_utc(2026, 1, 2))
    store.write(entity_id="z-1", feature_name="lag1", value=30.0, knowledge_time=_utc(2026, 1, 3))
    assert store.get_feature("z-1", "lag1", as_of=_utc(2026, 1, 3)) == 20.0


def test_asof_read_excludes_a_value_stamped_exactly_at_t(engine) -> None:
    """THE FAILURE INJECTION, through the database: a read at t must NOT see a
    value stamped at t. Strictness lives in the SQL predicate
    (`knowledge_time < ?`), so the row is never fetched, not fetched-then-hidden."""
    store = PersistentFeatureStore(engine.open(), TENANT)
    store.write(entity_id="z-1", feature_name="f", value=1.0, knowledge_time=_utc(2026, 1, 1))
    store.write(entity_id="z-1", feature_name="f", value=99.0, knowledge_time=_utc(2026, 1, 2))
    assert store.get_feature("z-1", "f", as_of=_utc(2026, 1, 2)) == 1.0
    assert store.get_features("z-1", as_of=_utc(2026, 1, 2)) == {"f": 1.0}


def test_asof_read_before_any_knowledge_time_sees_nothing(engine) -> None:
    store = PersistentFeatureStore(engine.open(), TENANT)
    store.write(entity_id="z-1", feature_name="f", value=5.0, knowledge_time=_utc(2026, 6, 1))
    assert store.get_feature("z-1", "f", as_of=_utc(2026, 1, 1)) is None
    assert store.get_features("z-1", as_of=_utc(2026, 1, 1)) == {}


def test_get_features_returns_per_feature_latest_strictly_past(engine) -> None:
    store = PersistentFeatureStore(engine.open(), TENANT)
    store.write(entity_id="z-1", feature_name="lag1", value=1.0, knowledge_time=_utc(2026, 1, 1))
    store.write(entity_id="z-1", feature_name="lag1", value=2.0, knowledge_time=_utc(2026, 1, 5))
    store.write(entity_id="z-1", feature_name="roll7", value=3.0, knowledge_time=_utc(2026, 1, 2))
    store.write(entity_id="z-1", feature_name="roll7", value=4.0, knowledge_time=_utc(2026, 1, 9))
    assert store.get_features("z-1", as_of=_utc(2026, 1, 6)) == {"lag1": 2.0, "roll7": 3.0}


def test_same_knowledge_time_last_write_wins(engine) -> None:
    """A correction recorded at the same instant supersedes what it corrects.
    In memory that falls out of scanning in append order; here it is
    `write_sequence DESC`, an explicit stored column -- so the tie-break is a
    property of the rows, readable by anything, not of a scan order."""
    store = PersistentFeatureStore(engine.open(), TENANT)
    store.write(entity_id="z-1", feature_name="f", value=1.0, knowledge_time=_utc(2026, 1, 1))
    store.write(entity_id="z-1", feature_name="f", value=1.5, knowledge_time=_utc(2026, 1, 1))
    assert store.get_feature("z-1", "f", as_of=_utc(2026, 1, 2)) == 1.5
    assert store.get_features("z-1", as_of=_utc(2026, 1, 2)) == {"f": 1.5}


def test_entities_are_isolated(engine) -> None:
    store = PersistentFeatureStore(engine.open(), TENANT)
    store.write(entity_id="z-1", feature_name="f", value=1.0, knowledge_time=_utc(2026, 1, 1))
    store.write(entity_id="z-2", feature_name="f", value=2.0, knowledge_time=_utc(2026, 1, 1))
    assert store.get_feature("z-1", "f", as_of=_utc(2026, 1, 2)) == 1.0
    assert store.get_feature("z-2", "f", as_of=_utc(2026, 1, 2)) == 2.0
    assert store.get_feature("z-3", "f", as_of=_utc(2026, 1, 2)) is None
    assert store.entities() == frozenset({"z-1", "z-2"})


def test_naive_timestamps_are_rejected_before_anything_is_stored(engine) -> None:
    store = PersistentFeatureStore(engine.open(), TENANT)
    with pytest.raises(ValueError):
        store.write(entity_id="z-1", feature_name="f", value=1.0, knowledge_time=datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        store.get_feature("z-1", "f", as_of=datetime(2026, 1, 2))
    with pytest.raises(ValueError):
        store.get_features("z-1", as_of=datetime(2026, 1, 2))
    assert store.entities() == frozenset()  # the rejected write left no row


def test_history_is_the_append_only_audit_view(engine) -> None:
    """The audit view retains everything ever written, including values an as-of
    read would refuse to show -- and round-trips the entity, so a successful read
    proves the stored columns still validate as a `FeatureValue`."""
    store = PersistentFeatureStore(engine.open(), TENANT)
    first = store.write(entity_id="z-1", feature_name="f", value=1.0, knowledge_time=_utc(2026, 1, 1))
    second = store.write(entity_id="z-1", feature_name="f", value=2.0, knowledge_time=_utc(2026, 1, 2))
    assert store.history("z-1", "f") == (first, second)


def test_double_precision_values_round_trip_bit_identically(engine) -> None:
    """The `DOUBLE PRECISION`-not-`REAL` choice, under test. PostgreSQL's REAL is
    float4: these values would come back CHANGED on the production engine and
    unchanged on the reference one, silently breaking the bit-identical claim the
    leakage tests make. Exact `==`, deliberately -- not pytest.approx."""
    store = PersistentFeatureStore(engine.open(), TENANT)
    values = [math.pi, 0.1 + 0.2, 1.0 / 3.0, 1e-300, 1.2345678901234567e8, -2.718281828459045]
    for index, value in enumerate(values):
        store.write(
            entity_id="z-1", feature_name=f"f{index}", value=value, knowledge_time=_utc(2026, 1, 1)
        )
    read_back = store.get_features("z-1", as_of=_utc(2026, 1, 2))
    assert read_back == {f"f{i}": v for i, v in enumerate(values)}


def test_persistent_and_in_memory_stores_agree_on_every_asof_read(engine) -> None:
    """Differential test (SYNTHETIC): the same writes into both backends, then
    every as-of read on a grid that deliberately INCLUDES the exact knowledge
    stamps (the boundary the strict `<` governs) and points either side of them."""
    writes = [
        ("z-1", "lag1", 10.0, _utc(2026, 1, 1)),
        ("z-1", "lag1", 20.0, _utc(2026, 1, 3)),
        ("z-1", "lag1", 25.0, _utc(2026, 1, 3)),  # same-instant correction
        ("z-1", "roll7", 1.5, _utc(2026, 1, 2)),
        ("z-2", "lag1", 99.0, _utc(2026, 1, 2)),
    ]
    reference = FeatureStore()
    persistent = PersistentFeatureStore(engine.open(), TENANT)
    for entity_id, feature_name, value, knowledge_time in writes:
        for store in (reference, persistent):
            store.write(
                entity_id=entity_id,
                feature_name=feature_name,
                value=value,
                knowledge_time=knowledge_time,
            )

    grid = [
        _utc(2025, 12, 31),
        _utc(2026, 1, 1),  # exactly the first stamp
        _utc(2026, 1, 2),
        _utc(2026, 1, 3),  # exactly the corrected stamp
        _utc(2026, 1, 4),
    ]
    for as_of in grid:
        for entity_id in ("z-1", "z-2", "z-3"):
            assert reference.get_features(entity_id, as_of=as_of) == persistent.get_features(
                entity_id, as_of=as_of
            ), f"backends disagree for {entity_id} at {as_of}"
            for feature_name in ("lag1", "roll7"):
                assert reference.get_feature(
                    entity_id, feature_name, as_of=as_of
                ) == persistent.get_feature(entity_id, feature_name, as_of=as_of)
    assert reference.entities() == persistent.entities()


def test_feature_values_survive_a_reopen(engine) -> None:
    """The gap this packet closes, stated at its simplest: write, drop the
    connection, open a new one over the same storage, read the same answers."""
    first = PersistentFeatureStore(engine.open(), TENANT)
    first.write(entity_id="z-1", feature_name="f", value=1.0, knowledge_time=_utc(2026, 1, 1))
    first.write(entity_id="z-1", feature_name="f", value=2.0, knowledge_time=_utc(2026, 1, 5))
    before_history = first.history("z-1", "f")
    first._db.close()

    restarted = PersistentFeatureStore(engine.open(), TENANT)
    assert restarted.get_feature("z-1", "f", as_of=_utc(2026, 1, 3)) == 1.0
    assert restarted.get_feature("z-1", "f", as_of=_utc(2026, 1, 6)) == 2.0
    assert restarted.history("z-1", "f") == before_history
    assert restarted.entities() == frozenset({"z-1"})


# --------------------------------------------------------------------------- #
# 4. THE LEAKAGE GUARANTEE, PROVED THROUGH THE PERSISTENT PATH (REAL DATA)
# --------------------------------------------------------------------------- #
# Same mechanical discipline as ADR-0034 / realdata/leakage_audit.py: corrupt
# everything after a cutoff, and assert every as-of read at/<= the cutoff is
# bit-identical. Windowed to the first _WINDOW observed days so the PostgreSQL
# parameter stays a few seconds rather than a few minutes -- the property is
# per-(entity, feature) and holds pointwise, so a window exercises it exactly as
# the full panel does, just fewer times.
_ENTITY = "aar_nyc_scheduled_trips"  # opaque id, no PII
_FEATURE = "scheduled_trips"
_WINDOW = 300


def _load_aar_daily() -> list[tuple[datetime, float]]:
    import pandas as pd

    df = pd.read_csv(_AAR_DAILY, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    rows = [
        (ts.to_pydatetime().replace(tzinfo=timezone.utc), float(v))
        for ts, v in zip(df["date"], df["scheduled_trips"])
    ]
    return rows[:_WINDOW]


def _write_series(
    store: PersistentFeatureStore, entity_id: str, rows: list[tuple[datetime, float]]
) -> None:
    for knowledge_time, value in rows:
        store.write(
            entity_id=entity_id,
            feature_name=_FEATURE,
            value=value,
            knowledge_time=knowledge_time,
        )


@pytest.mark.skipif(not _AAR_DAILY.exists(), reason="real AAR daily panel absent")
def test_real_panel_asof_read_is_strictly_past_through_persistence(engine) -> None:
    """REAL DATA: an as-of read at day d returns the count known the previous
    observed day, never day d's own (same-stamp) value -- read back out of the
    database, not out of a Python dict."""
    rows = _load_aar_daily()
    store = PersistentFeatureStore(engine.open(), TENANT)
    _write_series(store, _ENTITY, rows)
    assert store.get_feature(_ENTITY, _FEATURE, as_of=rows[2][0]) == rows[1][1]


@pytest.mark.skipif(not _AAR_DAILY.exists(), reason="real AAR daily panel absent")
def test_real_panel_future_corruption_leaves_past_bit_identical_through_persistence(
    engine,
) -> None:
    """REAL DATA -- THE LEAKAGE GUARANTEE, THROUGH THE PERSISTENT BACKEND.

    Corrupt every row stamped after a cutoff, persist the corrupted series, and
    assert every as-of read at a label time <= cutoff is bit-identical to the
    baseline. Run at three cutoffs across the timeline. If a past read changed
    when only the future was corrupted, the persistent store would be leaking.

    Each corrupted rebuild is written under its own entity id in the SAME
    database rather than into a fresh one: the invariant is per-(entity,
    feature), so this is the same experiment, and it keeps the baseline series
    physically present in the same table while the corrupted one is queried --
    a slightly harsher setup than a clean rebuild, not a laxer one.
    """
    rows = _load_aar_daily()
    store = PersistentFeatureStore(engine.open(), TENANT)
    _write_series(store, _ENTITY, rows)
    dates = [d for d, _ in rows]
    rng = np.random.default_rng(0)

    for index, cutoff in enumerate(
        (dates[len(dates) // 4], dates[len(dates) // 2], dates[3 * len(dates) // 4])
    ):
        corrupted_rows = [
            (d, (float(rng.integers(10_000_000, 100_000_000)) if d > cutoff else v))
            for d, v in rows
        ]
        corrupted_entity = f"{_ENTITY}__corrupt_{index}"
        _write_series(store, corrupted_entity, corrupted_rows)

        checked = 0
        for label_time in dates:
            if label_time > cutoff:
                continue
            before = store.get_feature(_ENTITY, _FEATURE, as_of=label_time)
            after = store.get_feature(corrupted_entity, _FEATURE, as_of=label_time)
            assert before == after, (
                f"leak at as_of={label_time} cutoff={cutoff}: {before} != {after}"
            )
            checked += 1
        assert checked > 0  # the cutoff actually exercised some past reads


@pytest.mark.skipif(not _AAR_DAILY.exists(), reason="real AAR daily panel absent")
def test_real_panel_stored_rows_corrupted_in_place_leave_past_bit_identical(engine) -> None:
    """REAL DATA -- the version of the leakage test only a PERSISTENT store can be
    asked to pass.

    The previous test rebuilds from corrupted inputs. This one corrupts the
    STORED ROWS THEMSELVES with raw SQL (the store issues no UPDATE anywhere;
    this is a test-only tamper, exactly as `tamper_with_row` is for the canonical
    stores), drops the connection, reopens, and re-reads. The corrupted future is
    physically sitting in the same table, in the same series, on disk -- and
    every as-of read at/<= the cutoff is still bit-identical, because the engine
    never selects those rows for a past label time.
    """
    rows = _load_aar_daily()
    database = engine.open()
    store = PersistentFeatureStore(database, TENANT)
    _write_series(store, _ENTITY, rows)
    dates = [d for d, _ in rows]
    cutoff = dates[len(dates) // 2]

    baseline = {d: store.get_feature(_ENTITY, _FEATURE, as_of=d) for d in dates if d <= cutoff}

    # Tamper: overwrite every stored value whose knowledge time is strictly after
    # the cutoff. Raw SQL on purpose -- the store's own API cannot do this. The
    # storage form of the timestamp is re-derived here rather than imported from
    # the module under test, so this tamper does not inherit a bug from it.
    #
    # `use_tenant` first: on PostgreSQL this UPDATE runs under core_rls_postgres.sql,
    # whose USING clause would otherwise hide the very rows the tamper is meant to
    # reach -- and a tamper that silently touched NOTHING would make the assertions
    # below pass for the wrong reason. The tenant is named in the WHERE clause too,
    # so the tamper is the same statement on SQLite, which has no policy.
    database.use_tenant(TENANT)
    database.execute(
        "UPDATE feature_values SET value = ? "
        "WHERE tenant_id = ? AND entity_id = ? AND feature_name = ? AND knowledge_time > ?",
        (
            987654321.0,
            str(TENANT),
            _ENTITY,
            _FEATURE,
            cutoff.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00"),
        ),
    )
    database.commit()
    database.close()

    restarted = PersistentFeatureStore(engine.open(), TENANT)
    for label_time, expected in baseline.items():
        assert restarted.get_feature(_ENTITY, _FEATURE, as_of=label_time) == expected, (
            f"in-place future corruption changed a past read at {label_time}"
        )
    assert baseline  # the cutoff actually exercised some past reads
    # AND the tamper really landed. Under row-level security a raw UPDATE issued
    # with the wrong (or no) tenant in scope silently matches ZERO rows, which
    # would make every bit-identical assertion above vacuously true. A read after
    # the cutoff must therefore SEE the corruption.
    assert restarted.get_feature(_ENTITY, _FEATURE, as_of=dates[-1]) == 987654321.0, (
        "the in-place tamper matched no rows -- the leakage assertions above would "
        "have been proving nothing at all"
    )


@pytest.mark.skipif(not _AAR_DAILY.exists(), reason="real AAR daily panel absent")
def test_real_panel_corruption_would_change_a_future_read_through_persistence(engine) -> None:
    """REAL DATA control: the corruption is real. A read whose label time is AFTER
    the cutoff -- thus allowed to see corrupted rows -- DOES change. Without this,
    the bit-identical results above could be an inert no-op corruption rather than
    the strict-past rule at work."""
    rows = _load_aar_daily()
    store = PersistentFeatureStore(engine.open(), TENANT)
    _write_series(store, _ENTITY, rows)
    dates = [d for d, _ in rows]
    cutoff = dates[len(dates) // 2]
    rng = np.random.default_rng(1)
    corrupted_rows = [
        (d, (float(rng.integers(10_000_000, 100_000_000)) if d > cutoff else v)) for d, v in rows
    ]
    _write_series(store, f"{_ENTITY}__control", corrupted_rows)

    late = dates[-1]
    assert store.get_feature(_ENTITY, _FEATURE, as_of=late) != store.get_feature(
        f"{_ENTITY}__control", _FEATURE, as_of=late
    )


# --------------------------------------------------------------------------- #
# 5. The promotion ledger persists, complete and in order
# --------------------------------------------------------------------------- #
def test_promotion_gate_and_roles_persist_across_a_reopen(engine) -> None:
    """SYNTHETIC. The gate runs, the roles change, the connection drops, a new
    one opens: champion, challenger pool and canary are all still there."""
    a, b = _model_version(), _model_version()
    registry = _registry_with(a, b)
    database = engine.open()
    controller = PersistentPromotionController(registry, database, TENANT)

    controller.register_challenger(TASK, a.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, a.model_version_id, metric_name="wape", challenger_metric=0.2,
        higher_is_better=False, decided_at=_utc(2026, 6, 1),
    )
    controller.register_challenger(TASK, b.model_version_id)
    controller.set_canary(TASK, b.model_version_id, 0.25)
    database.close()

    restarted = PersistentPromotionController(registry, engine.open(), TENANT)
    assert restarted.champion(TASK) == a.model_version_id
    assert restarted.challengers(TASK) == (b.model_version_id,)
    assert restarted.canary(TASK) == (b.model_version_id, 0.25)
    assert restarted.route(TASK, 0.1) == b.model_version_id  # inside the canary slice
    assert restarted.route(TASK, 0.9) == a.model_version_id  # outside it
    assert restarted.rollout(TASK).canary_fraction == 0.25


def test_the_ledger_records_rejected_challengers_as_durably_as_promoted_ones(engine) -> None:
    """SYNTHETIC. An audit trail that only kept the promotions would answer "why
    is this serving?" but not "what else was tried, and why was it refused?" --
    the promotion analogue of the decision ledger's "why not the alternatives".
    Order and completeness both survive the reopen."""
    a, b, c = _model_version(), _model_version(), _model_version()
    registry = _registry_with(a, b, c)
    database = engine.open()
    controller = PersistentPromotionController(registry, database, TENANT)

    controller.register_challenger(TASK, a.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, a.model_version_id, metric_name="wape", challenger_metric=0.30,
        higher_is_better=False, decided_at=_utc(2026, 6, 1),
    )
    controller.register_challenger(TASK, b.model_version_id)
    rejected = controller.evaluate_and_maybe_promote(  # worse -> refused
        TASK, b.model_version_id, metric_name="wape", challenger_metric=0.40,
        incumbent_metric=0.30, higher_is_better=False, decided_at=_utc(2026, 6, 2),
    )
    controller.register_challenger(TASK, c.model_version_id)
    promoted = controller.evaluate_and_maybe_promote(  # better -> accepted
        TASK, c.model_version_id, metric_name="wape", challenger_metric=0.20,
        incumbent_metric=0.30, higher_is_better=False, decided_at=_utc(2026, 6, 3),
    )
    assert rejected.promoted is False and promoted.promoted is True
    before = controller.decisions()
    database.close()

    restarted = PersistentPromotionController(registry, engine.open(), TENANT)
    after = restarted.decisions()
    assert after == before  # complete, and equal field-for-field
    assert [d.promoted for d in after] == [True, False, True]  # and in decision order
    assert [d.decided_at for d in after] == [_utc(2026, 6, 1), _utc(2026, 6, 2), _utc(2026, 6, 3)]
    assert after[1].margin == pytest.approx(-0.10)  # the refused challenger's margin
    assert after[1].rationale == rejected.rationale  # including WHY it was refused
    assert restarted.champion(TASK) == c.model_version_id


def test_rollback_records_persist_in_order(engine) -> None:
    """SYNTHETIC. Two promotions then two rollbacks: the champion walks back down
    the history stack, and both rollback records read back in order after a
    reopen."""
    a, b, c = _model_version(), _model_version(), _model_version()
    registry = _registry_with(a, b, c)
    database = engine.open()
    controller = PersistentPromotionController(registry, database, TENANT)

    for index, version in enumerate((a, b, c)):
        controller.register_challenger(TASK, version.model_version_id)
        controller.evaluate_and_maybe_promote(
            TASK, version.model_version_id, metric_name="wape",
            challenger_metric=0.30 - 0.05 * index,
            incumbent_metric=None if index == 0 else 0.30 - 0.05 * (index - 1),
            higher_is_better=False, decided_at=_utc(2026, 6, 1 + index),
        )
    assert controller.champion(TASK) == c.model_version_id

    controller.rollback(TASK, decided_at=_utc(2026, 6, 10), reason="canary error spike")
    assert controller.champion(TASK) == b.model_version_id
    controller.rollback(TASK, decided_at=_utc(2026, 6, 11), reason="still degraded")
    assert controller.champion(TASK) == a.model_version_id
    before = controller.rollbacks()
    database.close()

    restarted = PersistentPromotionController(registry, engine.open(), TENANT)
    assert restarted.rollbacks() == before
    assert [r.reason for r in restarted.rollbacks()] == ["canary error spike", "still degraded"]
    assert [r.from_champion_id for r in restarted.rollbacks()] == [
        c.model_version_id,
        b.model_version_id,
    ]
    assert restarted.champion(TASK) == a.model_version_id
    # the demoted champions rejoined the challenger pool and survived the reopen
    assert set(restarted.challengers(TASK)) == {b.model_version_id, c.model_version_id}


def test_a_challenger_cannot_become_champion_without_passing_the_gate(engine) -> None:
    """FAILURE INJECTION, persisted. `evaluate_and_maybe_promote` is the only path
    to champion: a refused challenger stays a challenger, and nothing else in the
    module writes `promotion_champions`."""
    a, b = _model_version(), _model_version()
    controller = PersistentPromotionController(_registry_with(a, b), engine.open(), TENANT)
    controller.register_challenger(TASK, a.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, a.model_version_id, metric_name="wape", challenger_metric=0.2,
        higher_is_better=False, decided_at=_utc(2026, 6, 1),
    )
    controller.register_challenger(TASK, b.model_version_id)
    decision = controller.evaluate_and_maybe_promote(
        TASK, b.model_version_id, metric_name="wape", challenger_metric=0.25,
        incumbent_metric=0.2, higher_is_better=False, decided_at=_utc(2026, 6, 2),
    )
    assert decision.promoted is False
    assert controller.champion(TASK) == a.model_version_id
    assert b.model_version_id in controller.challengers(TASK)


def test_an_unregistered_challenger_cannot_be_gated(engine) -> None:
    a, b = _model_version(), _model_version()
    controller = PersistentPromotionController(_registry_with(a, b), engine.open(), TENANT)
    controller.register_challenger(TASK, a.model_version_id)
    with pytest.raises(RoleAssignmentError):
        controller.evaluate_and_maybe_promote(
            TASK, b.model_version_id, metric_name="wape", challenger_metric=0.1,
            higher_is_better=False, decided_at=_utc(2026, 6, 1),
        )
    assert controller.decisions() == ()  # nothing was recorded either


def test_rolling_back_with_no_prior_champion_is_refused(engine) -> None:
    a = _model_version()
    controller = PersistentPromotionController(_registry_with(a), engine.open(), TENANT)
    controller.register_challenger(TASK, a.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, a.model_version_id, metric_name="wape", challenger_metric=0.2,
        higher_is_better=False, decided_at=_utc(2026, 6, 1),
    )
    with pytest.raises(NoRollbackTargetError):
        controller.rollback(TASK, decided_at=_utc(2026, 6, 2), reason="nothing to fall back to")
    assert controller.rollbacks() == ()


def test_canary_traffic_fraction_is_bounded_in_python_and_in_the_database(engine) -> None:
    """FAILURE INJECTION. A canary taking all the traffic would just be the
    champion, so [0, 1) is enforced twice: by the controller, and by a CHECK
    constraint that also stops a writer which bypassed the controller entirely."""
    a, b = _model_version(), _model_version()
    database = engine.open()
    controller = PersistentPromotionController(_registry_with(a, b), database, TENANT)
    controller.register_challenger(TASK, a.model_version_id)
    for bad in (1.0, 1.5, -0.1):
        with pytest.raises(TrafficFractionError):
            controller.set_canary(TASK, a.model_version_id, bad)
    assert controller.canary(TASK) is None

    # And the database refuses it too, on both engines. Stamped with the acting
    # tenant on purpose: the CHECK constraint is what must reject this row, so the
    # row is made legal in every OTHER respect first -- a foreign tenant_id would
    # be refused by the RLS policy instead and prove a different thing (that case
    # has its own test in test_core_tenant_isolation.py).
    database.use_tenant(TENANT)
    with pytest.raises(_INTEGRITY_ERRORS):
        database.execute(
            "INSERT INTO promotion_canaries (tenant_id, task, model_version_id, "
            "traffic_fraction) VALUES (?, ?, ?, ?)",
            (str(TENANT), TASK, str(a.model_version_id), 1.0),
        )


def test_the_registrys_own_champion_pointer_is_never_touched(engine) -> None:
    """The ADR-0034 composition invariant, still true once state is persisted:
    the controller owns the richer role state, the registry keeps its ADR-0010
    single pointer, and the two never fight over one piece of state."""
    a = _model_version()
    registry = _registry_with(a)
    controller = PersistentPromotionController(registry, engine.open(), TENANT)
    controller.register_challenger(TASK, a.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, a.model_version_id, metric_name="wape", challenger_metric=0.2,
        higher_is_better=False, decided_at=_utc(2026, 6, 1),
    )
    assert controller.champion(TASK) == a.model_version_id
    assert registry.champion(TASK) is None  # untouched


def test_persistent_and_in_memory_controllers_agree_on_a_full_lifecycle(engine) -> None:
    """Differential test (SYNTHETIC): the identical lifecycle script through both
    backends, then every observable compared. Signature parity says the contract
    LOOKS the same; this says it BEHAVES the same -- including the refused
    decision's margin and rationale, which is where a re-implementation would
    most plausibly drift."""
    a, b, c = _model_version(), _model_version(), _model_version()
    reference = PromotionController(_registry_with(a, b, c))
    persistent = PersistentPromotionController(_registry_with(a, b, c), engine.open(), TENANT)

    for controller in (reference, persistent):
        controller.register_challenger(TASK, a.model_version_id)
        controller.evaluate_and_maybe_promote(
            TASK, a.model_version_id, metric_name="wape", challenger_metric=0.30,
            higher_is_better=False, decided_at=_utc(2026, 6, 1),
        )
        controller.register_challenger(TASK, b.model_version_id)
        controller.set_canary(TASK, b.model_version_id, 0.1)
        controller.evaluate_and_maybe_promote(
            TASK, b.model_version_id, metric_name="wape", challenger_metric=0.31,
            incumbent_metric=0.30, higher_is_better=False, decided_at=_utc(2026, 6, 2),
        )
        controller.register_challenger(TASK, c.model_version_id)
        controller.evaluate_and_maybe_promote(
            TASK, c.model_version_id, metric_name="wape", challenger_metric=0.20,
            incumbent_metric=0.30, higher_is_better=False, decided_at=_utc(2026, 6, 3),
        )
        controller.rollback(TASK, decided_at=_utc(2026, 6, 4), reason="latency regression")
        controller.demote_challenger(TASK, b.model_version_id)

    assert persistent.champion(TASK) == reference.champion(TASK)
    assert persistent.challengers(TASK) == reference.challengers(TASK)
    assert persistent.canary(TASK) == reference.canary(TASK)
    assert persistent.rollout(TASK) == reference.rollout(TASK)
    assert persistent.decisions() == reference.decisions()
    assert persistent.rollbacks() == reference.rollbacks()
    for roll in (0.0, 0.05, 0.5, 0.99):
        assert persistent.route(TASK, roll) == reference.route(TASK, roll)


def test_feature_store_and_promotion_ledger_share_one_database(engine) -> None:
    """Both Program D stores apply the same `core_v0_1.sql` (every CREATE is
    IF NOT EXISTS), so they can live in one database without either one's DDL
    failing on the other's tables -- and neither disturbs the other's rows."""
    a = _model_version()
    database = engine.open()
    features = PersistentFeatureStore(database, TENANT)
    controller = PersistentPromotionController(_registry_with(a), database, TENANT)

    features.write(entity_id="z-1", feature_name="f", value=3.0, knowledge_time=_utc(2026, 1, 1))
    controller.register_challenger(TASK, a.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, a.model_version_id, metric_name="wape", challenger_metric=0.2,
        higher_is_better=False, decided_at=_utc(2026, 6, 1),
    )

    assert features.get_feature("z-1", "f", as_of=_utc(2026, 1, 2)) == 3.0
    assert controller.champion(TASK) == a.model_version_id
    assert len(controller.decisions()) == 1
