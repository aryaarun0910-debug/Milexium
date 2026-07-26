"""Adversarial conformance: tenant isolation on the PROGRAM D tables
(MX-D-TENANT-ISOLATION-006).

WHAT GAP THIS CLOSES. ADR-0041 made Program D's adaptive memory persistent --
`feature_values` plus the six promotion tables in
`app/core/sql/core_v0_1.sql` -- and named the hole it left in its own
limitations: "No tenant column or RLS on Program D tables ... today these tables
are not tenant-isolated, and that must be closed before a second operator's data
lands in them." Every other tenant-scoped table in this repository is guarded
(ADR-0018/0037/0043/0046). These seven were not. A second operator's feature
values and promotion ledger would have sat in the same tables as the first's with
nothing between them.

The column (`tenant_id NOT NULL`, leading every primary key) is in
`core_v0_1.sql`; the boundary is `app/core/sql/core_rls_postgres.sql`,
applied only on PostgreSQL. These tests exist to prove the BOUNDARY, so every
cross-tenant read below is RAW SQL with the `tenant_id` filter DELIBERATELY
DELETED. What is under test is the database policy, never a Python code path --
a WHERE clause is application code that a refactor can drop; a policy is not.

FOUR WAYS THIS SUITE COULD PASS FOR THE WRONG REASON, each closed by a test
rather than argued away:

1. *The acting role bypasses RLS anyway.* `test_the_acting_role_is_bound_by_row_security`
   asserts `milexium_dev` holds neither `rolsuper` nor `rolbypassrls` (ADR-0006)
   before anything else here is claimed -- both are checked BEFORE ownership and
   before FORCE, so neither ENABLE nor FORCE could rescue a privileged connection.
2. *The OWNER bypasses the policy.* `milexium_dev` owns every table
   `CoreDatabase.postgres()` creates, and a table owner bypasses RLS unless FORCE
   is set -- the false green `app/canonical/sql/rls_postgres.sql`'s header is
   about. `test_force_row_level_security_is_load_bearing` lifts FORCE, watches the
   boundary collapse, and restores it.
3. *The block is passing on an empty table.* Every cross-tenant denial is paired
   with a positive control proving the row it is not seeing exists and IS visible
   to its own tenant.
4. *The deny-all default is only tested for a NULL GUC.* `current_setting(name,
   true)` returns NULL only when the GUC was NEVER set; after `RESET` it returns
   the EMPTY STRING, which an `IS NOT NULL` guard happily accepts. Both cases get
   their own test, and the reset case asserts the empty string EXPLICITLY.

AND THE ONE THAT IS SPECIFIC TO PROGRAM D. ADR-0041's load-bearing invariant is
the leakage guarantee: an as-of read at label time t returns only values whose
`knowledge_time` is STRICTLY < t, enforced as a SQL predicate. Conjoining a
tenant predicate must not weaken it, and the tenant predicate must not be
weakened by it either. `test_a_tenant_crossing_asof_read_returns_nothing_even_at_a_permissive_timestamp`
and `test_another_tenants_corrupted_future_cannot_change_this_tenants_past_read`
prove the two rules COMPOSE: what comes back is the intersection, and neither
predicate can rescue a row the other excludes.

The PostgreSQL half skips cleanly (never fails) when the native `milexium_dev`
instance on 5432 is absent, so CI stays green -- but a skip proves nothing, so
the packet's evidence requirement is that these RUN. The store-level half is
parametrised `[sqlite]`/`[postgres]` and its SQLite parameter always runs.

REAL vs SYNTHETIC is labelled per test. The real panel is NYC Access-A-Ride daily
scheduled trips (realdata/panels/aar_daily.csv), public aggregate data.
Status: Demonstrated, never operator-Validated.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")  # skip the whole module if absent

from psycopg import sql  # noqa: E402

from app.canonical import ModelVersion, ModelVersionId, TenantId, new_id  # noqa: E402
from app.canonical.postgres_storage import is_reachable as pg_is_reachable  # noqa: E402
from app.core.feature_store import (  # noqa: E402
    CoreDatabase,
    PersistentFeatureStore,
    _iso_utc,
    _read_dev_password,
)
from app.core.model_registry import ModelRegistry  # noqa: E402
from app.core.promotion import PersistentPromotionController  # noqa: E402

TASK = "forecast.demand"

# --- REAL aggregate panel (labelled): NYC Access-A-Ride daily scheduled trips.
_AAR_DAILY = Path(__file__).resolve().parents[3] / "realdata" / "panels" / "aar_daily.csv"
# A short window: the leakage invariant is per-(entity, feature) and holds
# pointwise, so 60 observed days exercise it exactly as the full panel does --
# just fewer times -- and keep this adversarial file quick enough to actually run.
_WINDOW = 60
_ENTITY = "aar_nyc_scheduled_trips"  # opaque id, no PII
_FEATURE = "scheduled_trips"

# Every table core_v0_1.sql defines, in the order the file declares them. All
# seven are Program D runtime state and all seven now carry tenant_id.
_PROGRAM_D_TABLES = (
    "feature_values",
    "promotion_decisions",
    "promotion_rollbacks",
    "promotion_champions",
    "promotion_champion_history",
    "promotion_challengers",
    "promotion_canaries",
)


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Raw row templates: one legal row per table, stamped with a caller-chosen
# tenant. Deliberately NOT routed through PersistentFeatureStore /
# PersistentPromotionController -- those set the GUC and name tenant_id in their
# own WHERE clauses, so a test that leant on them would be proving the Python
# helper rather than the policy.
# --------------------------------------------------------------------------- #
def _row_for(table: str, tenant: TenantId) -> tuple[str, tuple]:
    """(column list, values) for one syntactically legal row of `table`."""
    model = str(new_id(ModelVersionId))
    if table == "feature_values":
        return (
            "tenant_id, entity_id, feature_name, value, knowledge_time, write_sequence",
            (str(tenant), "zone-1", "lag1", 42.0, _iso_utc(_utc(2026, 1, 1)), 1),
        )
    if table == "promotion_decisions":
        return (
            "tenant_id, decision_sequence, task, challenger_id, incumbent_id, metric_name, "
            "challenger_metric, incumbent_metric, higher_is_better, min_improvement, margin, "
            "promoted, decided_at, rationale",
            (
                str(tenant), 1, TASK, model, None, "wape",
                0.2, None, 0, 0.0, None, 1, _iso_utc(_utc(2026, 6, 1)), "first champion",
            ),
        )
    if table == "promotion_rollbacks":
        return (
            "tenant_id, rollback_sequence, task, from_champion_id, to_champion_id, "
            "decided_at, reason",
            (str(tenant), 1, TASK, model, str(new_id(ModelVersionId)),
             _iso_utc(_utc(2026, 6, 2)), "error spike"),
        )
    if table == "promotion_champions":
        return ("tenant_id, task, champion_id", (str(tenant), TASK, model))
    if table == "promotion_champion_history":
        return (
            "tenant_id, task, stack_position, champion_id",
            (str(tenant), TASK, 1, model),
        )
    if table == "promotion_challengers":
        return (
            "tenant_id, task, model_version_id, enrol_sequence",
            (str(tenant), TASK, model, 1),
        )
    if table == "promotion_canaries":
        return (
            "tenant_id, task, model_version_id, traffic_fraction",
            (str(tenant), TASK, model, 0.25),
        )
    raise AssertionError(f"unknown Program D table {table!r}")  # pragma: no cover


def _insert_raw(database: CoreDatabase, table: str, tenant: TenantId) -> None:
    """Insert one row into `table` for `tenant`, by raw SQL, under that tenant's
    own GUC (which is the only way the WITH CHECK half will permit it)."""
    columns, values = _row_for(table, tenant)
    database.use_tenant(tenant)
    placeholders = ", ".join("?" for _ in values)
    database.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",  # noqa: S608
        values,
    )
    database.commit()


def _raw_tenant_ids(database: CoreDatabase, table: str) -> list[str]:
    """A raw, UNFILTERED scan of `table`. No WHERE clause at all -- if the policy
    is not the boundary, every tenant's rows come back."""
    return [row[0] for row in database.query(f"SELECT tenant_id FROM {table}")]  # noqa: S608


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def pg() -> CoreDatabase:
    """A PostgreSQL `CoreDatabase` in its own disposable `mx_core_<uuid>` schema,
    with `core_rls_postgres.sql` applied. Skips (never fails) when the native
    instance is absent."""
    if not pg_is_reachable():
        pytest.skip(
            "PostgreSQL (milexium_dev, port 5432) is not reachable on this machine; "
            "skipping the Program D tenant-isolation policy tests"
        )
    database = CoreDatabase.postgres()
    try:
        yield database
    finally:
        try:
            database._conn.rollback()  # a test may have aborted the transaction
        except Exception:  # pragma: no cover - teardown must never mask a failure
            pass
        database.drop_schema()
        database.close()


