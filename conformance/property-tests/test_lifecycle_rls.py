"""Adversarial conformance: TENANT ISOLATION on the durable lifecycle record.

WHAT IS SENSITIVE HERE, and it is not the same thing as everywhere else. Most
tenant-scoped tables in this schema hold operational facts. This one holds a
per-rider record of REFUSALS: that request R was denied for NO_ACCESSIBLE_CAPACITY,
or negotiated ninety minutes away from what the rider asked for, decided by
dispatcher token 7 at 09:14 on a Tuesday. It is precisely the material an agency
would be examined on in a civil-rights complaint, and `request_id` ties every row
to a tokenised rider. One operator seeing another's service-denial history is a
worse outcome than most leaks in this repository, which is why the table's policy
landed in the same packet as the table (ADR-0037's retroactive fix, not repeated).

WHAT IS UNDER TEST IS THE DATABASE POLICY, NEVER A PYTHON CODE PATH. Every
cross-tenant read below is RAW SQL with the `tenant_id` filter DELIBERATELY
DELETED. A WHERE clause is application code that a refactor can drop; a policy is
not. `test_lifecycle_record.py` covers the store-level scoping on both engines;
this file covers what holds when that scoping is removed.

FIVE WAYS THIS SUITE COULD PASS FOR THE WRONG REASON, each closed by a test
rather than argued away:

1. *The acting role bypasses RLS anyway.* `test_the_acting_role_is_bound_by_row_security`
   asserts `milexium_dev` holds neither `rolsuper` nor `rolbypassrls` (ADR-0006,
   ADR-0046/0052) BEFORE any isolation result here is read as evidence. PostgreSQL
   checks both attributes before ownership and before FORCE, so a privileged
   credential would make every policy in this file pure decoration.
2. *The OWNER bypasses the policy.* `milexium_dev` owns the table, and a table
   owner bypasses RLS unless FORCE is set.
   `test_force_row_level_security_is_load_bearing` lifts FORCE, watches the
   boundary collapse, and restores it.
3. *The block is passing on an empty table.* Every denial is paired with a
   positive control proving the row it is not seeing exists and IS visible to its
   own tenant.
4. *The deny-all default is only tested for a NULL GUC.* `current_setting(name,
   true)` returns NULL only when the GUC was NEVER set; after `RESET` it returns
   the EMPTY STRING, which an `IS NOT NULL` guard happily accepts (ADR-0043).
   Both cases get their own test, and the reset case asserts the empty string
   EXPLICITLY before concluding anything.
5. *The policy is written the way ADR-0043 warns against.*
   `test_the_lifecycle_policy_is_not_written_as_an_is_not_null_guard` reads the
   policy's own text out of `pg_policy` and refuses the shape that has already
   caught this repository once.

SYNTHETIC FIXTURES ONLY. Status: Demonstrated. Skips cleanly (never fails) when
the native PostgreSQL instance is absent -- but a skip proves nothing, so the
packet's evidence requirement is that these RUN.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

psycopg = pytest.importorskip("psycopg")  # skip the whole module if absent

from psycopg import sql  # noqa: E402

from packages.canonical.entities import Tenant  # noqa: E402
from packages.canonical.ids import (  # noqa: E402
    RequestId,
    RequestTransitionId,
    TenantId,
    new_id,
)
from packages.canonical.lifecycle import TimeWindow, iso_fixed_utc  # noqa: E402
from packages.canonical.postgres_storage import (  # noqa: E402
    PostgresCanonicalStore,
    _read_dev_password,
    is_reachable as pg_is_reachable,
)
from packages.canonical.state_machine import ServiceRequestState  # noqa: E402
from packages.canonical.vocab import ReasonCode  # noqa: E402

_TABLE = "request_state_transitions"

_INSERT = (
    f"INSERT INTO {_TABLE} (transition_id, tenant_id, request_id, sequence, from_state, "  # noqa: S608
    "to_state, decided_at, recorded_at, actor_type, actor_id, reason_codes) "
    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
)


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture
def pg():
    """A `PostgresCanonicalStore` in its own disposable schema, with
    `rls_postgres.sql` applied. Skips (never fails) when the instance is absent."""
    if not pg_is_reachable():
        pytest.skip(
            "PostgreSQL (milexium_dev, port 5432) is not reachable on this machine; "
            "skipping the lifecycle-record tenant-isolation policy tests"
        )
    store = PostgresCanonicalStore.connect(schema=f"mx_life_rls_{uuid.uuid4().hex}")
    try:
        yield store
    finally:
        try:
            store._conn.rollback()  # a test may have aborted the transaction
        except Exception:  # pragma: no cover - teardown must never mask a failure
            pass
        store.drop_schema()
        store.close()


def _query(store, statement: str, params: tuple = ()) -> list[tuple]:
    return store._conn.execute(statement, params).fetchall()


def _new_tenant(store) -> TenantId:
    tenant_id = new_id(TenantId)
    store.create_tenant(Tenant(tenant_id=tenant_id, name="Synthetic Transit", created_at=_utc(2026, 1, 1)))
    return tenant_id


def _insert_raw(store, tenant_id: TenantId, *, acting: TenantId | None = None) -> RequestId:
    """Insert one syntactically legal transition row for `tenant_id`, by RAW SQL.

    Deliberately NOT routed through `record_transition`: that method sets the GUC
    and names `tenant_id` in its own WHERE clauses, so a test leaning on it would
    be proving the Python helper rather than the policy. `acting` lets a test
    stamp one tenant's id while acting as another, which is what the WITH CHECK
    half has to refuse.
    """
    request_id = new_id(RequestId)
    store._use_tenant(acting if acting is not None else tenant_id)
    store._conn.execute(
        _INSERT,
        (
            str(new_id(RequestTransitionId)), str(tenant_id), str(request_id), 1,
            ServiceRequestState.REQUESTED.value, ServiceRequestState.DENIED.value,
            iso_fixed_utc(_utc(2026, 7, 1, 9, 14, 3)),
            iso_fixed_utc(_utc(2026, 7, 1, 9, 14, 4)),
            "human", "dispatcher-token-7", '["NO_ACCESSIBLE_CAPACITY"]',
        ),
    )
    store._conn.commit()
    return request_id


def _raw_tenant_ids(store) -> list[str]:
    """A raw, UNFILTERED scan. No WHERE clause at all -- if the policy is not the
    boundary, every operator's refusal history comes back."""
    return [row[0] for row in _query(store, f"SELECT tenant_id FROM {_TABLE}")]  # noqa: S608


