"""Conformance + adversarial tests for the reserved platform tenant
(MX-A-RUNREF-PLATFORM-TENANT-004, task 2 -- implementing ADR-0040).

WHY THIS FILE IS THE DELIVERABLE, in ADR-0040's own words: landing half of this
-- "the constant without the policy, or the policy without the test" -- would be
**worse than the current honest placeholder, because it would look finished**.
A `PLATFORM_TENANT_ID` that no policy knows about is a naming convention wearing
a security guarantee's clothes. So the claim under test is the adversarial one:

    a tenant session CANNOT write a row stamped with the platform id,
    and CAN read one.

Both halves matter and they pull in opposite directions. Platform-trained models
(the five real models here are trained on PUBLIC data -- NYC TLC, Chicago TNP,
MTA, NTD -- and belong to no customer) must be **readable by every tenant and
writable by none of them**. A strict `tenant_id = GUC` policy would make the
platform's own models invisible to the customers who need to run them; a policy
loose enough to fix that, applied symmetrically, would let any customer forge a
platform-owned model. Hence the one asymmetric policy in `rls_postgres.sql`:

    USING      (tenant_id = current_setting('milexium.tenant_id', true)
                OR tenant_id = '<PLATFORM_TENANT_ID>')   -- read: yes
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true))
                                                          -- write: no

FOUR SECTIONS, three of which need no database:

1. THE CONSTANT, and that the SQL literal has not drifted from the Python one --
   the single most likely way this decays silently, and it is checkable without
   PostgreSQL, so it runs everywhere.
2. THE SEEDED ROW, on BOTH stores. The reserved id has to be a real `tenants`
   row or the foreign key rejects the first platform-owned insert; ADR-0040 calls
   this out explicitly and both stores seed it idempotently at setup.
3. RESOLUTION -- `themis/core/model_registry.py` resolving platform-owned
   models without a special case at every call site.
4. THE ADVERSARIAL PROOF, against the native PostgreSQL 17 on 5432. These issue
   RAW SQL after pointing the session GUC at a tenant, exactly as
   `aletheia/conformance/adversarial/test_postgres_rls_isolation.py` and
   `test_stop_time_observation_store.py` do, so what is under test is the
   POLICY, not any Python filter. `model_versions` has no store method, and that
   is fine -- it is the database that has to hold this line.

   They skip cleanly (never fail) when `milexium_dev` is unreachable so CI stays
   green -- but a skip proves nothing, so the packet's evidence requirement is
   that section 4 RUNS, not merely that it passes.

HONEST LIMIT OF THE BOUNDARY, stated rather than implied. The GUC *is* the
identity: a session that sets `milexium.tenant_id` to the platform id is acting
AS the platform and may write platform rows -- that is how the platform seeds its
own models, and it is the same trust model every other policy in
`rls_postgres.sql` has (the app role holds one credential; ADR-0018). What is
excluded, and what is proven below, is a session acting as a CUSTOMER.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from themis.canonical import (
    PLATFORM_TENANT_ID,
    PLATFORM_TENANT_NAME,
    ModelVersion,
    ModelVersionId,
    Tenant,
    TenantId,
    new_id,
    platform_tenant,
)
from themis.canonical.postgres_storage import PostgresCanonicalStore
from themis.canonical.postgres_storage import is_reachable as pg_is_reachable
from themis.canonical.storage import SqliteCanonicalStore
from themis.core.model_registry import ModelRegistry, is_platform_owned

_SQL_DIR = Path(__file__).resolve().parents[3] / "themis" / "canonical" / "sql"
_RLS_SQL = (_SQL_DIR / "rls_postgres.sql").read_text(encoding="utf-8")


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _tenant(name: str = "platform-tenant-conformance") -> Tenant:
    return Tenant(tenant_id=new_id(TenantId), name=name, created_at=_utc(2026, 7, 24))


def _model_version(tenant_id: TenantId, **overrides) -> ModelVersion:
    fields = dict(
        model_version_id=new_id(ModelVersionId),
        tenant_id=tenant_id,
        task="forecast.demand",
        training_data_manifest_hash="deadbeef" * 8,
        feature_schema_version="zone_hour_demand_v1",
        evaluation_window_start=_utc(2026, 3, 2),
        evaluation_window_end=_utc(2026, 5, 31),
        artifact_hash="cafebabe" * 8,
    )
    fields.update(overrides)
    return ModelVersion(**fields)


def _model_versions_policy() -> str:
    """The `model_versions` policy statement, verbatim, out of the real file."""
    marker = "CREATE POLICY tenant_isolation ON model_versions"
    start = _RLS_SQL.index(marker)
    return _RLS_SQL[start : _RLS_SQL.index(";", start)]


# =========================================================================
# 1. THE CONSTANT, and Python-vs-SQL drift
# =========================================================================


def test_the_platform_tenant_id_is_a_valid_tenant_id() -> None:
    """It must satisfy the SAME validation as every other TenantId (UUIDv7,
    RFC-4122 variant). A sentinel needing an exemption would push a special case
    into `ids.py` -- exactly the "special case at every call site" cost ADR-0040
    rejected the nullable-`tenant_id` option to avoid."""
    assert isinstance(PLATFORM_TENANT_ID, TenantId)
    assert TenantId(str(PLATFORM_TENANT_ID)) == PLATFORM_TENANT_ID


def test_the_platform_tenant_id_literal_is_pinned() -> None:
    """A WELL-KNOWN constant: its value is data, already stamped onto rows and
    written into a SQL policy. Changing it silently orphans every row stamped
    with it and reopens the read hole the policy closes, so the literal is
    pinned here and a change has to be deliberate."""
    assert str(PLATFORM_TENANT_ID) == "00000000-0000-7000-8000-000000000000"


def test_the_platform_tenant_id_cannot_collide_with_a_minted_tenant() -> None:
    """UUIDv7's leading 48 bits are a Unix-millisecond timestamp, which is never
    zero for a real mint, so the all-zero prefix cannot be handed to a customer
    by `new_id(TenantId)`."""
    minted = {str(new_id(TenantId)) for _ in range(50)}
    assert str(PLATFORM_TENANT_ID) not in minted
    assert all(not candidate.startswith("00000000-0000") for candidate in minted)


def test_the_rls_policy_literal_matches_the_python_constant() -> None:
    """The drift check. The policy lives in a `.sql` file, so the id is written
    twice -- once in Python, once as a SQL literal -- and nothing but this test
    forces them to agree. If they diverge, the constant keeps working in Python
    while the database silently stops recognising platform rows: every tenant
    loses read access to the platform's models and nobody gets an error."""
    assert str(PLATFORM_TENANT_ID) in _model_versions_policy()