@pytest.fixture(params=["sqlite", "postgres"])
def core_db(request, tmp_path) -> CoreDatabase:
    """The SAME store-level assertions on both engines. On SQLite the boundary is
    the stores' own `tenant_id = ?` predicates (there is no RLS to apply); on
    PostgreSQL those predicates sit INSIDE the policy. Running both is what makes
    "the store is tenant-scoped" an engine-independent property and the policy an
    extra, provable layer rather than the only thing holding."""
    if request.param == "postgres":
        if not pg_is_reachable():
            pytest.skip("PostgreSQL (milexium_dev) is not reachable on this machine")
        database = CoreDatabase.postgres(schema=f"mx_core_iso_{uuid.uuid4().hex}")
        try:
            yield database
        finally:
            try:
                database._conn.rollback()
            except Exception:  # pragma: no cover
                pass
            database.drop_schema()
            database.close()
    else:
        database = CoreDatabase.sqlite(str(tmp_path / "core_iso.db"))
        try:
            yield database
        finally:
            database.close()


def _model_version(tenant: TenantId) -> ModelVersion:
    """SYNTHETIC model-version fixture (the controller's tenant scoping is what
    is under test, not the registry)."""
    return ModelVersion(
        model_version_id=new_id(ModelVersionId),
        tenant_id=tenant,
        task=TASK,
        training_data_manifest_hash="deadbeef" * 8,
        feature_schema_version="zone_hour_demand_v1",
        evaluation_window_start=_utc(2026, 3, 2),
        evaluation_window_end=_utc(2026, 5, 31),
        artifact_hash="cafebabe" * 8,
    )