# =========================================================================
# 0. The preconditions everything else rests on
# =========================================================================


def test_the_acting_role_is_bound_by_row_security(pg) -> None:
    """If the acting role were a superuser or held BYPASSRLS, the policy on this
    table would be inert and this whole module would be a tautology measuring
    WHERE clauses that are no longer there.

    Both attributes are checked by PostgreSQL BEFORE ownership and before FORCE,
    so neither ENABLE nor FORCE could rescue a privileged connection -- which is
    exactly the trap ADR-0046 and ADR-0052 record, where the container image's
    bootstrap credential turned out to hold rolsuper. ADR-0006 makes
    `milexium_dev` an ordinary role precisely so this assertion can hold; asserting
    it is what lets every later result in this file be read as evidence."""
    acting, is_super, bypasses = _query(
        pg,
        "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user",
    )[0]

    assert is_super is False, (
        f"the canonical store is acting as superuser {acting!r}, which bypasses row "
        "security outright -- every isolation assertion in this module would pass "
        "for the wrong reason"
    )
    assert bypasses is False, f"acting role {acting!r} holds BYPASSRLS"


def test_the_acting_role_owns_the_lifecycle_table(pg) -> None:
    """FORCE is only meaningful against the OWNER. For any other role an ordinary
    privilege error, not the policy, would be what stands in the way, and
    `test_force_row_level_security_is_load_bearing` would prove nothing when it
    lifts FORCE."""
    (owner,) = _query(
        pg,
        "SELECT c.relowner::regrole::text FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = %s",
        (pg._schema, _TABLE),
    )[0]
    (acting,) = _query(pg, "SELECT current_user")[0]

    assert owner == acting, (
        f"{_TABLE} is owned by {owner!r} but the store acts as {acting!r} -- FORCE "
        "would not be what constrains it"
    )