def test_the_model_versions_policy_is_asymmetric() -> None:
    """The exact shape ADR-0040 specifies, asserted clause by clause. This is
    the difference between "a tenant may use a platform model" and "a tenant may
    forge one", and it is one word long, so it is asserted rather than reviewed:
    the platform id appears in USING and MUST NOT appear in WITH CHECK."""
    policy = _model_versions_policy()
    assert "WITH CHECK" in policy, "the policy must have an explicit WITH CHECK clause"

    using, with_check = policy.split("WITH CHECK", 1)

    assert str(PLATFORM_TENANT_ID) in using, (
        "USING must admit the platform id, or the platform's own models become "
        "invisible to the customers who need to run them"
    )
    assert str(PLATFORM_TENANT_ID) not in with_check, (
        "WITH CHECK must NOT admit the platform id -- with it, any tenant session "
        "could write a platform-stamped row, and a customer could forge a platform model"
    )
    assert "current_setting('milexium.tenant_id', true)" in using
    assert "current_setting('milexium.tenant_id', true)" in with_check


def test_the_platform_exception_is_confined_to_model_versions() -> None:
    """The asymmetry is a deliberate, single exception. Every other policy in the
    file stays symmetric, so this test fails the moment the platform id is
    pasted into a second table's policy -- which is how a narrow exception
    becomes a general hole."""
    assert _RLS_SQL.count(str(PLATFORM_TENANT_ID)) == 1, (
        "the platform id should appear exactly once in rls_postgres.sql (the "
        "model_versions USING clause); another occurrence widens the exception"
    )