def _registry_with(*versions: ModelVersion) -> ModelRegistry:
    registry = ModelRegistry()
    for version in versions:
        registry.register(version)
    return registry


# =========================================================================
# 0. The preconditions everything else rests on
# =========================================================================


def test_the_acting_role_is_bound_by_row_security(pg) -> None:
    """If the acting role were a superuser or held BYPASSRLS, every policy in
    `core_rls_postgres.sql` would be inert and this whole module would be a
    tautology measuring WHERE clauses that are no longer there.

    Both attributes are checked by PostgreSQL BEFORE ownership and before FORCE,
    so neither ENABLE nor FORCE could rescue a privileged connection. ADR-0006
    makes `milexium_dev` an ordinary role precisely so this assertion can hold;
    asserting it is what lets every later result in this file be read as
    evidence."""
    acting, is_super, bypasses = pg.query(
        "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles "
        "WHERE rolname = current_user"
    )[0]

    assert is_super is False, (
        f"the Program D store is acting as superuser {acting!r}, which bypasses row "
        "security outright -- every isolation assertion in this module would pass "
        "for the wrong reason"
    )
    assert bypasses is False, f"acting role {acting!r} holds BYPASSRLS"


@pytest.mark.parametrize("table", _PROGRAM_D_TABLES)
def test_the_acting_role_owns_the_program_d_tables(pg, table: str) -> None:
    """FORCE is only meaningful against the OWNER. For any other role an ordinary
    privilege error, not the policy, would be what stands in the way, and
    `test_force_row_level_security_is_load_bearing` would prove nothing when it
    lifts FORCE. `CoreDatabase.postgres()` creates the schema and its tables
    itself, so it owns them -- asserted, not assumed."""
    (owner,) = pg.query(
        "SELECT c.relowner::regrole::text FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = ? AND c.relname = ?",
        (pg.schema, table),
    )[0]
    (acting,) = pg.query("SELECT current_user")[0]

    assert owner == acting, (
        f"{table} is owned by {owner!r} but the store acts as {acting!r} -- FORCE "
        "would not be what constrains it"
    )


# =========================================================================
# 1. The policy is installed, on every Program D table, with FORCE
# =========================================================================


@pytest.mark.parametrize("table", _PROGRAM_D_TABLES)
def test_program_d_tables_have_rls_enabled_and_forced(pg, table: str) -> None:
    """Read straight out of `pg_class` rather than inferred from behaviour: an
    ENABLE-only setup fails HERE, explicitly, instead of being caught indirectly
    (or missed). `relforcerowsecurity` is the bit that actually matters, because
    the acting role owns these tables -- see the owner-bypass note at the top of
    `core_rls_postgres.sql`."""
    row = pg.query(
        "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = ? AND c.relname = ?",
        (pg.schema, table),
    )
    assert row, f"{table} does not exist in the Program D schema"
    enabled, forced = row[0]
    assert enabled is True, (
        f"{table} has no ROW LEVEL SECURITY -- this is the ADR-0041 gap "
        "MX-D-TENANT-ISOLATION-006 exists to close"
    )
    assert forced is True, (
        f"{table} has ENABLE but not FORCE -- milexium_dev OWNS it and would bypass "
        "the policy, so every isolation test below would pass for the wrong reason"
    )


@pytest.mark.parametrize("table", _PROGRAM_D_TABLES)
def test_each_program_d_table_carries_exactly_one_tenant_policy(pg, table: str) -> None:
    """A table with RLS enabled and NO policy denies everything, which looks like
    isolation and is actually an outage; a table with several could be permissive
    in a way no single policy's text reveals (multiple PERMISSIVE policies are
    OR-ed). Exactly one, named as in `rls_postgres.sql`, is the shape intended --
    and this test is also what catches the reopen path double-applying the file."""
    names = [
        row[0]
        for row in pg.query(
            "SELECT p.polname FROM pg_policy p "
            "JOIN pg_class c ON c.oid = p.polrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = ? AND c.relname = ?",
            (pg.schema, table),
        )
    ]
    assert names == ["tenant_isolation"], f"{table} has policies {names!r}"


def test_reapplying_the_rls_file_is_idempotent(pg) -> None:
    """`CoreDatabase.postgres(schema=...)` REOPENS a named schema -- that is how
    "state survives a restart" is testable at all -- so the RLS file is applied
    more than once against the same tables. `CREATE POLICY` is not idempotent and
    would abort the reopen; `DROP POLICY IF EXISTS` first is what makes it so.
    Proved by reopening and re-reading the policy set, because a reopen that
    failed would take the whole persistence claim with it."""
    tenant = new_id(TenantId)
    _insert_raw(pg, "feature_values", tenant)

    reopened = CoreDatabase.postgres(schema=pg.schema)  # re-applies both SQL files
    try:
        names = [
            row[0]
            for row in reopened.query(
                "SELECT p.polname FROM pg_policy p "
                "JOIN pg_class c ON c.oid = p.polrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = ? AND c.relname = 'feature_values'",
                (pg.schema,),
            )
        ]
        assert names == ["tenant_isolation"], f"reopen left policies {names!r}"
        reopened.use_tenant(tenant)
        assert _raw_tenant_ids(reopened, "feature_values") == [str(tenant)], (
            "the reopen dropped or wiped the row it re-applied the DDL over"
        )
    finally:
        reopened.close()