# =========================================================================
# 1. The policy is installed, with FORCE
# =========================================================================


def test_the_lifecycle_table_has_rls_enabled_and_forced(pg) -> None:
    """Read straight out of `pg_class` rather than inferred from behaviour: an
    ENABLE-only setup fails HERE, explicitly, instead of being caught indirectly
    or missed. `relforcerowsecurity` is the bit that actually matters, because the
    acting role owns this table."""
    rows = _query(
        pg,
        "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = %s",
        (pg._schema, _TABLE),
    )
    assert rows, f"{_TABLE} does not exist in the canonical schema"
    enabled, forced = rows[0]

    assert enabled is True, (
        f"{_TABLE} has no ROW LEVEL SECURITY -- a tenant-scoped table with no policy "
        "is the exact false assurance ADR-0018 exists to prevent, and this table "
        "holds one operator's per-rider refusal history"
    )
    assert forced is True, (
        f"{_TABLE} has ENABLE but not FORCE -- milexium_dev OWNS it and would bypass "
        "the policy, so every isolation test below would pass for the wrong reason"
    )


def test_the_lifecycle_table_carries_exactly_one_tenant_policy(pg) -> None:
    """A table with RLS enabled and NO policy denies everything, which looks like
    isolation and is actually an outage; a table with several could be permissive
    in a way no single policy's text reveals, because multiple PERMISSIVE policies
    are OR-ed together."""
    names = [
        row[0]
        for row in _query(
            pg,
            "SELECT p.polname FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relname = %s",
            (pg._schema, _TABLE),
        )
    ]
    assert names == ["tenant_isolation"], f"{_TABLE} has policies {names!r}"


def test_the_lifecycle_policy_is_not_written_as_an_is_not_null_guard(pg) -> None:
    """ADR-0043's trap, read out of the policy's OWN TEXT rather than out of the
    file we wrote.

    The tempting way to write a deny guard is "the GUC IS NOT NULL". That is wrong
    after a `RESET`, where `current_setting(name, true)` returns the EMPTY STRING
    and `IS NOT NULL` happily accepts it -- a pooled connection handed back and
    reused would then read every row in the table. This policy is a plain equality
    against the GUC, which survives the reset case because `tenant_id = ''` is
    false for any real UUID; asserting the SHAPE here is what stops a future edit
    "fixing" it into the form that has already caught this repository once."""
    expressions = _query(
        pg,
        "SELECT pg_get_expr(p.polqual, p.polrelid), pg_get_expr(p.polwithcheck, p.polrelid) "
        "FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = %s",
        (pg._schema, _TABLE),
    )[0]

    for clause in expressions:
        assert clause is not None, "the policy is missing a USING or a WITH CHECK clause"
        assert "is not null" not in clause.lower(), (
            f"the {_TABLE} policy is written as an IS NOT NULL guard ({clause!r}), "
            "which does NOT deny a session whose GUC was RESET -- see ADR-0043"
        )
        assert "current_setting('milexium.tenant_id'" in clause.lower(), (
            f"the policy is not keyed on the session GUC at all: {clause!r}"
        )


# =========================================================================
# 2. Cross-tenant reads, positive controls, and the deny-all default
# =========================================================================


