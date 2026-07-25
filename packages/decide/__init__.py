"""Program F: Decide -- policy and optimisation contract (v0.1 slice).

The expansion's Decision program contract, built additively as `packages/decide`.
It is NOT the founder-owned YC scheduler in `reference_agency/` and does not
replace it: this slice proves the Program F *contract properties* (blueprint 06 +
14) on a small paratransit assignment problem, the same generator/verifier
discipline `packages.verify` holds against `packages.canonical`.

The three load-bearing properties it demonstrates:

- The candidate generator (`solver`) and the independent feasibility checker
  (`feasibility`) are SEPARATE modules with a one-way dependency -- the solver
  self-audits against the checker; the checker never imports the solver and can
  validate a solution the solver never produced.
- No accepted result violates a hard constraint: the checker rejects any
  infeasible assignment with a canonical `ReasonCode`.
- Honest solver status: optimal / feasible / infeasible / timeout, and a timeout
  incumbent is NEVER dressed up as a proven optimum.

v0.1 backends are pure Python (a grid-exact branch-and-bound + a greedy
fallback). CP-SAT / MILP / SMT / a heuristic portfolio are Specified in
blueprint 06, not built here.
"""

from packages.decide.feasibility import (
    DarpViolation,
    MalformedDarpSolution,
    MalformedSolution,
    Violation,
    check_darp_feasibility,
    check_feasibility,
    darp_objective,
    darp_served_requests,
    is_darp_feasible,
    is_feasible,
)
from packages.decide.ir import (
    Assignment,
    DecisionPolicy,
    DecisionProblem,
    DecisionSolution,
    DecisionVehicle,
    Denial,
    RideRequest,
)
from packages.decide.solver import SOLVER_NAME, SOLVER_VERSION, solve

# DARP routing extension (v0.2) -- additive; the v0.1 API above is unchanged.
from packages.decide.darp_ir import (
    DarpInstance,
    DarpNode,
    DarpRoute,
    DarpSolution,
    DarpVisit,
)
from packages.decide.darp_loader import (
    find_benchmark_archive,
    list_zip_instances,
    load_instance_file,
    load_zip_instance,
    parse_instance,
)
from packages.decide.darp_solver import (
    DARP_SOLVER_NAME,
    DARP_SOLVER_VERSION,
    schedule_route,
    solve_darp,
)
from packages.decide.darp_bridge import project_darp_solution

# Solver portfolio (v0.3) -- additive; every API above is unchanged.
#
# NOTE ON IMPORT SAFETY: none of these modules import `ortools` at module scope.
# The import happens inside the solve functions, behind `ortools_capability()`.
# That is deliberate and load-bearing -- `import packages.decide` must succeed on
# a machine with no OR-Tools wheel, or every unrelated test in the suite would
# fail on an optional dependency.
from packages.decide.capability import (
    SolverCapability,
    SolverUnavailable,
    cpsat_available,
    ortools_capability,
)
from packages.decide.cpsat import (
    CPSAT_SOLVER_NAME,
    CPSAT_SOLVER_VERSION,
    CpSatModelTooLarge,
    CpSatOutcome,
    solve_cpsat,
    solve_cpsat_detailed,
)
from packages.decide.cpsat_darp import (
    CPSAT_DARP_SOLVER_NAME,
    CPSAT_DARP_SOLVER_VERSION,
    CpSatDarpOutcome,
    DarpModelUnsupported,
    exact_schedule,
    solve_darp_cpsat,
)
from packages.decide.portfolio import (
    PORTFOLIO_VERSION,
    PortfolioContradiction,
    PortfolioReport,
    StrategyRun,
    solve_darp_portfolio,
    solve_portfolio,
)

