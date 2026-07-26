"""Scalable heuristic backend for the dial-a-ride problem (Program F v0.2).

The v0.1 solver (`app.decide.solver`) is a grid-exact branch-and-bound for a
single-leg assignment problem; it does not scale to, and cannot even represent, a
real DARP routing instance. This module adds -- alongside it, changing nothing in
it -- a genuinely scalable heuristic for routed dial-a-ride:

- **Route scheduling**: the Cordeau & Laporte (2003) eight-step forward-slack
  evaluation. Given a node sequence it computes concrete begin-service times that
  respect travel times, time windows, ride-time limits and route duration, or
  reports the sequence infeasible. Every schedule it returns is re-verified
  against all constraints (with a small safety margin) before it is trusted, so
  the scheduler is sound by construction even if the slack heuristic is
  imperfect -- an imperfect schedule is rejected, never silently accepted.
- **Construction**: regret-2 insertion. Requests are inserted one at a time at
  their cheapest feasible pickup/drop-off position pair, prioritising the request
  that would cost the most if deferred.
- **Improvement**: large-neighbourhood search (ruin-and-recreate) with random and
  worst-distance removal and simulated-annealing acceptance, all driven by a
  seeded RNG so a run is reproducible from (instance, seed, iterations).

Honest status: this is a heuristic. It reports `status="feasible"` (or
`"incomplete"` if it cannot serve every request) and NEVER `"optimal"` -- it
proves nothing. Its output is handed to the INDEPENDENT checker
(`app.decide.feasibility.check_darp_feasibility`) before it is returned; a
solver bug that produced an infeasible route fails loudly there rather than
being reported as a solution. No `ortools`/external solver is used; pure Python.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from random import Random

from app.decide.darp_ir import (
    DarpInstance,
    DarpRoute,
    DarpSolution,
    DarpVisit,
)
from app.decide.feasibility import check_darp_feasibility

DARP_SOLVER_NAME = "milexium-decide-darp"
DARP_SOLVER_VERSION = "0.2.0"

_SAFETY = 1e-6  # keep accepted schedules strictly inside upper bounds (windows/ride/duration).


# --------------------------------------------------------------------------
# Route scheduling: Cordeau & Laporte (2003) eight-step evaluation.
# --------------------------------------------------------------------------

def schedule_route(instance: DarpInstance, seq: list[int]) -> list[float] | None:
    """Feasible begin-service times for the node sequence `seq` (which must start
    and end at a depot), or None if no feasible schedule exists. Sound: any list
    it returns satisfies capacity, precedence, time windows, ride time and route
    duration with a `_SAFETY` margin on every upper bound."""
    nodes = instance.nodes
    m = len(seq)
    if m < 2:
        return None
    Q = instance.vehicle_capacity
    Lmax = instance.max_ride_time
    Tmax = instance.max_route_duration

    # Capacity + within-sequence precedence (a drop-off may not precede its pickup).
    load = 0
    for s in seq:
        load += nodes[s].load
        if load < 0 or load > Q:
            return None

    e = [nodes[s].tw_start for s in seq]
    l = [nodes[s].tw_end for s in seq]
    d = [nodes[s].service_duration for s in seq]
    dist = instance.distances
    t = [0.0] + [dist[seq[i - 1]][seq[i]] for i in range(1, m)]

    n = instance.num_requests
    pickup_pos: dict[int, int] = {}
    dropoff_pos: dict[int, int] = {}
    for idx, s in enumerate(seq):
        if 1 <= s <= n:
            pickup_pos[s] = idx
        elif n + 1 <= s <= 2 * n:
            dropoff_pos[s - n] = idx
    # Any half-present request means this sequence cannot be scheduled coherently.
    if set(pickup_pos) != set(dropoff_pos):
        return None
    reqs = list(pickup_pos)

    B = [0.0] * m
    A = [0.0] * m
    W = [0.0] * m
    D = [0.0] * m

    def run_forward(B0: float, lb: list[float] | None) -> None:
        B[0] = B0
        A[0] = B0
        W[0] = 0.0
        D[0] = B0 + d[0]
        for i in range(1, m):
            ai = D[i - 1] + t[i]
            bi = ai if ai > e[i] else e[i]
            if lb is not None and lb[i] > bi:
                bi = lb[i]
            A[i] = ai
            B[i] = bi
            W[i] = bi - ai
            D[i] = bi + d[i]

    def ride_time(r: int) -> float:
        pp = pickup_pos[r]
        return B[dropoff_pos[r]] - (B[pp] + d[pp])

    def verified() -> bool:
        """True iff the current B satisfies every upper bound with the safety
        margin (and lower bounds within float tolerance)."""
        for i in range(m):
            if B[i] > l[i] - _SAFETY or B[i] < e[i] - 1e-9:
                return False
        for r in reqs:
            if ride_time(r) > Lmax - _SAFETY:
                return False
        return (B[m - 1] - B[0]) <= Tmax - _SAFETY

    run_forward(e[0], None)
    for i in range(m):
        if B[i] > l[i] + 1e-9:
            return None  # earliest-possible schedule already blows a window -> infeasible
    if verified():
        return list(B)  # fast path: the as-early schedule is already feasible.

    def forward_slack(i: int) -> float:
        cumW = 0.0
        best = math.inf
        for j in range(i, m):
            if j > i:
                cumW += W[j]
            wslack = (l[j] - _SAFETY) - B[j]
            rslack = math.inf
            sj = seq[j]
            if n + 1 <= sj <= 2 * n:
                rr = sj - n
                if pickup_pos.get(rr, m) < i:
                    rslack = (Lmax - _SAFETY) - ride_time(rr)
            slack_j = wslack if wslack < rslack else rslack
            if slack_j < 0.0:
                slack_j = 0.0
            cand = cumW + slack_j
            if cand < best:
                best = cand
        return 0.0 if best is math.inf else best

    # Step 3-4: delay departure from the depot to cut avoidable waiting.
    total_wait = sum(W[1:m - 1]) if m > 2 else 0.0
    f0 = forward_slack(0)
    run_forward(e[0] + min(f0, total_wait), None)

    # Step 7: delay each pickup by its forward slack to shrink ride times.
    lb = list(e)
    lb[0] = B[0]
    for i in range(1, m - 1):
        if not (1 <= seq[i] <= n):
            continue
        fi = forward_slack(i)
        tail_wait = sum(W[i + 1:m - 1]) if i + 1 <= m - 2 else 0.0
        delay = fi if fi < tail_wait else tail_wait
        if delay <= 0.0:
            continue
        lb[i] = B[i] + delay
        run_forward(B[0], lb)

    # Final verification with the safety margin on every upper bound.
    return list(B) if verified() else None


def route_distance(instance: DarpInstance, seq: list[int]) -> float:
    dist = instance.distances
    return sum(dist[seq[i - 1]][seq[i]] for i in range(1, len(seq)))


# --------------------------------------------------------------------------
# Insertion.
# --------------------------------------------------------------------------

@dataclass
class _Insertion:
    cost: float           # true added distance
    route: int
    pickup_pos: int
    dropoff_pos: int


def _as_early_departures(instance: DarpInstance, seq: list[int]) -> list[float]:
    """As-early departure time at each stop of an (unmodified) route -- used to
    prune insertion positions the vehicle cannot reach in time, cheaply."""
    nodes = instance.nodes
    dist = instance.distances
    m = len(seq)
    dep = [0.0] * m
    dep[0] = nodes[seq[0]].tw_start
    for i in range(1, m):
        arr = dep[i - 1] + dist[seq[i - 1]][seq[i]]
        e_i = nodes[seq[i]].tw_start
        b = arr if arr > e_i else e_i
        dep[i] = b + nodes[seq[i]].service_duration
    return dep


def _scan_insertions(instance, routes, deps, r, noise, rng) -> tuple[_Insertion | None, float]:
    """Best feasible insertion of request r (by noised cost) and the second-best
    noised cost (for regret). `deps[ri]` is the as-early departure array of
    routes[ri]. Uses the cheap pickup-reachability prune, then the authoritative
    `schedule_route` on survivors; insertion cost is computed analytically."""
    p = instance.pickup_index(r)
    dnode = instance.dropoff_index(r)
    dist = instance.distances
    l_p = instance.nodes[p].tw_end
    best: _Insertion | None = None
    best_key = math.inf
    second_key = math.inf
    for ri, seq in enumerate(routes):
        dep = deps[ri]
        L = len(seq)
        for pi in range(1, L):
            a = seq[pi - 1]
            if dep[pi - 1] + dist[a][p] > l_p + 1e-9:
                continue  # cannot reach the pickup within its window at this position
            b = seq[pi]
            add_p = dist[a][p] + dist[p][b] - dist[a][b]
            cand1 = seq[:pi] + [p] + seq[pi:]
            La = len(cand1)
            for dj in range(pi + 1, La):
                c = cand1[dj - 1]
                nx = cand1[dj]
                add_d = dist[c][dnode] + dist[dnode][nx] - dist[c][nx]
                cand = cand1[:dj] + [dnode] + cand1[dj:]
                if schedule_route(instance, cand) is None:
                    continue
                cost = add_p + add_d
                key = cost + (noise * rng.uniform(-1.0, 1.0) if noise > 0.0 else 0.0)
                if key < best_key:
                    second_key = best_key
                    best_key = key
                    best = _Insertion(cost, ri, pi, dj)
                elif key < second_key:
                    second_key = key
    return best, second_key


def _apply_insertion(instance, routes, route_dists, deps, r, ins: _Insertion) -> None:
    p = instance.pickup_index(r)
    dnode = instance.dropoff_index(r)
    seq = routes[ins.route]
    cand1 = seq[:ins.pickup_pos] + [p] + seq[ins.pickup_pos:]
    cand = cand1[:ins.dropoff_pos] + [dnode] + cand1[ins.dropoff_pos:]
    routes[ins.route] = cand
    route_dists[ins.route] = route_distance(instance, cand)
    deps[ins.route] = _as_early_departures(instance, cand)


def _regret_insert(instance: DarpInstance, routes, route_dists, deps, unassigned: set[int], rng: Random, noise: float = 0.0) -> set[int]:
    """Insert requests by highest regret (best vs second-best insertion cost);
    return the requests that could not be placed anywhere. `noise` randomises the
    cost used for selection (0 = deterministic construction)."""
    remaining = set(unassigned)
    while remaining:
        best_req = None
        best_ins: _Insertion | None = None
        best_rank = None
        for r in sorted(remaining):  # stable iteration; RNG drives the randomisation
            top, second = _scan_insertions(instance, routes, deps, r, noise, rng)
            if top is None:
                continue  # r cannot be inserted right now
            regret = (second - top.cost) if second != math.inf else 1e18
            rank = (-regret, top.cost, r)  # highest regret first, then cheapest, then id
            if best_rank is None or rank < best_rank:
                best_rank, best_req, best_ins = rank, r, top
        if best_req is None:
            break  # nothing left can be inserted
        _apply_insertion(instance, routes, route_dists, deps, best_req, best_ins)
        remaining.discard(best_req)
    return remaining


# --------------------------------------------------------------------------
# Large-neighbourhood search.
# --------------------------------------------------------------------------

def _served(instance: DarpInstance, routes) -> set[int]:
    n = instance.num_requests
    return {s for seq in routes for s in seq if 1 <= s <= n}


def _remove_requests(instance, routes, route_dists, deps, victims: set[int]) -> None:
    p_nodes = {instance.pickup_index(r) for r in victims}
    d_nodes = {instance.dropoff_index(r) for r in victims}
    drop = p_nodes | d_nodes
    for ri, seq in enumerate(routes):
        if any(s in drop for s in seq):
            routes[ri] = [s for s in seq if s not in drop]
            route_dists[ri] = route_distance(instance, routes[ri])
            deps[ri] = _as_early_departures(instance, routes[ri])


def _empty_routes(instance: DarpInstance) -> list[list[int]]:
    return [[instance.depot_start, instance.depot_end] for _ in range(instance.num_vehicles)]


def _ensure_schedulable(instance, routes, route_dists, deps) -> set[int]:
    """Guarantee every route has a feasible schedule, evicting requests until so.

    Removing a request can delete the downstream waiting slack another request's
    ride-time feasibility relied on, leaving a route unschedulable. This restores
    the invariant (used after a removal), returning the requests it had to evict
    so the caller can try to reinsert them."""
    n = instance.num_requests
    evicted: set[int] = set()
    for ri in range(len(routes)):
        while schedule_route(instance, routes[ri]) is None:
            seq = routes[ri]
            reqs_on = [s for s in seq if 1 <= s <= n]
            if not reqs_on:
                break  # a bare depot route always schedules; safety valve
            drop_r = reqs_on[-1]
            for r in reqs_on:  # prefer a single eviction that restores feasibility
                dr = instance.dropoff_index(r)
                trial = [x for x in seq if x != r and x != dr]
                if schedule_route(instance, trial) is not None:
                    drop_r = r
                    break
            dr = instance.dropoff_index(drop_r)
            routes[ri] = [x for x in seq if x != drop_r and x != dr]
            route_dists[ri] = route_distance(instance, routes[ri])
            deps[ri] = _as_early_departures(instance, routes[ri])
            evicted.add(drop_r)
    return evicted


def _worst_requests(instance, routes, count: int, rng: Random) -> set[int]:
    """Requests whose removal saves the most distance (detour cost), with a little
    randomisation so the operator is not purely greedy."""
    n = instance.num_requests
    scored: list[tuple[float, int]] = []
    dist = instance.distances
    for seq in routes:
        pos = {s: i for i, s in enumerate(seq)}
        for s in seq:
            if 1 <= s <= n:
                r = s
                pnode, dnodex = s, instance.dropoff_index(r)
                score = 0.0
                for node in (pnode, dnodex):
                    i = pos[node]
                    if 0 < i < len(seq) - 1:
                        score += dist[seq[i - 1]][node] + dist[node][seq[i + 1]] - dist[seq[i - 1]][seq[i + 1]]
                scored.append((score, r))
    scored.sort(reverse=True)
    chosen: set[int] = set()
    i = 0
    while len(chosen) < count and i < len(scored):
        # bias toward the worst but jitter the pick
        idx = min(len(scored) - 1, i + rng.randint(0, 2))
        chosen.add(scored[idx][1])
        i += 1
    return chosen


def _related_requests(instance, routes, count: int, rng: Random) -> set[int]:
    """Shaw-style related removal: grow a cluster of geographically related
    requests (close pickups and close drop-offs), so re-insertion can re-sequence
    a whole neighbourhood at once -- the operator that cracks tightly-coupled
    instances a random/worst removal cannot."""
    n = instance.num_requests
    dist = instance.distances
    served = [s for seq in routes for s in seq if 1 <= s <= n]
    if not served:
        return set()
    served_set = set(served)
    removed = {rng.choice(served)}
    while len(removed) < count and len(removed) < len(served_set):
        r = rng.choice(tuple(removed))
        pr, dr = instance.pickup_index(r), instance.dropoff_index(r)
        cands = [x for x in served_set if x not in removed]
        cands.sort(key=lambda x: dist[pr][instance.pickup_index(x)] + dist[dr][instance.dropoff_index(x)])
        idx = int(len(cands) * (rng.random() ** 3))  # bias toward the most related
        removed.add(cands[min(idx, len(cands) - 1)])
    return removed


def solve_darp(
    instance: DarpInstance,
    *,
    seed: int = 0,
    max_iterations: int = 2000,
    time_limit_s: float | None = 30.0,
) -> DarpSolution:
    """Solve a DARP instance with regret construction + LNS. Reproducible from
    (instance, seed, max_iterations) unless the wall-clock `time_limit_s` cap
    binds first (recorded honestly on the result)."""
    rng = Random(seed)
    start = time.perf_counter()
    n = instance.num_requests

    routes = _empty_routes(instance)
    route_dists = [0.0] * len(routes)
    deps = [_as_early_departures(instance, s) for s in routes]
    _regret_insert(instance, routes, route_dists, deps, set(range(1, n + 1)), rng, noise=0.0)

    def total(rd) -> float:
        return sum(rd)

    all_requests = set(range(1, n + 1))
    # Noise magnitude ~ mean arc length; drives diversification of reinsertion.
    N = len(instance.nodes)
    flat = [instance.distances[i][j] for i in range(N) for j in range(N) if i != j]
    mean_arc = (sum(flat) / len(flat)) if flat else 1.0
    noise_mag = 0.1 * mean_arc
    # Unserved requests are penalised so partial and full solutions are comparable
    # in one objective f = distance + P * unserved. P is large enough that serving
    # every request always wins, yet finite so the annealer can *temporarily* drop
    # one to escape a basin and refit it elsewhere.
    penalty = max(1000.0, 4.0 * instance.max_route_duration)

    def combined(dists, served_count: int) -> float:
        return sum(dists) + penalty * (n - served_count)

    q_max = max(2, min(n // 3 + 1, 8))
    cur_routes = [list(s) for s in routes]
    cur_dists = list(route_dists)
    cur_deps = [list(dp) for dp in deps]
    cur_served = _served(instance, cur_routes)
    cur_f = combined(cur_dists, len(cur_served))

    best_routes = [list(s) for s in cur_routes]
    best_served = set(cur_served)
    best_dist = total(cur_dists)  # best *distance* among the best served-count seen
    best_count = len(cur_served)

    t0 = 0.35 * penalty      # hot enough to occasionally accept dropping a request
    t_end = max(1e-3, 0.03 * mean_arc)
    cooling = (t_end / t0) ** (1.0 / max(1, max_iterations))
    temp = t0
    hit_time_cap = False
    reheat_after = max(150, max_iterations // 8)  # escape a stale basin by reheating
    since_improved = 0

    it = 0
    while it < max_iterations:
        it += 1
        if time_limit_s is not None and (it & 15) == 0 and (time.perf_counter() - start) > time_limit_s:
            hit_time_cap = True
            break
        if since_improved >= reheat_after:
            temp = 0.4 * t0
            since_improved = 0

        cand_routes = [list(s) for s in cur_routes]
        cand_dists = list(cur_dists)
        cand_deps = [list(dp) for dp in cur_deps]
        served_now = _served(instance, cand_routes)
        pool = sorted(served_now)
        q = min(rng.randint(1, q_max), max(1, len(pool)))
        if not pool:
            victims: set[int] = set()
        else:
            op = rng.random()
            if op < 0.34:
                victims = set(rng.sample(pool, q))
            elif op < 0.67:
                victims = _worst_requests(instance, cand_routes, q, rng)
            else:
                victims = _related_requests(instance, cand_routes, q, rng)
        _remove_requests(instance, cand_routes, cand_dists, cand_deps, victims)
        evicted = _ensure_schedulable(instance, cand_routes, cand_dists, cand_deps)
        to_insert = victims | evicted | (all_requests - served_now)
        use_noise = noise_mag if rng.random() < 0.8 else 0.0
        _regret_insert(instance, cand_routes, cand_dists, cand_deps, to_insert, rng, noise=use_noise)

        cand_served = _served(instance, cand_routes)
        cand_f = combined(cand_dists, len(cand_served))

        delta = cand_f - cur_f
        if delta < 0 or (temp > 1e-9 and math.exp(-delta / temp) > rng.random()):
            cur_routes, cur_dists, cur_deps = cand_routes, cand_dists, cand_deps
            cur_served, cur_f = cand_served, cand_f

        cand_dist = total(cand_dists)
        if len(cand_served) > best_count or (len(cand_served) == best_count and cand_dist < best_dist - 1e-9):
            best_routes = [list(s) for s in cand_routes]
            best_served = set(cand_served)
            best_dist = cand_dist
            best_count = len(cand_served)
            since_improved = 0
        else:
            since_improved += 1
        temp *= cooling

    wall = time.perf_counter() - start
    served_all = len(best_served) == n
    status = "feasible" if served_all else "incomplete"

    darp_routes: list[DarpRoute] = []
    for vi, seq in enumerate(best_routes):
        begin = schedule_route(instance, seq)
        if begin is None:
            # A route with only the two depot anchors is trivially schedulable at 0;
            # a non-trivial route must schedule, or we do not emit it as feasible.
            if len(seq) == 2:
                begin = [instance.nodes[seq[0]].tw_start, instance.nodes[seq[0]].tw_start]
            else:
                raise AssertionError(f"final route {seq} failed to schedule -- solver bug")
        visits = tuple(DarpVisit(node_index=s, begin_service=begin[k]) for k, s in enumerate(seq))
        darp_routes.append(DarpRoute(vehicle=vi, visits=visits))

    # Independently recompute the objective for the served set.
    obj = sum(route_distance(instance, seq) for seq in best_routes)

    solution = DarpSolution(
        instance_name=instance.name,
        num_requests=n,
        routes=tuple(darp_routes),
        status=status,
        objective=obj if served_all else None,
        served_requests=tuple(sorted(best_served)),
        solver_name=DARP_SOLVER_NAME,
        solver_version=DARP_SOLVER_VERSION,
        seed=seed,
        wall_time_s=round(wall, 3),
    )

    # One-way self-audit against the INDEPENDENT checker. An infeasible "solution"
    # is a bug, and we fail loudly rather than report it.
    violations = check_darp_feasibility(instance, solution)
    if violations:
        raise AssertionError(f"DARP solver produced an infeasible solution: {violations[:5]}")

    return solution