def test_tenant_b_cannot_read_tenant_a_transitions(pg) -> None:
    """THE CORE PROOF. Acting as tenant B, a raw table scan with NO WHERE clause
    returns none of tenant A's rows -- and what it would have returned is A's
    record of which riders it refused and on what grounds."""
    tenant_a, tenant_b = _new_tenant(pg), _new_tenant(pg)
    _insert_raw(pg, tenant_a)
    _insert_raw(pg, tenant_b)

    pg._use_tenant(tenant_b)
    visible = _raw_tenant_ids(pg)

    assert set(visible) == {str(tenant_b)}, (
        f"a raw unfiltered scan of {_TABLE} as tenant B returned {visible!r} -- "
        "another operator's service-denial history leaked"
    )
    assert str(tenant_a) not in visible


def test_a_tenants_own_transitions_are_still_visible(pg) -> None:
    """POSITIVE CONTROL: the policy must not over-block. Without this, the denial
    above would be equally satisfied by an empty table, by a broken INSERT, or by
    a policy that denies everyone -- and would prove nothing at all."""
    tenant_a, tenant_b = _new_tenant(pg), _new_tenant(pg)
    _insert_raw(pg, tenant_a)
    _insert_raw(pg, tenant_b)

    pg._use_tenant(tenant_a)
    assert _raw_tenant_ids(pg) == [str(tenant_a)], "tenant A cannot see its own row"


def test_the_store_read_is_policy_scoped_even_with_its_where_clause_deleted(pg) -> None:
    """The store's own `request_lifecycle` query, re-issued with the `tenant_id`
    filter REMOVED, while acting as the wrong tenant.

    This is the difference between "the application filters" and "the database
    isolates": the exact SELECT the store runs, minus the line a refactor could
    drop, still returns nothing. The positive control at the end proves the row is
    really there and really readable by its owner."""
    tenant_a, tenant_b = _new_tenant(pg), _new_tenant(pg)
    request_id = _insert_raw(pg, tenant_a)

    unfiltered = (
        "SELECT transition_id, sequence, from_state, to_state FROM "  # noqa: S608
        f"{_TABLE} WHERE request_id = %s ORDER BY sequence ASC"
    )

    pg._use_tenant(tenant_b)
    assert _query(pg, unfiltered, (str(request_id),)) == [], (
        "the store's own read, with only its tenant filter removed, returned another "
        "operator's lifecycle record -- the policy is not the boundary"
    )

    pg._use_tenant(tenant_a)
    assert len(_query(pg, unfiltered, (str(request_id),))) == 1, (
        "positive control failed: tenant A cannot read its own row even with no "
        "tenant filter, so the empty result above proves nothing"
    )


def test_a_reset_guc_denies_everything_and_reads_back_as_the_empty_string(pg) -> None:
    """Default-DENY, not default-allow -- and THE EMPTY-STRING TRAP, asserted
    rather than assumed (ADR-0043).

    `current_setting(name, true)` returns NULL only when the GUC was NEVER set;
    once set and RESET it returns the EMPTY STRING. This pins BOTH facts: that the
    value really is `''` here, and that deny-all holds anyway -- because
    `tenant_id = ''` is false for any real UUIDv7. Pinning them together is what
    stops a future edit "fixing" the policy with an IS NOT NULL check that
    silently opens the door."""
    _insert_raw(pg, _new_tenant(pg))
    _insert_raw(pg, _new_tenant(pg))

    pg._conn.execute("RESET milexium.tenant_id")
    is_null, value = _query(
        pg,
        "SELECT current_setting('milexium.tenant_id', true) IS NULL, "
        "current_setting('milexium.tenant_id', true)",
    )[0]
    visible = _raw_tenant_ids(pg)

    assert is_null is False and value == "", (
        "a RESET GUC is expected to read back as the EMPTY STRING, not NULL -- if this "
        "ever changes, any guard written as `IS NOT NULL` becomes load-bearing in a "
        "way it was never tested for"
    )
    assert visible == [], (
        f"a reset milexium.tenant_id exposed {len(visible)} lifecycle rows -- the "
        "policy defaults to allow-all, which is backwards"
    )


