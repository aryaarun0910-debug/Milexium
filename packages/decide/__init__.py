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
]

CONTRACT_VERSION = "0.2.0"