# =========================================================================
# 2. Cross-tenant reads, positive controls, and the deny-all default
# =========================================================================


@pytest.mark.parametrize("table", _PROGRAM_D_TABLES)
def test_tenant_b_cannot_read_tenant_a_rows(pg, table: str) -> None:
    """THE CORE PROOF. Acting as tenant B, a raw table scan with NO WHERE clause
    returns none of tenant A's rows.

    For `feature_values` that is another operator's model inputs; for the
    promotion tables it is their entire model-governance record -- which model
    serves their riders, what was tried against it, and why each challenger was
    refused."""
    tenant_a, tenant_b = new_id(TenantId), new_id(TenantId)
    _insert_raw(pg, table, tenant_a)
    _insert_raw(pg, table, tenant_b)

    pg.use_tenant(tenant_b)
    visible = _raw_tenant_ids(pg, table)

    assert set(visible) == {str(tenant_b)}, (
        f"a raw unfiltered scan of {table} as tenant B returned {visible!r} -- "
        "another operator's Program D state leaked"
    )
    assert str(tenant_a) not in visible


@pytest.mark.parametrize("table", _PROGRAM_D_TABLES)
def test_a_tenants_own_rows_are_still_visible(pg, table: str) -> None:
    """POSITIVE CONTROL: the policy must not over-block. Acting as A, A's own row
    IS there -- without this, the denial above would be equally satisfied by an
    empty table, by a broken INSERT, or by a policy that denies everyone, and
    would prove nothing at all."""
    tenant_a, tenant_b = new_id(TenantId), new_id(TenantId)
    _insert_raw(pg, table, tenant_a)
    _insert_raw(pg, table, tenant_b)

    pg.use_tenant(tenant_a)
    visible = _raw_tenant_ids(pg, table)

    assert visible == [str(tenant_a)], (
        f"tenant A cannot see its own {table} row -- the policy over-blocks"
    )


@pytest.mark.parametrize("table", _PROGRAM_D_TABLES)
def test_reset_guc_denies_all_and_reads_back_as_the_empty_string(pg, table: str) -> None:
    """Default-DENY, not default-allow -- and THE EMPTY-STRING TRAP, asserted
    rather than assumed.

    It is tempting to write a deny guard as "the GUC IS NULL". That is wrong
    after a RESET: `current_setting(name, true)` returns NULL only when the GUC
    was NEVER set in the session; once set and reset it returns the EMPTY STRING,
    which `IS NOT NULL` happily accepts -- the trap
    `app/canonical/sql/rls_postgres.sql` documents on its `model_versions`
    branch, where a first attempt at the clause fell into it.

    This test pins BOTH facts: that the value really is the empty string here,
    and that deny-all holds anyway (because `tenant_id = ''` is false for any
    real UUIDv7 tenant id). Pinning them together is what stops a future edit
    from "fixing" a policy with an IS NOT NULL check that silently opens the
    door -- the equality form in `core_rls_postgres.sql` survives the reset case
    by the shape of the value space, which is exactly the kind of accident that
    should be under test rather than relied on quietly."""
    _insert_raw(pg, table, new_id(TenantId))
    _insert_raw(pg, table, new_id(TenantId))

    pg.execute("RESET milexium.tenant_id")
    is_null, value = pg.query(
        "SELECT current_setting('milexium.tenant_id', true) IS NULL, "
        "current_setting('milexium.tenant_id', true)"
    )[0]
    visible = _raw_tenant_ids(pg, table)

    assert is_null is False and value == "", (
        "a RESET GUC is expected to read back as the EMPTY STRING, not NULL -- if "
        "this ever changes, any guard written as `IS NOT NULL` becomes load-bearing "
        "in a way it was never tested for"
    )
    assert visible == [], (
        f"a reset milexium.tenant_id exposed {len(visible)} {table} rows -- the "
        "policy defaults to allow-all, which is backwards"
    )


@pytest.mark.parametrize("table", _PROGRAM_D_TABLES)
def test_a_session_that_never_set_the_guc_sees_nothing(pg, table: str) -> None:
    """The OTHER half of the trap: a brand-new connection nobody ever scoped.

    Here `current_setting(..., true)` really does return NULL, and `tenant_id =
    NULL` is never true -- so an unscoped connection (a forgotten scope call, a
    psql session someone opened with the app credential) reads nobody's data. A
    SEPARATE connection into the same schema is required, because the fixture's
    connection has necessarily had the GUC set during seeding and can therefore
    only ever demonstrate the empty-string case above."""
    _insert_raw(pg, table, new_id(TenantId))

    unscoped = psycopg.connect(
        host="localhost", port=5432, dbname="milexium_dev",
        user="milexium_dev", password=_read_dev_password(),
    )
    try:
        unscoped.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(pg.schema)))
        (is_null,) = unscoped.execute(
            "SELECT current_setting('milexium.tenant_id', true) IS NULL"
        ).fetchone()
        (count,) = unscoped.execute(
            sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
        ).fetchone()
        unscoped.commit()
    finally:
        unscoped.close()

    assert is_null is True, "a never-set GUC should read back as NULL"
    assert count == 0, (
        f"an unscoped connection read {count} {table} rows -- a connection nobody "
        "assigned a tenant must be able to read nobody's data"
    )