def test_a_session_that_never_set_the_guc_sees_nothing(pg) -> None:
    """The OTHER half of the trap: a brand-new connection nobody ever scoped --
    a forgotten scope call, or a psql session someone opened with the app
    credential. Here `current_setting(..., true)` really does return NULL, and
    `tenant_id = NULL` is never true.

    A SEPARATE connection is required: the fixture's connection has necessarily
    had the GUC set during seeding and can therefore only ever demonstrate the
    empty-string case above."""
    _insert_raw(pg, _new_tenant(pg))

    unscoped = psycopg.connect(
        host="localhost", port=5432, dbname="milexium_dev",
        user="milexium_dev", password=_read_dev_password(),
    )
    try:
        unscoped.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(pg._schema)))
        (is_null,) = unscoped.execute(
            "SELECT current_setting('milexium.tenant_id', true) IS NULL"
        ).fetchone()
        (count,) = unscoped.execute(
            sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(_TABLE))
        ).fetchone()
        unscoped.commit()
    finally:
        unscoped.close()

    assert is_null is True, "a never-set GUC should read back as NULL"
    assert count == 0, (
        f"an unscoped connection read {count} lifecycle rows -- a connection nobody "
        "assigned a tenant must be able to read nobody's data"
    )


# =========================================================================
# 3. Writes and deletes: the WITH CHECK and USING halves
# =========================================================================


def test_a_transition_stamped_with_a_foreign_tenant_is_rejected(pg) -> None:
    """Acting as one tenant, an INSERT stamped with ANOTHER tenant's id is refused
    by the database, not by Python.

    The read half alone would not be enough, and for THIS table the write half is
    arguably the sharper risk: a forged row in another operator's lifecycle record
    is a fabricated audit trail -- a denial that never happened, or a negotiation
    invented to explain one that did."""
    victim = _new_tenant(pg)
    attacker = _new_tenant(pg)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _insert_raw(pg, victim, acting=attacker)
    pg._conn.rollback()

    pg._use_tenant(victim)
    assert _raw_tenant_ids(pg) == [], "the forged row landed in the victim's record"


def test_a_delete_cannot_reach_another_tenants_transitions(pg) -> None:
    """The USING clause governs DELETE as well as SELECT, so an unqualified
    `DELETE FROM request_state_transitions` -- the shape a careless cleanup script
    takes -- removes only the acting tenant's rows.

    Worth its own test rather than inferred from the SELECT result: this table is
    an append-only evidence ledger, and destroying another operator's copy of it
    is a worse outcome than reading it."""
    tenant_a, tenant_b = _new_tenant(pg), _new_tenant(pg)
    _insert_raw(pg, tenant_a)
    _insert_raw(pg, tenant_b)

    pg._use_tenant(tenant_b)
    pg._conn.execute(f"DELETE FROM {_TABLE}")  # noqa: S608 -- no WHERE clause, on purpose
    pg._conn.commit()

    pg._use_tenant(tenant_a)
    assert _raw_tenant_ids(pg) == [str(tenant_a)], (
        "an unqualified DELETE as tenant B destroyed tenant A's lifecycle record"
    )


# =========================================================================
# 4. FORCE is what binds the owner -- shown by removing it
# =========================================================================