def test_every_table_this_packet_touches_is_enabled_and_forced_in_the_sql() -> None:
    """ADR-0018's owner-bypass rule, asserted at the source level so it holds
    even where PostgreSQL is absent: `milexium_dev` OWNS these tables and an
    owner bypasses RLS by default, so ENABLE without FORCE is a false green."""
    for table in ("model_versions", "tenants", "outcomes"):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" in _RLS_SQL
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;" in _RLS_SQL


# =========================================================================
# 2. THE SEEDED ROW -- both stores
# =========================================================================


@pytest.fixture(params=["sqlite", "postgres"])
def store(request):
    """Both engines through one fixture: the reserved tenant has to exist on
    whichever engine a deployment runs, so seeding is part of BOTH stores'
    setup, not a Postgres detail."""
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
            "skipping the PostgreSQL half of the platform-tenant seeding contract"
        )
    st = PostgresCanonicalStore.connect()
    try:
        yield st
    finally:
        st.drop_schema()
        st.close()


def _exec(store, statement: str, params: tuple):
    """Run the same raw SQL against whichever engine `store` wraps -- `?` is
    rewritten to `%s` for psycopg, the SQL itself is identical because
    schema_v0_1.sql is portable."""
    placeholder = "?" if isinstance(store, SqliteCanonicalStore) else "%s"
    return store._conn.execute(statement.replace("?", placeholder), params)


def _act_as(store, tenant_id) -> None:
    """Point the RLS session key at `tenant_id` (a no-op on SQLite, which has no
    RLS -- the boundary there is the WHERE clause)."""
    if isinstance(store, PostgresCanonicalStore):
        store._use_tenant(tenant_id)


def test_store_setup_seeds_the_reserved_platform_tenant(store) -> None:
    """ADR-0040: "the reserved id must be a real row in `tenants` to satisfy the
    foreign key, and seeding it becomes part of store setup." Asserted as a row,
    with its name, on a store nobody has called `create_tenant` on."""
    _act_as(store, PLATFORM_TENANT_ID)
    cur = _exec(
        store,
        "SELECT tenant_id, name FROM tenants WHERE tenant_id = ?",
        (str(PLATFORM_TENANT_ID),),
    )
    rows = cur.fetchall()
    store._conn.commit()

    assert len(rows) == 1, "the reserved platform tenant was not seeded by store setup"
    assert rows[0][1] == PLATFORM_TENANT_NAME


def test_seeding_the_platform_tenant_again_is_a_no_op(store) -> None:
    """Idempotent, as the packet requires -- a store opened against a database
    that already has the row must not fail and must not duplicate it. Calling
    the seeder directly is the honest way to test that: it is the code path a
    re-open would take."""
    store._seed_platform_tenant()
    store._seed_platform_tenant()

    _act_as(store, PLATFORM_TENANT_ID)
    cur = _exec(
        store, "SELECT count(*) FROM tenants WHERE tenant_id = ?", (str(PLATFORM_TENANT_ID),)
    )
    (count,) = cur.fetchone()
    store._conn.commit()

    assert count == 1


