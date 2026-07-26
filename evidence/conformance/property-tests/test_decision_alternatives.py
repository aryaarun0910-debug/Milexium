"""Conformance tests for DecisionAlternative storage (MX-A-CANONICAL-DEBT-003).

`decision_alternatives` has been defined in schema_v0_1.sql since v0.1, but until
this packet NEITHER store read nor wrote it: "why not the alternatives?" -- a
load-bearing explainability claim -- had no storage behind it, and Program I had
to work around the gap by embedding alternatives in a RECOMMENDATION event
payload (knowledge/architecture/decisions/0009-...). That convention is untouched; these
tests prove the table is now usable, not that anything migrated onto it.

Every behavioural test runs against BOTH stores through one parametrized fixture,
because the whole claim being made is that `SqliteCanonicalStore` and
`PostgresCanonicalStore` expose the SAME method contract (ADR-0004). A test that
only ran on SQLite would prove half of it.

The PostgreSQL parameter skips cleanly (not a failure) when `milexium_dev` is
unreachable, matching evidence/conformance/property-tests/test_postgres_event_log_properties.py,
so this suite stays green on a machine where it was never provisioned. The SQLite
parameter always runs.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest

from app.canonical import (
    DecisionAlternative,
    PolicyId,
    ReasonCode,
    RequestId,
    ScheduleRunId,
    Tenant,
    TenantId,
    VehicleId,
    new_id,
)
from app.canonical.postgres_storage import PostgresCanonicalStore
from app.canonical.postgres_storage import is_reachable as pg_is_reachable
from app.canonical.storage import CrossTenantWriteError, SqliteCanonicalStore


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture(params=["sqlite", "postgres"])
def store(request):
    """The same tests, both engines. `params` (not two copies of each test) is
    what makes "identical method contract" a property under test rather than a
    claim in a docstring."""
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
            "skipping the PostgreSQL half of the DecisionAlternative contract"
        )
    st = PostgresCanonicalStore.connect()
    try:
        yield st
    finally:
        st.drop_schema()
        st.close()


def _tenant(name: str = "alternatives-conformance") -> Tenant:
    return Tenant(tenant_id=new_id(TenantId), name=name, created_at=_utc(2026, 7, 24))


def _exec(store, statement: str, params: tuple) -> None:
    """Run raw DDL-adjacent seed SQL against whichever engine `store` wraps.

    Neither store has (or needs, for this packet) a `create_schedule_run` method,
    so the FK parents a DecisionAlternative requires are seeded directly here --
    the same raw-SQL stance evidence/conformance/adversarial/test_postgres_rls_isolation.py
    takes. `?` is rewritten to `%s` for psycopg; the SQL itself is identical
    because schema_v0_1.sql is portable.
    """
    placeholder = "?" if isinstance(store, SqliteCanonicalStore) else "%s"
    store._conn.execute(statement.replace("?", placeholder), params)


def _seed_schedule_run(store, tenant: Tenant) -> tuple[ScheduleRunId, VehicleId]:
    """Register `tenant` and give it one policy, one vehicle and one schedule run
    (the FK parents `decision_alternatives` requires). Returns the run and the
    vehicle a candidate alternative can name."""
    store.create_tenant(tenant)
    if isinstance(store, PostgresCanonicalStore):
        # Raw seed writes go through the RLS policies too, so the acting GUC has
        # to name this tenant -- exactly what the store's own methods do.
        store._use_tenant(tenant.tenant_id)

    policy_id = str(new_id(PolicyId))
    vehicle_id = str(new_id(VehicleId))
    run_id = str(new_id(ScheduleRunId))
    _exec(
        store,
        "INSERT INTO policies (policy_id, version, tenant_id, name, config_json, "
        "effective_from) VALUES (?,?,?,?,?,?)",
        (policy_id, 1, str(tenant.tenant_id), "baseline", "{}", "2026-07-24T00:00:00+00:00"),
    )
    _exec(
        store,
        "INSERT INTO vehicles (vehicle_id, tenant_id, capacity_ambulatory, "
        "capacity_wheelchair, accessibility_equipment) VALUES (?,?,?,?,?)",
        (vehicle_id, str(tenant.tenant_id), 4, 1, "[]"),
    )
    _exec(
        store,
        "INSERT INTO schedule_runs (schedule_run_id, tenant_id, policy_id, policy_version, "
        "solver_name, solver_version, seed, status, started_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            run_id,
            str(tenant.tenant_id),
            policy_id,
            1,
            "reference-solver",
            "0.1.0",
            42,
            "optimal",
            "2026-07-24T08:00:00+00:00",
        ),
    )
    store._conn.commit()
    return ScheduleRunId(run_id), VehicleId(vehicle_id)


# -- the contract itself ----------------------------------------------------


def test_both_stores_expose_the_same_decision_alternative_contract() -> None:
    """The mirrored-contract claim, checked structurally rather than trusted:
    same method names, same signatures, on both stores."""
    for name in ("append_decision_alternative", "decision_alternatives"):
        sqlite_method = getattr(SqliteCanonicalStore, name)
        postgres_method = getattr(PostgresCanonicalStore, name)
        assert inspect.signature(sqlite_method) == inspect.signature(postgres_method), (
            f"{name} has diverged between the SQLite and PostgreSQL stores"
        )


# -- round-trip -------------------------------------------------------------


def test_append_and_read_round_trips_an_infeasible_alternative(store) -> None:
    """The debt this packet clears: an alternative that was CONSIDERED and
    REJECTED, with the reason codes explaining why, survives a write/read."""
    tenant = _tenant()
    run_id, vehicle_id = _seed_schedule_run(store, tenant)

    alternative = DecisionAlternative(
        schedule_run_id=run_id,
        request_id=new_id(RequestId),
        candidate_vehicle_id=vehicle_id,
        feasible=False,
        failed_constraints=(ReasonCode.NO_ACCESSIBLE_CAPACITY, ReasonCode.PICKUP_WINDOW),
        objective_delta=12.5,
    )
    store.append_decision_alternative(tenant_id=tenant.tenant_id, alternative=alternative)

    assert store.decision_alternatives(tenant.tenant_id, run_id) == (alternative,)


def test_feasible_alternative_with_no_candidate_vehicle_round_trips(store) -> None:
    """The nullable/empty edges: no candidate vehicle, no failed constraints, no
    objective delta -- a feasible alternative must not be coerced into the
    infeasible shape by the storage layer."""
    tenant = _tenant()
    run_id, _ = _seed_schedule_run(store, tenant)

    alternative = DecisionAlternative(
        schedule_run_id=run_id,
        request_id=new_id(RequestId),
        candidate_vehicle_id=None,
        feasible=True,
        failed_constraints=(),
        objective_delta=None,
    )
    store.append_decision_alternative(tenant_id=tenant.tenant_id, alternative=alternative)

    (stored,) = store.decision_alternatives(tenant.tenant_id, run_id)
    assert stored == alternative
    assert stored.feasible is True
    assert stored.candidate_vehicle_id is None
    assert stored.failed_constraints == ()
    assert stored.objective_delta is None


def test_alternatives_are_returned_in_a_deterministic_order(store) -> None:
    """Both stores must return the same SEQUENCE, not merely the same set --
    candidates first (ordered by vehicle id), then the no-vehicle alternative,
    within each request. Written portably so SQLite and PostgreSQL agree."""
    tenant = _tenant()
    run_id, vehicle_id = _seed_schedule_run(store, tenant)
    request_id = new_id(RequestId)

    no_vehicle = DecisionAlternative(
        schedule_run_id=run_id, request_id=request_id, feasible=False,
        failed_constraints=(ReasonCode.NO_ACCESSIBLE_CAPACITY,),
    )
    with_vehicle = DecisionAlternative(
        schedule_run_id=run_id, request_id=request_id,
        candidate_vehicle_id=vehicle_id, feasible=True, objective_delta=-3.0,
    )
    # Inserted no-vehicle FIRST, so insertion order is not what is being read back.
    store.append_decision_alternative(tenant_id=tenant.tenant_id, alternative=no_vehicle)
    store.append_decision_alternative(tenant_id=tenant.tenant_id, alternative=with_vehicle)

    assert store.decision_alternatives(tenant.tenant_id, run_id) == (with_vehicle, no_vehicle)


def test_reading_a_run_with_no_alternatives_returns_empty(store) -> None:
    tenant = _tenant()
    run_id, _ = _seed_schedule_run(store, tenant)
    assert store.decision_alternatives(tenant.tenant_id, run_id) == ()


# -- tenant isolation -------------------------------------------------------


def test_writing_an_alternative_for_another_tenants_run_is_rejected(store) -> None:
    """The packet's failure injection. `decision_alternatives` has no tenant_id
    column of its own, so an unchecked store would happily attach tenant A's
    reasoning to a run tenant B claims to act for. Both stores refuse, with the
    same error type."""
    tenant_a = _tenant("tenant-a")
    tenant_b = _tenant("tenant-b")
    run_of_a, _ = _seed_schedule_run(store, tenant_a)
    _seed_schedule_run(store, tenant_b)

    forged = DecisionAlternative(
        schedule_run_id=run_of_a,  # A's run ...
        request_id=new_id(RequestId),
        feasible=False,
        failed_constraints=(ReasonCode.SHIFT_END,),
    )
    with pytest.raises(CrossTenantWriteError):
        store.append_decision_alternative(
            tenant_id=tenant_b.tenant_id, alternative=forged  # ... written as B
        )

    # And nothing landed: A's run still has no alternatives.
    assert store.decision_alternatives(tenant_a.tenant_id, run_of_a) == ()


def test_writing_an_alternative_for_an_unknown_run_is_rejected(store) -> None:
    """A run that exists for nobody is refused by the same check -- the parent is
    resolved, never assumed from the caller's word."""
    tenant = _tenant()
    _seed_schedule_run(store, tenant)

    with pytest.raises(CrossTenantWriteError):
        store.append_decision_alternative(
            tenant_id=tenant.tenant_id,
            alternative=DecisionAlternative(
                schedule_run_id=new_id(ScheduleRunId),  # never inserted
                request_id=new_id(RequestId),
                feasible=True,
            ),
        )