def test_force_row_level_security_is_load_bearing(pg) -> None:
    """The boundary is shown COLLAPSING the instant FORCE is lifted, then restored.

    Without this, `relforcerowsecurity is True` would be a bit asserted because the
    file sets it, not because we know what it does. The acting role OWNS this
    table, so ENABLE alone leaves it entirely unconstrained -- an ENABLE-only
    version of `rls_postgres.sql` would make every other test in this module pass
    while isolating nothing."""
    tenant_a = _new_tenant(pg)
    _insert_raw(pg, tenant_a)
    pg._use_tenant(_new_tenant(pg))  # an unrelated, empty tenant

    assert _raw_tenant_ids(pg) == [], "FORCE RLS should hide tenant A's rows"

    try:
        pg._conn.execute(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY")  # noqa: S608
        assert _raw_tenant_ids(pg) == [str(tenant_a)], (
            "lifting FORCE did not open the table -- the owning role was being "
            "constrained by something other than the policy, so this module would "
            "have been silently proving nothing"
        )
    finally:
        pg._conn.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")  # noqa: S608

    assert _raw_tenant_ids(pg) == [], "the boundary did not come back when FORCE was restored"
    pg._conn.commit()


# =========================================================================
# 5. The boundary composes with the chain rules
# =========================================================================


def test_another_tenants_chain_cannot_advance_or_block_this_ones(pg) -> None:
    """THE COMPOSITION PROOF. Two operators hold the SAME `request_id` -- which is
    what happens when both import from a source system that numbers requests from
    one -- and each walks it to a different outcome.

    Three things have to hold at once, and none of them can rescue a row the
    others exclude: the chain-position counter is derived from what the ACTING
    tenant can see (so both chains start at 1 and neither collides on the UNIQUE
    constraint); the head lookup that decides whether a transition is legal cannot
    see the other tenant's head (so B being DENIED does not make A's request look
    terminal); and each explanation names only its own operator's outcome."""
    tenant_a, tenant_b = _new_tenant(pg), _new_tenant(pg)
    request_id = new_id(RequestId)

    first_a = pg.record_transition(
        tenant_id=tenant_a, request_id=request_id,
        from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.NEGOTIATED,
        decided_at=_utc(2026, 7, 1, 9, 14, 3), recorded_at=_utc(2026, 7, 1, 9, 14, 4),
        actor_type="system", actor_id="scheduler",
        reason_codes=(ReasonCode.NO_ACCESSIBLE_CAPACITY,),
        requested_window=TimeWindow(start=_utc(2026, 7, 1, 8, 0), end=_utc(2026, 7, 1, 8, 30)),
        negotiated_window=TimeWindow(start=_utc(2026, 7, 1, 9, 45), end=_utc(2026, 7, 1, 10, 15)),
    )
    first_b = pg.record_transition(
        tenant_id=tenant_b, request_id=request_id,
        from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.DENIED,
        decided_at=_utc(2026, 7, 1, 7, 0), recorded_at=_utc(2026, 7, 1, 7, 0),
        actor_type="human", actor_id="dispatcher-token-9",
        reason_codes=(ReasonCode.MAX_RIDE_TIME,),
    )

    assert first_a.sequence == 1 and first_b.sequence == 1, (
        "the chain counter is derived globally rather than per tenant -- under RLS "
        "the second operator's write would collide on UNIQUE (tenant_id, request_id, "
        "sequence) and each operator's numbering would leak the other's activity"
    )

    # B's request is DENIED (terminal). If the head lookup crossed tenants, this
    # legal move for A would be refused as a move out of a terminal state.
    second_a = pg.record_transition(
        tenant_id=tenant_a, request_id=request_id,
        from_state=ServiceRequestState.NEGOTIATED, to_state=ServiceRequestState.SCHEDULED,
        decided_at=_utc(2026, 7, 1, 9, 14, 7), recorded_at=_utc(2026, 7, 1, 9, 14, 8),
        actor_type="system", actor_id="scheduler",
    )
    assert second_a.sequence == 2

    assert pg.explain_outcome(tenant_a, request_id).terminal_state is None
    assert (
        pg.explain_outcome(tenant_b, request_id).terminal_state is ServiceRequestState.DENIED
    )
    assert pg.explain_outcome(tenant_b, request_id).outcome_reason_codes == (
        ReasonCode.MAX_RIDE_TIME,
    )