def test_a_platform_stamped_model_satisfies_the_tenants_foreign_key(store) -> None:
    """The concrete reason the row has to exist. `model_versions.tenant_id`
    REFERENCES `tenants(tenant_id)`, so a platform-owned model is only
    insertable because setup registered the reserved tenant -- a convention
    alone would have failed here, on both engines."""
    _act_as(store, PLATFORM_TENANT_ID)
    model = _model_version(PLATFORM_TENANT_ID)
    _exec(
        store,
        "INSERT INTO model_versions (model_version_id, tenant_id, task, "
        "training_data_manifest_hash, feature_schema_version, evaluation_window_start, "
        "evaluation_window_end, artifact_hash) VALUES (?,?,?,?,?,?,?,?)",
        (
            str(model.model_version_id),
            str(model.tenant_id),
            model.task,
            model.training_data_manifest_hash,
            model.feature_schema_version,
            model.evaluation_window_start.isoformat(),
            model.evaluation_window_end.isoformat(),
            model.artifact_hash,
        ),
    )
    store._conn.commit()

    cur = _exec(
        store,
        "SELECT count(*) FROM model_versions WHERE tenant_id = ?",
        (str(PLATFORM_TENANT_ID),),
    )
    (count,) = cur.fetchone()
    store._conn.commit()
    assert count == 1


def test_the_seeded_row_matches_the_canonical_platform_tenant_entity() -> None:
    """`platform_tenant()` is the single source of the seeded row, and its
    `created_at` is FIXED (not `now()`), so re-seeding cannot change the value,
    only skip the insert."""
    tenant = platform_tenant()
    assert tenant.tenant_id == PLATFORM_TENANT_ID
    assert tenant.name == PLATFORM_TENANT_NAME
    assert platform_tenant() == tenant


# =========================================================================
# 3. RESOLUTION -- no special case at every call site
# =========================================================================


def test_a_platform_owned_model_is_recognised_as_such() -> None:
    assert is_platform_owned(_model_version(PLATFORM_TENANT_ID)) is True
    assert is_platform_owned(_model_version(new_id(TenantId))) is False


def test_a_tenant_resolves_the_platform_champion_as_its_own() -> None:
    """The point of ADR-0040's reserved tenant: a customer that has trained
    nothing still resolves the platform's model, with no caller-side special
    case for "the platform owns this one"."""
    registry = ModelRegistry()
    platform_model = _model_version(PLATFORM_TENANT_ID)
    registry.register(platform_model)
    registry.promote(platform_model.model_version_id)

    customer = new_id(TenantId)
    assert registry.champion("forecast.demand", tenant_id=customer) == platform_model
    assert registry.list_for_task("forecast.demand", tenant_id=customer) == (platform_model,)


def test_a_tenant_does_not_resolve_another_customers_model() -> None:
    """The read boundary the platform exception must not widen. A model owned by
    customer A is not resolvable by customer B, and `champion` answers None --
    the same answer as "nothing promoted yet", so B cannot even tell that A has
    a champion."""
    registry = ModelRegistry()
    tenant_a, tenant_b = new_id(TenantId), new_id(TenantId)
    a_model = _model_version(tenant_a)
    registry.register(a_model)
    registry.promote(a_model.model_version_id)

    assert registry.champion("forecast.demand", tenant_id=tenant_b) is None
    assert registry.list_for_task("forecast.demand", tenant_id=tenant_b) == ()
    assert registry.champion("forecast.demand", tenant_id=tenant_a) == a_model


def test_a_tenant_sees_its_own_and_the_platforms_models_together() -> None:
    """Both at once, which is the case a per-call-site special case gets wrong:
    the tenant's own model AND the platform's, and nobody else's."""
    registry = ModelRegistry()
    tenant_a, tenant_b = new_id(TenantId), new_id(TenantId)
    own = _model_version(tenant_a)
    platform_model = _model_version(PLATFORM_TENANT_ID)
    other = _model_version(tenant_b)
    for model in (own, platform_model, other):
        registry.register(model)

    assert set(registry.list_for_task("forecast.demand", tenant_id=tenant_a)) == {
        own,
        platform_model,
    }


def test_unscoped_listing_is_unchanged() -> None:
    """Non-regression: every existing caller passes no tenant and must still get
    the platform's own full catalog view."""
    registry = ModelRegistry()
    models = [_model_version(new_id(TenantId)), _model_version(PLATFORM_TENANT_ID)]
    for model in models:
        registry.register(model)

    assert set(registry.list_for_task("forecast.demand")) == set(models)


