"""Decision IR (Program F contract, v0.1).

The typed problem-and-solution vocabulary the Decide program reasons over: a
small paratransit assignment problem (requests with pickup/dropoff windows, a
mobility-device need, and a max ride time; vehicles with ambulatory/wheelchair
capacity and a shift; a policy) plus a `DecisionSolution` (which request went on
which vehicle, at what pickup/dropoff time, which requests were denied and why,
the solver's honest status, and the objective/bound/gap only where claimable).

This module is data only -- it defines *what* a decision problem and its answer
are, not how either is produced or checked. The candidate generator lives in
`packages.decide.solver`; the INDEPENDENT feasibility checker lives in
`packages.decide.feasibility`. Keeping the shared vocabulary here lets the
checker validate a solution the solver never produced (proving independence).

Time modelling (v0.1): the ride takes a fixed `nominal_ride_time_minutes`; the
solver's only continuous freedom is the pickup time, from which the dropoff time
follows. Real detour-driven ride-time inflation and a travel-time matrix are
Specified, not built. Reused canonical concepts: `ScheduleRunStatus` (the honest
solver status) and `ReasonCode` (why a request was denied).
"""

from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.canonical.ids import PolicyId, RequestId, TenantId, VehicleId
from packages.canonical.time import UtcDateTime
from packages.canonical.vocab import ReasonCode, ScheduleRunStatus


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RideRequest(_Frozen):
    """One rider's trip request. `must_serve` marks a mandated trip (ADA
    complementary paratransit is legally must-serve) -- an instance where a
    must_serve request cannot be scheduled is genuinely INFEASIBLE, not just a
    denial."""

    request_id: RequestId
    pickup_window_start: UtcDateTime
    pickup_window_end: UtcDateTime
    dropoff_window_start: UtcDateTime | None = None
    dropoff_window_end: UtcDateTime
    needs_wheelchair: bool = False
    party_size: int = Field(default=1, ge=1, description="Ambulatory seats consumed; a wheelchair rider consumes one wheelchair position instead.")
    nominal_ride_time_minutes: float = Field(gt=0.0, description="Fixed in-vehicle duration; dropoff = pickup + this.")
    max_ride_time_minutes: float = Field(gt=0.0, description="ADA ceiling on in-vehicle time; a request whose nominal exceeds this can never be served.")
    must_serve: bool = True

    @model_validator(mode="after")
    def _windows_ordered(self) -> "RideRequest":
        if self.pickup_window_start > self.pickup_window_end:
            raise ValueError("pickup_window_start must not be after pickup_window_end")
        if self.dropoff_window_start is not None and self.dropoff_window_start > self.dropoff_window_end:
            raise ValueError("dropoff_window_start must not be after dropoff_window_end")
        return self

    @property
    def nominal_ride(self) -> timedelta:
        return timedelta(minutes=self.nominal_ride_time_minutes)


class DecisionVehicle(_Frozen):
    """A vehicle bound to a driver shift -- the schedulable duty the solver
    assigns to. Composes canonical `Vehicle` (capacity) with a canonical
    `Driver` shift window; kept as one object here because the solver reasons
    over vehicle-time, not the two entities separately."""

    vehicle_id: VehicleId
    capacity_ambulatory: int = Field(ge=0)
    capacity_wheelchair: int = Field(ge=0)
    shift_start: UtcDateTime
    shift_end: UtcDateTime

    @model_validator(mode="after")
    def _shift_ordered(self) -> "DecisionVehicle":
        if self.shift_start >= self.shift_end:
            raise ValueError("shift_start must be before shift_end")
        return self


class DecisionPolicy(_Frozen):
    """Objective weights and solver budget. The exact solver searches pickup
    times on a grid of `time_granularity_minutes`, so it proves optimality
    relative to that discretization (an honest, bounded claim), not over
    continuous time."""

    policy_id: PolicyId
    name: str
    time_granularity_minutes: int = Field(default=5, ge=1)
    unserved_penalty: float = Field(default=1000.0, ge=0.0, description="Objective cost added per denied non-mandated request.")
    ride_time_weight: float = Field(default=1.0, ge=0.0, description="Objective weight on total scheduled in-vehicle minutes.")
    max_search_nodes: int = Field(default=200_000, ge=1, description="Branch-and-bound node budget; exceeding it forces an honest TIMEOUT rather than a claimed optimum.")
    exact_max_requests: int = Field(default=12, ge=1, description="Above this request count the exact solver is skipped for the greedy fallback (FEASIBLE, not proven optimal).")


class DecisionProblem(_Frozen):
    tenant_id: TenantId
    policy: DecisionPolicy
    vehicles: tuple[DecisionVehicle, ...]
    requests: tuple[RideRequest, ...]


class Assignment(_Frozen):
    """One request placed on one vehicle at concrete pickup/dropoff times."""

    request_id: RequestId
    vehicle_id: VehicleId
    pickup_time: UtcDateTime
    dropoff_time: UtcDateTime


class Denial(_Frozen):
    """A request left unserved, with the hard-constraint reason codes that
    explain why. Never SHAP output or generated prose (blueprint 06)."""

    request_id: RequestId
    reason_codes: tuple[ReasonCode, ...] = Field(min_length=1)


class DecisionSolution(_Frozen):
    """A proposed answer to a `DecisionProblem`.

    `status` is the honest solver outcome. `gap`/`bound` are populated ONLY when
    a valid optimality claim exists (status OPTIMAL); a TIMEOUT or greedy
    FEASIBLE result leaves them None rather than dressing an incumbent up as
    proven-optimal (the failure mode blueprint 15 names by name).
    """

    status: ScheduleRunStatus
    assignments: tuple[Assignment, ...] = ()
    unserved: tuple[Denial, ...] = ()
    objective_value: float | None = None
    bound: float | None = None
    gap: float | None = None
    seed: int
    solver_name: str
    solver_version: str

    @property
    def proven_optimal(self) -> bool:
        """True only when the solver actually certified optimality. Callers must
        gate any 'optimal plan' claim on this, never on status alone."""
        return self.status is ScheduleRunStatus.OPTIMAL and self.gap == 0.0