def test_reading_another_tenants_run_returns_nothing(store) -> None:
    """The read is scoped through the parent run's tenant in SQL. Tenant B naming
    tenant A's run id -- the id is not a secret -- gets nothing back, rather than
    A's reasoning."""
    tenant_a = _tenant("tenant-a")
    tenant_b = _tenant("tenant-b")
    run_of_a, vehicle_of_a = _seed_schedule_run(store, tenant_a)
    _seed_schedule_run(store, tenant_b)

    store.append_decision_alternative(
        tenant_id=tenant_a.tenant_id,
        alternative=DecisionAlternative(
            schedule_run_id=run_of_a,
            request_id=new_id(RequestId),
            candidate_vehicle_id=vehicle_of_a,
            feasible=True,
        ),
    )

    assert len(store.decision_alternatives(tenant_a.tenant_id, run_of_a)) == 1
    assert store.decision_alternatives(tenant_b.tenant_id, run_of_a) == ()


def test_adr_0009_embedded_payload_convention_still_works_alongside_the_table(store) -> None:
    """Explicit non-regression for the coexistence the packet requires: making the
    table usable does NOT force a cutover. The same alternatives can be recorded
    BOTH in a RECOMMENDATION event payload (the v0.1 ADR-0009 convention Program I
    relies on) and in the table, with neither disturbing the other."""
    from app.canonical import DecisionEventType  # local: only this test needs it

    tenant = _tenant()
    run_id, vehicle_id = _seed_schedule_run(store, tenant)
    request_id = new_id(RequestId)

    embedded = {
        "alternatives": [
            {"candidate_vehicle_id": str(vehicle_id), "feasible": False,
             "failed_constraints": [ReasonCode.MAX_RIDE_TIME.value]}
        ]
    }
    event = store.append_event(
        tenant_id=tenant.tenant_id,
        aggregate_id=str(request_id),
        aggregate_type="ServiceRequest",
        occurred_at=_utc(2026, 7, 24, 8, 0),
        actor_type="system",
        actor_id="scheduler",
        event_type=DecisionEventType.RECOMMENDATION,
        payload=embedded,
    )
    store.append_decision_alternative(
        tenant_id=tenant.tenant_id,
        alternative=DecisionAlternative(
            schedule_run_id=run_id, request_id=request_id,
            candidate_vehicle_id=vehicle_id, feasible=False,
            failed_constraints=(ReasonCode.MAX_RIDE_TIME,),
        ),
    )

    history = store.history(tenant.tenant_id, str(request_id))
    assert history[0].payload == embedded  # the ADR-0009 payload is intact
    assert history[0].hash == event.hash  # and its hash chain is undisturbed
    assert len(store.decision_alternatives(tenant.tenant_id, run_id)) == 1