# =========================================================================
# 4. THE ADVERSARIAL PROOF -- native PostgreSQL 17 (5432)
# =========================================================================

psycopg = pytest.importorskip("psycopg")


@pytest.fixture
def rls_store() -> PostgresCanonicalStore:
    """`PostgresCanonicalStore` is the store that applies sql/rls_postgres.sql,
    so it is what can prove the asymmetric policy."""
    if not pg_is_reachable():
        pytest.skip(
            "PostgreSQL (milexium_dev) is not reachable on this machine; "
            "skipping the platform-tenant RLS conformance tests"
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
    statements below are governed only by the policy."""
    store._conn.execute("SELECT set_config('milexium.tenant_id', %s, false)", (str(tenant_id),))


def _raw_insert_model(store: PostgresCanonicalStore, tenant_id) -> ModelVersionId:
    """INSERT one model_versions row stamped `tenant_id`, under whatever GUC the
    session currently names. Raises if the policy refuses -- which is the point."""
    model = _model_version(tenant_id if isinstance(tenant_id, TenantId) else TenantId(str(tenant_id)))
    store._conn.execute(
        "INSERT INTO model_versions (model_version_id, tenant_id, task, "
        "training_data_manifest_hash, feature_schema_version, evaluation_window_start, "
        "evaluation_window_end, artifact_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            str(model.model_version_id),
            str(model.tenant_id),
            model.task,
            model.training_data_manifest_hash,
            model.feature_schema_version,
            model.evaluation_window_start.isoformat(),
            model.evaluation_window_end.isoformat(),
            model.artifact_hash,
        ),
    )
    return model.model_version_id


def _seed_platform_model(store: PostgresCanonicalStore) -> ModelVersionId:
    """Write a platform-owned model AS the platform -- the only session that may,
    which is itself part of what these tests assert."""
    _set_session_tenant(store, PLATFORM_TENANT_ID)
    model_version_id = _raw_insert_model(store, PLATFORM_TENANT_ID)
    store._conn.commit()
    return model_version_id


def _seed_customer_model(store: PostgresCanonicalStore, tenant: Tenant) -> ModelVersionId:
    store.create_tenant(tenant)  # also points the GUC at this tenant
    model_version_id = _raw_insert_model(store, tenant.tenant_id)
    store._conn.commit()
    return model_version_id


def test_model_versions_has_rls_enabled_and_forced(rls_store) -> None:
    """The precondition everything below rests on, asserted rather than assumed.
    ENABLE alone would be a false green: `milexium_dev` OWNS this table and a
    table owner bypasses RLS by default (ADR-0018), so `relforcerowsecurity` is
    the bit that actually binds our own connection."""
    cur = rls_store._conn.execute(
        "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = 'model_versions'",
        (rls_store._schema,),
    )
    enabled, forced = cur.fetchone()
    rls_store._conn.commit()

    assert enabled is True, "model_versions does not have ROW LEVEL SECURITY enabled"
    assert forced is True, (
        "model_versions has ENABLE but not FORCE -- the owning role bypasses the "
        "policy and every test below would pass for the wrong reason"
    )


def test_a_tenant_session_cannot_write_a_platform_stamped_model(rls_store) -> None:
    """**THE DELIVERABLE.** Acting as a customer, an INSERT stamped with the
    platform id is refused by the database. This is the half ADR-0040 warns
    cannot be skipped: without it the constant is a naming convention that merely
    looks like a guarantee, and a customer could publish a model that every other
    tenant would then read as the platform's own.

    Note what is NOT relied on: no store method, no Python filter, no application
    check. Raw SQL on the connection, refused by the policy's WITH CHECK.
    """
    tenant = _tenant("forger")
    rls_store.create_tenant(tenant)
    _set_session_tenant(rls_store, tenant.tenant_id)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _raw_insert_model(rls_store, PLATFORM_TENANT_ID)
    rls_store._conn.rollback()

    # And nothing landed.
    _set_session_tenant(rls_store, PLATFORM_TENANT_ID)
    cur = rls_store._conn.execute(
        "SELECT count(*) FROM model_versions WHERE tenant_id = %s", (str(PLATFORM_TENANT_ID),)
    )
    assert cur.fetchone()[0] == 0
    rls_store._conn.commit()


def test_a_tenant_session_can_read_a_platform_model(rls_store) -> None:
    """The other half, and the reason the policy could not simply stay strict: a
    raw scan with NO WHERE clause, acting as a customer, DOES return the
    platform's model. Without this, ADR-0040's reserved tenant would hide the
    platform's own models from every customer who needs to run them."""
    platform_model_id = _seed_platform_model(rls_store)

    tenant = _tenant("reader")
    rls_store.create_tenant(tenant)
    _set_session_tenant(rls_store, tenant.tenant_id)
    cur = rls_store._conn.execute("SELECT model_version_id, tenant_id FROM model_versions")
    rows = cur.fetchall()
    rls_store._conn.commit()

    assert [(r[0], r[1]) for r in rows] == [
        (str(platform_model_id), str(PLATFORM_TENANT_ID))
    ], "a tenant session could not read the platform's model"


def test_a_tenant_session_still_cannot_read_another_customers_model(rls_store) -> None:
    """The exception must be an exception. Adding `OR tenant_id = PLATFORM` to
    USING widens visibility by exactly one well-known id and nothing else --
    customer A's model stays invisible to customer B."""
    tenant_a = _tenant("customer-a")
    _seed_customer_model(rls_store, tenant_a)
    platform_model_id = _seed_platform_model(rls_store)

    tenant_b = _tenant("customer-b")
    rls_store.create_tenant(tenant_b)
    _set_session_tenant(rls_store, tenant_b.tenant_id)
    cur = rls_store._conn.execute("SELECT model_version_id, tenant_id FROM model_versions")
    rows = cur.fetchall()
    rls_store._conn.commit()

    visible = {r[1] for r in rows}
    assert visible == {str(PLATFORM_TENANT_ID)}, (
        f"a raw scan as customer B returned {visible}; the platform exception must not "
        "expose another customer's models"
    )
    assert str(platform_model_id) in {r[0] for r in rows}


def test_a_tenant_session_cannot_write_another_customers_model(rls_store) -> None:
    """Non-regression on the ordinary WITH CHECK, which the asymmetry must not
    have loosened: stamping another CUSTOMER's id is still refused."""
    tenant_a = _tenant("customer-a")
    rls_store.create_tenant(tenant_a)
    tenant_b = _tenant("customer-b")
    rls_store.create_tenant(tenant_b)

    _set_session_tenant(rls_store, tenant_b.tenant_id)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _raw_insert_model(rls_store, tenant_a.tenant_id)
    rls_store._conn.rollback()


def test_a_tenant_session_can_write_its_own_model(rls_store) -> None:
    """Positive control. Without it, the two rejection tests above would also
    pass if the policy refused EVERY insert -- an over-blocking policy that
    breaks the product while looking like airtight security."""
    tenant = _tenant("own-model")
    model_version_id = _seed_customer_model(rls_store, tenant)

    _set_session_tenant(rls_store, tenant.tenant_id)
    cur = rls_store._conn.execute("SELECT model_version_id FROM model_versions")
    rows = cur.fetchall()
    rls_store._conn.commit()

    assert [r[0] for r in rows] == [str(model_version_id)]


def test_an_unset_session_tenant_denies_all_customer_owned_models(rls_store) -> None:
    """Deny-by-default is preserved for CUSTOMER data: with no tenant named,
    `current_setting(..., true)` yields NULL, `tenant_id = NULL` is never true,
    and a forgotten GUC hides every customer's models rather than exposing them.

    The platform rows are the deliberate, documented exception -- see the next
    test. That is asserted separately rather than folded in here, so the
    customer-data guarantee is stated on its own and cannot be weakened by
    accident."""
    tenant_a = _tenant("customer-a")
    _seed_customer_model(rls_store, tenant_a)
    tenant_b = _tenant("customer-b")
    _seed_customer_model(rls_store, tenant_b)

    rls_store._conn.execute("RESET milexium.tenant_id")
    cur = rls_store._conn.execute("SELECT count(*) FROM model_versions")
    (count,) = cur.fetchone()
    rls_store._conn.commit()

    assert count == 0, (
        f"an unset milexium.tenant_id exposed {count} customer-owned model_versions rows"
    )


def test_an_unset_session_tenant_denies_platform_models_too(rls_store) -> None:
    """Deny-all holds for EVERY row of model_versions, platform rows included
    (ADR-0043, tightening ADR-0040).

    ADR-0040's literal clause was `USING (... OR tenant_id = PLATFORM)`, which is
    true whatever the GUC says -- so an unset session could read platform rows.
    That leaked no customer data (platform rows are readable by every tenant by
    construction), but it contradicted the deny-all default `rls_postgres.sql`
    advertises in its own header, and "the rows we judged harmless" is a
    judgement that would have to keep holding for every column and join added
    later. The policy now requires the GUC to be non-NULL for the platform-read
    branch, which costs nothing -- any acting tenant still reads platform models
    (proved by test_any_tenant_can_read_platform_models) -- and restores the
    invariant: an unset GUC returns zero rows from this table, as from every
    other."""
    _seed_platform_model(rls_store)
    tenant_a = _tenant("customer-a")
    _seed_customer_model(rls_store, tenant_a)

    rls_store._conn.execute("RESET milexium.tenant_id")
    cur = rls_store._conn.execute("SELECT tenant_id FROM model_versions")
    rows = cur.fetchall()
    rls_store._conn.commit()

    assert rows == []


def test_the_reserved_tenants_own_registration_row_is_not_leaked(rls_store) -> None:
    """The exception is confined to `model_versions`. The `tenants` table keeps
    its strict symmetric policy, so a customer session cannot read the reserved
    tenant's registration row -- seeding it did not quietly make `tenants`
    world-readable."""
    tenant = _tenant("nosy")
    rls_store.create_tenant(tenant)
    _set_session_tenant(rls_store, tenant.tenant_id)

    cur = rls_store._conn.execute("SELECT tenant_id FROM tenants")
    rows = cur.fetchall()
    rls_store._conn.commit()

    assert {r[0] for r in rows} == {str(tenant.tenant_id)}


def test_force_row_level_security_is_load_bearing_on_model_versions(rls_store) -> None:
    """Proves FORCE -- not ENABLE alone -- is what binds the OWNING role on this
    table, mirroring the same proof for `decision_events` and the observation
    tables. The boundary is shown collapsing the instant FORCE is lifted, then
    restored, so the asymmetric policy above is not passing for the wrong
    reason."""
    tenant_a = _tenant("customer-a")
    _seed_customer_model(rls_store, tenant_a)
    _set_session_tenant(rls_store, new_id(TenantId))  # an empty, unrelated tenant

    cur = rls_store._conn.execute("SELECT count(*) FROM model_versions")
    assert cur.fetchone()[0] == 0, "FORCE RLS should hide customer A's model"

    rls_store._conn.execute("ALTER TABLE model_versions NO FORCE ROW LEVEL SECURITY")
    cur = rls_store._conn.execute("SELECT count(*) FROM model_versions")
    assert cur.fetchone()[0] == 1, (
        "without FORCE the owning role bypasses RLS on model_versions -- exactly why "
        "FORCE is required, and why an ENABLE-only setup would be a false green"
    )

    rls_store._conn.execute("ALTER TABLE model_versions FORCE ROW LEVEL SECURITY")
    cur = rls_store._conn.execute("SELECT count(*) FROM model_versions")
    assert cur.fetchone()[0] == 0
    rls_store._conn.commit()