# =========================================================================
# 3. Writes: the WITH CHECK half
# =========================================================================


@pytest.mark.parametrize("table", _PROGRAM_D_TABLES)
def test_a_write_stamped_with_a_foreign_tenant_is_rejected(pg, table: str) -> None:
    """Acting as one tenant, an INSERT stamped with ANOTHER tenant's id is
    refused by the database, not by Python.

    The read half alone would not be enough. Without WITH CHECK, a compromised or
    simply buggy writer could forge rows into another operator's ledger: a
    fabricated `promotion_decisions` row is a fabricated audit trail, and a forged
    `promotion_champions` row would change which model actually serves someone
    else's riders."""
    victim = new_id(TenantId)
    _insert_raw(pg, table, victim)

    pg.use_tenant(new_id(TenantId))  # an unrelated tenant
    columns, values = _row_for(table, victim)  # ... stamping the VICTIM's id
    placeholders = ", ".join("?" for _ in values)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        pg.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",  # noqa: S608
            values,
        )
    pg._conn.rollback()


@pytest.mark.parametrize("table", _PROGRAM_D_TABLES)
def test_a_delete_cannot_reach_another_tenants_rows(pg, table: str) -> None:
    """The USING clause governs DELETE as well as SELECT, so an unqualified
    `DELETE FROM <table>` -- the shape a careless cleanup script takes -- removes
    only the acting tenant's rows and silently matches zero of anyone else's.

    Worth its own test rather than assumed from the SELECT result: for the two
    append-only LEDGERS a cross-tenant delete would be destruction of another
    operator's audit trail, which is a worse outcome than reading it."""
    tenant_a, tenant_b = new_id(TenantId), new_id(TenantId)
    _insert_raw(pg, table, tenant_a)
    _insert_raw(pg, table, tenant_b)

    pg.use_tenant(tenant_b)
    pg.execute(f"DELETE FROM {table}")  # noqa: S608 -- no WHERE clause, on purpose
    pg.commit()

    pg.use_tenant(tenant_a)
    assert _raw_tenant_ids(pg, table) == [str(tenant_a)], (
        f"an unqualified DELETE as tenant B destroyed tenant A's {table} rows"
    )


# =========================================================================
# 4. FORCE is what binds the owner -- shown by removing it
# =========================================================================


@pytest.mark.parametrize("table", _PROGRAM_D_TABLES)
def test_force_row_level_security_is_load_bearing(pg, table: str) -> None:
    """The boundary is shown COLLAPSING the instant FORCE is lifted, then
    restored.

    Without this, `relforcerowsecurity is True` would be a bit asserted because
    the file sets it, not because we know what it does. The acting role OWNS these
    tables, so ENABLE alone leaves it entirely unconstrained -- and an ENABLE-only
    version of `core_rls_postgres.sql` would make every other test in this module
    pass while isolating nothing."""
    tenant_a = new_id(TenantId)
    _insert_raw(pg, table, tenant_a)
    pg.use_tenant(new_id(TenantId))  # an unrelated, empty tenant

    assert _raw_tenant_ids(pg, table) == [], f"FORCE RLS should hide tenant A's {table} rows"

    try:
        pg.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")  # noqa: S608
        assert _raw_tenant_ids(pg, table) == [str(tenant_a)], (
            f"lifting FORCE did not open {table} -- the owning role was being "
            "constrained by something other than the policy, so this module would "
            "have been silently proving nothing"
        )
    finally:
        pg.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")  # noqa: S608

    assert _raw_tenant_ids(pg, table) == [], (
        "the boundary did not come back when FORCE was restored"
    )
    pg.commit()


# =========================================================================
# 5. THE LEAKAGE GUARANTEE AND THE TENANT BOUNDARY COMPOSE
#    (ADR-0041's load-bearing invariant, re-proved under tenant scoping)
# =========================================================================


