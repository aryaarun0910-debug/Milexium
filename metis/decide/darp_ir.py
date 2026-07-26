"""DARP benchmark IR (Program F, v0.2 -- additive routing extension).

The v0.1 Decision IR (`metis.decide.ir`) models a single-leg paratransit
*assignment* problem: each request has a fixed nominal ride time and the only
degree of freedom is the pickup instant. That IR is intentionally not a vehicle
router -- it has no travel-time matrix, no depot, and no notion of a vehicle
visiting a *sequence* of stops. It cannot represent a published dial-a-ride
benchmark instance, and it is left completely untouched here.

This module adds, alongside it, the vocabulary needed to represent a standard
Cordeau/Ropke dial-a-ride problem (DARP) instance and a *routed* solution:

- `DarpNode` -- a depot or a request node (pickup / drop-off) with coordinates,
  a service duration, a signed load (+q at a pickup, -q at its drop-off), and a
  time window.
- `DarpInstance` -- K vehicles from one depot, n requests (nodes 1..n are
  pickups, nodes n+1..2n the paired drop-offs, nodes 0 and 2n+1 the depot),
  a vehicle capacity Q, a maximum ride time L, a maximum route duration T, and
  a precomputed Euclidean travel-time/distance matrix. In the classic instances
  travel time between two nodes equals the Euclidean distance between them, and
  the objective is total routing distance.
- `DarpVisit` / `DarpRoute` / `DarpSolution` -- a *fully scheduled* answer: each
  route is an ordered list of visits, and every visit carries a concrete
  begin-service time. Committing to concrete times (rather than only a node
  order) is deliberate: it lets the INDEPENDENT feasibility checker
  (`metis.decide.feasibility.check_darp_feasibility`) verify every hard
  constraint directly from the raw instance, re-deriving nothing from the
  solver's scheduling logic.

Design note: unlike the pydantic v0.1 IR, these are frozen dataclasses. A DARP
instance carries a dense (2n+2)x(2n+2) float distance matrix; a plain frozen
dataclass keeps that cheap and lets us precompute the matrix once at load time.
The module is data only -- no solving, no checking, no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class DarpNode:
    """One vertex of a DARP instance.

    `load` is signed: +q at a pickup, -q at the paired drop-off, 0 at the depot.
    Times (`service_duration`, `tw_start`, `tw_end`) are in minutes; coordinates
    are in the instance's distance units.
    """

    node_id: int
    x: float
    y: float
    service_duration: float
    load: int
    tw_start: float
    tw_end: float


@dataclass(frozen=True)
class DarpInstance:
    """A single-depot dial-a-ride instance.

    Node indexing follows the standard convention: index 0 is the start depot,
    indices 1..n are request pickups, indices n+1..2n are the paired drop-offs
    (request r's drop-off is node n+r), and index 2n+1 is the (identical) end
    depot. `distances[i][j]` is the Euclidean distance between nodes i and j,
    which is also the travel time between them.
    """

    name: str
    num_vehicles: int
    num_requests: int
    max_route_duration: float
    vehicle_capacity: int
    max_ride_time: float
    nodes: tuple[DarpNode, ...]
    distances: tuple[tuple[float, ...], ...]

    # --- indexing helpers -------------------------------------------------
    @property
    def depot_start(self) -> int:
        return 0

    @property
    def depot_end(self) -> int:
        return 2 * self.num_requests + 1

    def pickup_index(self, request: int) -> int:
        """Node index of request r's pickup (r in 1..n)."""
        return request

    def dropoff_index(self, request: int) -> int:
        """Node index of request r's drop-off (r in 1..n)."""
        return self.num_requests + request

    def is_pickup(self, node_index: int) -> bool:
        return 1 <= node_index <= self.num_requests

    def is_dropoff(self, node_index: int) -> bool:
        return self.num_requests + 1 <= node_index <= 2 * self.num_requests

    def request_of(self, node_index: int) -> int:
        """The request id (1..n) a pickup/drop-off node belongs to. Raises for a
        depot node, which belongs to no request."""
        if self.is_pickup(node_index):
            return node_index
        if self.is_dropoff(node_index):
            return node_index - self.num_requests
        raise ValueError(f"node {node_index} is a depot, not a request node")

    def dist(self, i: int, j: int) -> float:
        return self.distances[i][j]

    @classmethod
    def build(
        cls,
        *,
        name: str,
        num_vehicles: int,
        num_requests: int,
        max_route_duration: float,
        vehicle_capacity: int,
        max_ride_time: float,
        nodes: Iterable[DarpNode],
    ) -> "DarpInstance":
        """Construct an instance, precomputing the Euclidean distance matrix.

        Validates the structural invariants a Cordeau-format instance must hold
        (2n+2 nodes, depot loads zero, paired pickup/drop-off loads that cancel)
        so a malformed file fails loudly at load time, not deep inside a solver.
        """
        node_tuple = tuple(nodes)
        expected = 2 * num_requests + 2
        if len(node_tuple) != expected:
            raise ValueError(
                f"{name}: expected {expected} nodes for n={num_requests} "
                f"(depot + 2n + depot), got {len(node_tuple)}"
            )
        coords = [(nd.x, nd.y) for nd in node_tuple]
        matrix = tuple(
            tuple(math.hypot(ax - bx, ay - by) for (bx, by) in coords)
            for (ax, ay) in coords
        )
        inst = cls(
            name=name,
            num_vehicles=num_vehicles,
            num_requests=num_requests,
            max_route_duration=float(max_route_duration),
            vehicle_capacity=vehicle_capacity,
            max_ride_time=float(max_ride_time),
            nodes=node_tuple,
            distances=matrix,
        )
        inst._validate()
        return inst

    def _validate(self) -> None:
        n = self.num_requests
        if self.nodes[self.depot_start].load != 0 or self.nodes[self.depot_end].load != 0:
            raise ValueError(f"{self.name}: depot nodes must carry zero load")
        for r in range(1, n + 1):
            p = self.nodes[self.pickup_index(r)]
            d = self.nodes[self.dropoff_index(r)]
            if p.load <= 0:
                raise ValueError(f"{self.name}: pickup node {p.node_id} must carry positive load")
            if p.load + d.load != 0:
                raise ValueError(
                    f"{self.name}: request {r} pickup load {p.load} and drop-off load "
                    f"{d.load} do not cancel"
                )


@dataclass(frozen=True)
class DarpVisit:
    """A single stop on a route: which node, and the concrete begin-of-service
    time the solver committed to (minutes)."""

    node_index: int
    begin_service: float


@dataclass(frozen=True)
class DarpRoute:
    """One vehicle's ordered itinerary. By construction the first and last visit
    are the depot; the checker verifies that rather than trusting it."""

    vehicle: int
    visits: tuple[DarpVisit, ...]

    def node_sequence(self) -> tuple[int, ...]:
        return tuple(v.node_index for v in self.visits)


@dataclass(frozen=True)
class DarpSolution:
    """A routed, scheduled answer to a `DarpInstance`.

    `objective` is the solver's reported total routing distance; the independent
    checker recomputes it from the routes and refuses to trust a mismatch.
    `status` is an honest label ("feasible" for a heuristic result -- never
    "optimal", since this heuristic proves nothing). `served_requests` is
    informational; the checker derives the true served set from the routes.
    """

    instance_name: str
    num_requests: int
    routes: tuple[DarpRoute, ...]
    status: str
    objective: float | None
    served_requests: tuple[int, ...]
    solver_name: str
    solver_version: str
    seed: int
    wall_time_s: float | None = None

    def to_record(self) -> dict:
        """A JSON-serialisable summary (routes as node-id/time pairs)."""
        return {
            "instance_name": self.instance_name,
            "num_requests": self.num_requests,
            "status": self.status,
            "objective": self.objective,
            "served_requests": list(self.served_requests),
            "solver_name": self.solver_name,
            "solver_version": self.solver_version,
            "seed": self.seed,
            "wall_time_s": self.wall_time_s,
            "routes": [
                {
                    "vehicle": r.vehicle,
                    "visits": [[v.node_index, v.begin_service] for v in r.visits],
                }
                for r in self.routes
            ],
        }