# Commingled online exposure (v0.4) -- additive; every API above is unchanged.
#
# The offline path above sees every request before committing to any of them.
# These three modules add the SAME-DAY case, where it does not: requests arrive
# over time, each commitment is irrevocable, and the measurable question is what
# not seeing the future costs and WHO it costs. `commingled` adds the shared-floor
# constraint the v0.1 IR cannot express (without which commingling is free by
# construction); `online` is the sequential harness; `exposure` is the
# online-vs-offline gap, its accessibility breakdown, and the capacity
# attribution behind each denial.
#
# Same import-safety rule as v0.3: nothing here imports `ortools` at module scope.
from packages.decide.commingled import (
    COMMINGLED_SOLVER_NAME,
    COMMINGLED_SOLVER_VERSION,
    AcceptedRide,
    CommingledFleet,
    CommingledInstance,
    CommingledOutcome,
    DenialPenaltyTooWeak,
    InstanceProvenance,
    Placement,
    assert_denial_dominates,
    check_commingled,
    check_floor_feasibility,
    commingled_objective,
    derive_commingled_instance,
    feasible_placements,
    has_placement,
    pool_only_relaxation,
    solve_commingled_offline,
)
from packages.decide.online import (
    ONLINE_HARNESS_NAME,
    ONLINE_HARNESS_VERSION,
    POLICIES,
    Arrival,
    Commitment,
    InvalidPlacement,
    IrrevocabilityViolation,
    OnlineOutcome,
    OnlineView,
    RationingRefused,
    arrivals_from,
    first_fit,
    preserve_accessible_capacity,
    run_online,
)
from packages.decide.exposure import (
    AMBULATORY,
    EXPOSURE_VERSION,
    WHEELCHAIR,
    CapacityAttribution,
    CohortExposure,
    ExposureReport,
    attribute_capacity,
    measure_exposure,
)

__all__ = [
    "Assignment",
    "DecisionPolicy",
    "DecisionProblem",
    "DecisionSolution",
    "DecisionVehicle",
    "Denial",
    "RideRequest",
    "MalformedSolution",
    "Violation",
    "check_feasibility",
    "is_feasible",
    "solve",
    "SOLVER_NAME",
    "SOLVER_VERSION",
    # DARP routing extension (v0.2)
    "DarpInstance",
    "DarpNode",
    "DarpRoute",
    "DarpSolution",
    "DarpVisit",
    "DarpViolation",
    "MalformedDarpSolution",
    "check_darp_feasibility",
    "is_darp_feasible",
    "darp_objective",
    "darp_served_requests",
    "parse_instance",
    "load_instance_file",
    "load_zip_instance",
    "list_zip_instances",
    "find_benchmark_archive",
    "schedule_route",
    "solve_darp",
    "project_darp_solution",
    "DARP_SOLVER_NAME",
    "DARP_SOLVER_VERSION",
    # Solver portfolio (v0.3)
    "SolverCapability",
    "SolverUnavailable",
    "cpsat_available",
    "ortools_capability",
    "CpSatModelTooLarge",
    "CpSatOutcome",
    "solve_cpsat",
    "solve_cpsat_detailed",
    "CPSAT_SOLVER_NAME",
    "CPSAT_SOLVER_VERSION",
    "CpSatDarpOutcome",
    "DarpModelUnsupported",
    "exact_schedule",
    "solve_darp_cpsat",
    "CPSAT_DARP_SOLVER_NAME",
    "CPSAT_DARP_SOLVER_VERSION",
    "PortfolioContradiction",
    "PortfolioReport",
    "StrategyRun",
    "solve_portfolio",
    "solve_darp_portfolio",
    "PORTFOLIO_VERSION",
    # Commingled online exposure (v0.4)
    "AcceptedRide",
    "CommingledFleet",
    "CommingledInstance",
    "CommingledOutcome",
    "DenialPenaltyTooWeak",
    "InstanceProvenance",
    "Placement",
    "assert_denial_dominates",
    "check_commingled",
    "check_floor_feasibility",
    "commingled_objective",
    "derive_commingled_instance",
    "feasible_placements",
    "has_placement",
    "pool_only_relaxation",
    "solve_commingled_offline",
    "COMMINGLED_SOLVER_NAME",
    "COMMINGLED_SOLVER_VERSION",
    "Arrival",
    "Commitment",
    "InvalidPlacement",
    "IrrevocabilityViolation",
    "OnlineOutcome",
    "OnlineView",
    "POLICIES",
    "RationingRefused",
    "arrivals_from",
    "first_fit",
    "preserve_accessible_capacity",
    "run_online",
    "ONLINE_HARNESS_NAME",
    "ONLINE_HARNESS_VERSION",
    "AMBULATORY",
    "WHEELCHAIR",
    "CapacityAttribution",
    "CohortExposure",
    "ExposureReport",
    "attribute_capacity",
    "measure_exposure",
    "EXPOSURE_VERSION",
]

CONTRACT_VERSION = "0.4.0"