def test_a_tenant_crossing_asof_read_returns_nothing_even_at_a_permissive_timestamp(pg) -> None:
    """THE COMPOSITION PROOF, at the policy layer. SYNTHETIC.

    Tenant A holds a value stamped 2026-01-01. Tenant B issues the store's REAL
    as-of query -- `knowledge_time < ?` -- with the `tenant_id` filter DELETED and
    an `as_of` of 2026-06-01, a timestamp that would happily admit A's value. It
    gets nothing.

    Three assertions, and all three are needed:
      * the timestamp really is permissive (A's own read at the same `as_of`
        returns the value), so the empty result is the TENANT rule and not an
        accidentally exclusive time bound;
      * B sees nothing at that permissive timestamp -- the tenant predicate is
        not weakened by the time predicate;
      * A sees nothing at `as_of` EXACTLY the stamp -- the strict `<` is not
        weakened by the tenant predicate.

    That is what "the two rules compose" means concretely: the rows returned are
    the intersection, and neither predicate can rescue a row the other excludes."""
    tenant_a, tenant_b = new_id(TenantId), new_id(TenantId)
    stamp = _utc(2026, 1, 1)
    permissive = _utc(2026, 6, 1)

    pg.use_tenant(tenant_a)
    pg.execute(
        "INSERT INTO feature_values (tenant_id, entity_id, feature_name, value, "
        "knowledge_time, write_sequence) VALUES (?, ?, ?, ?, ?, ?)",
        (str(tenant_a), "zone-1", "lag1", 42.0, _iso_utc(stamp), 1),
    )
    pg.commit()

    def asof(as_of: datetime) -> list:
        """The store's as-of query with the tenant filter REMOVED: the policy is
        the only thing left that could scope it."""
        return pg.query(
            "SELECT value FROM feature_values "
            "WHERE entity_id = ? AND feature_name = ? AND knowledge_time < ? "
            "ORDER BY knowledge_time DESC, write_sequence DESC LIMIT 1",
            ("zone-1", "lag1", _iso_utc(as_of)),
        )

    pg.use_tenant(tenant_a)
    assert asof(permissive) == [(42.0,)], (
        "positive control failed: the timestamp does not admit the value even for "
        "its own tenant, so the cross-tenant empty result below would prove nothing"
    )

    pg.use_tenant(tenant_b)
    assert asof(permissive) == [], (
        "a tenant-crossing as-of read returned another operator's feature value at "
        "a timestamp that admitted it -- the tenant predicate is not being applied "
        "by the policy"
    )

    pg.use_tenant(tenant_a)
    assert asof(stamp) == [], (
        "an as-of read at EXACTLY the knowledge time returned the value -- adding "
        "tenant scoping has weakened ADR-0041's strict `<`"
    )


@pytest.mark.skipif(not _AAR_DAILY.exists(), reason="real AAR daily panel absent")
def test_another_tenants_corrupted_future_cannot_change_this_tenants_past_read(
    core_db,
) -> None:
    """REAL DATA -- the ADR-0041 future-corruption discipline, run ACROSS THE
    TENANT BOUNDARY, on both engines.

    ADR-0034/ADR-0041 corrupt the future of ONE series and assert every past
    as-of read is bit-identical. The multi-tenant version of that question is
    sharper: a second operator writes a series under the SAME entity id and the
    SAME feature name -- which is exactly what happens when two agencies both
    track `scheduled_trips` for a zone they each call `zone-1` -- with garbage
    values at every knowledge time, including times in tenant A's PAST as well as
    its future.

    If the tenant predicate were dropped, or applied after the time predicate
    rather than beside it, A's reads would change. Every one of them is asserted
    bit-identical to the baseline taken before B existed. And the control at the
    end proves B's rows are really there and really different, so the
    bit-identity is not an inert no-op."""
    import numpy as np
    import pandas as pd

    frame = (
        pd.read_csv(_AAR_DAILY, parse_dates=["date"])
        .sort_values("date")
        .reset_index(drop=True)
        .head(_WINDOW)
    )
    rows = [
        (ts.to_pydatetime().replace(tzinfo=timezone.utc), float(v))
        for ts, v in zip(frame["date"], frame["scheduled_trips"])
    ]

    tenant_a, tenant_b = new_id(TenantId), new_id(TenantId)
    store_a = PersistentFeatureStore(core_db, tenant_a)
    store_b = PersistentFeatureStore(core_db, tenant_b)

    for knowledge_time, value in rows:
        store_a.write(
            entity_id=_ENTITY, feature_name=_FEATURE, value=value,
            knowledge_time=knowledge_time,
        )
    dates = [d for d, _ in rows]
    baseline = {d: store_a.get_feature(_ENTITY, _FEATURE, as_of=d) for d in dates}
    assert any(v is not None for v in baseline.values())  # the baseline is not empty

    # Tenant B floods the SAME (entity, feature) with garbage at every stamp --
    # A's past, A's present and A's future alike.
    rng = np.random.default_rng(0)
    for knowledge_time, _ in rows:
        store_b.write(
            entity_id=_ENTITY, feature_name=_FEATURE,
            value=float(rng.integers(10_000_000, 100_000_000)),
            knowledge_time=knowledge_time,
        )

    for label_time, expected in baseline.items():
        assert store_a.get_feature(_ENTITY, _FEATURE, as_of=label_time) == expected, (
            f"another tenant's writes changed tenant A's as-of read at {label_time}"
        )
    assert store_a.get_features(_ENTITY, as_of=dates[-1]) == (
        {_FEATURE: baseline[dates[-1]]} if baseline[dates[-1]] is not None else {}
    )

    # CONTROL: B's rows exist and are genuinely different, so the bit-identity
    # above is the boundary holding, not an ineffective corruption.
    assert store_b.get_feature(_ENTITY, _FEATURE, as_of=dates[-1]) != baseline[dates[-1]]
    assert store_b.get_feature(_ENTITY, _FEATURE, as_of=dates[-1]) is not None


def test_the_strict_past_rule_still_holds_per_tenant(core_db) -> None:
    """SYNTHETIC, both engines. The ADR-0041 boundary case, once per tenant: a
    read at exactly `t` sees the value BEFORE `t`, never the one stamped at `t`.

    Run for two tenants over one table so the strictness cannot be an artefact of
    a table containing exactly one operator's rows."""
    tenant_a, tenant_b = new_id(TenantId), new_id(TenantId)
    store_a = PersistentFeatureStore(core_db, tenant_a)
    store_b = PersistentFeatureStore(core_db, tenant_b)

    for store, early, late in ((store_a, 1.0, 99.0), (store_b, 2.0, 88.0)):
        store.write(entity_id="z-1", feature_name="f", value=early,
                    knowledge_time=_utc(2026, 1, 1))
        store.write(entity_id="z-1", feature_name="f", value=late,
                    knowledge_time=_utc(2026, 1, 2))

    assert store_a.get_feature("z-1", "f", as_of=_utc(2026, 1, 2)) == 1.0
    assert store_b.get_feature("z-1", "f", as_of=_utc(2026, 1, 2)) == 2.0
    assert store_a.get_features("z-1", as_of=_utc(2026, 1, 2)) == {"f": 1.0}
    assert store_b.get_features("z-1", as_of=_utc(2026, 1, 2)) == {"f": 2.0}


# =========================================================================
# 6. The stores themselves are tenant-scoped, on BOTH engines
# =========================================================================


def test_a_feature_store_cannot_be_built_without_a_valid_tenant(core_db) -> None:
    """`tenant_id` is a REQUIRED constructor argument, and it is validated as a
    canonical `TenantId`.

    Both halves matter. Required means there is no unscoped way to reach the
    table at all -- no default, no `None`, nothing to forget. Validated means a
    typo cannot become a silently distinct partition of the table that no
    legitimate session can ever read back or clean up."""
    with pytest.raises(TypeError):
        PersistentFeatureStore(core_db)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        PersistentFeatureStore(core_db, "not-a-uuid")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        # A UUIDv4 is a well-formed UUID and still not a canonical TenantId.
        PersistentFeatureStore(core_db, str(uuid.uuid4()))  # type: ignore[arg-type]


def test_a_promotion_controller_cannot_be_built_without_a_valid_tenant(core_db) -> None:
    registry = ModelRegistry()
    with pytest.raises(TypeError):
        PersistentPromotionController(registry, core_db)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        PersistentPromotionController(registry, core_db, "not-a-uuid")  # type: ignore[arg-type]


def test_two_tenants_feature_values_do_not_mix(core_db) -> None:
    """SYNTHETIC, both engines. Two stores, one database, one (entity, feature):
    each reads only its own value, and `entities()` -- which is a membership
    disclosure if unscoped, since it says how many entities an operator runs --
    lists only its own."""
    tenant_a, tenant_b = new_id(TenantId), new_id(TenantId)
    store_a = PersistentFeatureStore(core_db, tenant_a)
    store_b = PersistentFeatureStore(core_db, tenant_b)

    store_a.write(entity_id="z-1", feature_name="f", value=1.0, knowledge_time=_utc(2026, 1, 1))
    store_b.write(entity_id="z-1", feature_name="f", value=2.0, knowledge_time=_utc(2026, 1, 1))
    store_b.write(entity_id="z-9", feature_name="f", value=3.0, knowledge_time=_utc(2026, 1, 1))

    assert store_a.get_feature("z-1", "f", as_of=_utc(2026, 1, 2)) == 1.0
    assert store_b.get_feature("z-1", "f", as_of=_utc(2026, 1, 2)) == 2.0
    assert store_a.get_feature("z-9", "f", as_of=_utc(2026, 1, 2)) is None
    assert store_a.entities() == frozenset({"z-1"})
    assert store_b.entities() == frozenset({"z-1", "z-9"})
    # The audit view is one operator's own writes, not everyone's.
    assert [v.value for v in store_a.history("z-1", "f")] == [1.0]
    assert [v.value for v in store_b.history("z-1", "f")] == [2.0]


def test_two_tenants_promotion_ledgers_and_champions_do_not_mix(core_db) -> None:
    """SYNTHETIC, both engines. Two operators run the SAME task name -- which is
    the normal case, `forecast.demand` is not a customer-specific string -- and
    each keeps its own champion, challenger pool, canary and ledger.

    This is what the per-(tenant, task) primary keys buy. Before them, one
    operator promoting a model would have overwritten the other's champion
    pointer: not a leak, a takeover of which model serves someone else's riders.
    """
    tenant_a, tenant_b = new_id(TenantId), new_id(TenantId)
    a_model, b_model = _model_version(tenant_a), _model_version(tenant_b)
    controller_a = PersistentPromotionController(_registry_with(a_model), core_db, tenant_a)
    controller_b = PersistentPromotionController(_registry_with(b_model), core_db, tenant_b)

    for controller, model, metric in (
        (controller_a, a_model, 0.20),
        (controller_b, b_model, 0.30),
    ):
        controller.register_challenger(TASK, model.model_version_id)
        controller.evaluate_and_maybe_promote(
            TASK, model.model_version_id, metric_name="wape", challenger_metric=metric,
            higher_is_better=False, decided_at=_utc(2026, 6, 1),
        )

    assert controller_a.champion(TASK) == a_model.model_version_id
    assert controller_b.champion(TASK) == b_model.model_version_id
    assert controller_a.route(TASK, 0.5) == a_model.model_version_id
    assert controller_b.route(TASK, 0.5) == b_model.model_version_id

    # Each ledger is complete for its own operator and contains nothing else --
    # an audit trail that mixed two operators would be evidence for neither.
    assert len(controller_a.decisions()) == 1
    assert len(controller_b.decisions()) == 1
    assert controller_a.decisions()[0].challenger_metric == 0.20
    assert controller_b.decisions()[0].challenger_metric == 0.30
    assert controller_a.rollout(TASK).champion_id == a_model.model_version_id
    assert controller_b.rollout(TASK).champion_id == b_model.model_version_id


def test_ledger_sequences_are_per_tenant_and_start_at_one(core_db) -> None:
    """SYNTHETIC, both engines. `decision_sequence` restarts at 1 for each tenant.

    This is forced by the isolation boundary, not a stylistic choice: under RLS
    the `MAX(decision_sequence)` that assigns the next value can only see the
    ACTING tenant's rows, so a global counter would be re-derived per tenant and
    the second operator would collide on the primary key. Asserting the numbering
    here is what stops a future edit from "restoring" a global sequence and
    breaking multi-tenant writes on PostgreSQL only.

    It is also the better ledger: a global counter would leak the other
    operator's activity through the gaps in one's own."""
    tenant_a, tenant_b = new_id(TenantId), new_id(TenantId)
    models_a = [_model_version(tenant_a), _model_version(tenant_a)]
    models_b = [_model_version(tenant_b)]
    controller_a = PersistentPromotionController(_registry_with(*models_a), core_db, tenant_a)
    controller_b = PersistentPromotionController(_registry_with(*models_b), core_db, tenant_b)

    # Interleave the two operators so a global counter would be visibly wrong.
    controller_a.register_challenger(TASK, models_a[0].model_version_id)
    controller_a.evaluate_and_maybe_promote(
        TASK, models_a[0].model_version_id, metric_name="wape", challenger_metric=0.30,
        higher_is_better=False, decided_at=_utc(2026, 6, 1),
    )
    controller_b.register_challenger(TASK, models_b[0].model_version_id)
    controller_b.evaluate_and_maybe_promote(
        TASK, models_b[0].model_version_id, metric_name="wape", challenger_metric=0.40,
        higher_is_better=False, decided_at=_utc(2026, 6, 1),
    )
    controller_a.register_challenger(TASK, models_a[1].model_version_id)
    controller_a.evaluate_and_maybe_promote(
        TASK, models_a[1].model_version_id, metric_name="wape", challenger_metric=0.10,
        incumbent_metric=0.30, higher_is_better=False, decided_at=_utc(2026, 6, 2),
    )

    core_db.use_tenant(tenant_a)
    assert [
        row[0] for row in core_db.query(
            "SELECT decision_sequence FROM promotion_decisions WHERE tenant_id = ? "
            "ORDER BY decision_sequence", (str(tenant_a),)
        )
    ] == [1, 2]
    core_db.use_tenant(tenant_b)
    assert [
        row[0] for row in core_db.query(
            "SELECT decision_sequence FROM promotion_decisions WHERE tenant_id = ? "
            "ORDER BY decision_sequence", (str(tenant_b),)
        )
    ] == [1]

    # And the ledgers still read back complete and in order for each operator.
    assert [d.challenger_metric for d in controller_a.decisions()] == [0.30, 0.10]
    assert [d.challenger_metric for d in controller_b.decisions()] == [0.40]


def test_a_rollback_walks_only_its_own_tenants_champion_stack(core_db) -> None:
    """SYNTHETIC, both engines. `promotion_champion_history` is a per-(tenant,
    task) STACK, and `rollback()` pops the acting tenant's top entry only.

    The failure this rules out is specific and bad: with a shared stack, one
    operator's rollback would pop an entry pushed by another and install a model
    that operator has never evaluated as the other's serving champion."""
    tenant_a, tenant_b = new_id(TenantId), new_id(TenantId)
    a1, a2 = _model_version(tenant_a), _model_version(tenant_a)
    b1 = _model_version(tenant_b)
    controller_a = PersistentPromotionController(_registry_with(a1, a2), core_db, tenant_a)
    controller_b = PersistentPromotionController(_registry_with(b1), core_db, tenant_b)

    for index, model in enumerate((a1, a2)):
        controller_a.register_challenger(TASK, model.model_version_id)
        controller_a.evaluate_and_maybe_promote(
            TASK, model.model_version_id, metric_name="wape",
            challenger_metric=0.30 - 0.05 * index,
            incumbent_metric=None if index == 0 else 0.30,
            higher_is_better=False, decided_at=_utc(2026, 6, 1 + index),
        )
    controller_b.register_challenger(TASK, b1.model_version_id)
    controller_b.evaluate_and_maybe_promote(
        TASK, b1.model_version_id, metric_name="wape", challenger_metric=0.40,
        higher_is_better=False, decided_at=_utc(2026, 6, 1),
    )

    controller_a.rollback(TASK, decided_at=_utc(2026, 6, 10), reason="error spike")

    assert controller_a.champion(TASK) == a1.model_version_id
    assert controller_b.champion(TASK) == b1.model_version_id, (
        "tenant A's rollback moved tenant B's serving champion"
    )
    assert len(controller_a.rollbacks()) == 1
    assert controller_b.rollbacks() == (), (
        "tenant B's rollback ledger contains a record it never made"
    )
