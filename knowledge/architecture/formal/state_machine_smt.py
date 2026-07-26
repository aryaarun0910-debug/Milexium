"""Z3 model of the ServiceRequest lifecycle state machine.

Packet MX-G-FORMAL-SMT-002 (Phase-3 gate item G).

INDEPENDENCE (ADR-0028): the transition table below is transcribed BY HAND
from the normative spec (knowledge/docs/MASTER_ROADMAP.md `decision_events` lifecycle,
ADR-0003, blueprint Program A "domain state machines and idempotent
commands"). It deliberately does NOT import
``app.canonical.state_machine`` -- the prover reasons over its OWN copy of
the contract. A *separate* consistency check in ``app/verify/formal.py``
asserts this transcription equals the code's ``SERVICE_REQUEST_TRANSITIONS``
exactly, so drift on either side fails loudly without the prover ever importing
the code it reasons about.

The four invariants are discharged by z3 -- each result is a solver verdict,
never a Python ``assert``:

  * S1 terminal sinks   -- z3 ``unsat`` of "a terminal state has an outgoing edge"
  * S2 irreflexive      -- z3 ``unsat`` of "some state has a self-loop"
  * S3 acyclic          -- z3 ``unsat`` of "a walk of |States| edges exists"
                           (a DAG on n nodes has no walk with >= n edges, so this
                           is exactly the negation of acyclicity)
  * S4 no dead-end      -- z3 ``sat``: a witnessing path to a terminal for every
                           non-terminal source (a constructive certificate; the
                           Edge relation is pinned to the real table, so any
                           model is a genuine path)
"""

from __future__ import annotations

from dataclasses import dataclass

import z3

# --- Independent transcription of the spec (NOT imported from the code) ------
#
# ServiceRequest lifecycle, transcribed from ADR-0003 / MASTER_ROADMAP. State
# names are the enum *values* ("requested", ...) so the runner's consistency
# check can compare directly against `ServiceRequestState.value`.

TRANSCRIBED_TRANSITIONS: dict[str, frozenset[str]] = {
    "requested": frozenset({"negotiated", "denied", "cancelled"}),
    "negotiated": frozenset({"scheduled", "denied", "cancelled"}),
    "scheduled": frozenset({"in_progress", "cancelled", "no_show"}),
    "in_progress": frozenset({"completed"}),
    "completed": frozenset(),
    "denied": frozenset(),
    "cancelled": frozenset(),
    "no_show": frozenset(),
}

# Transcribed independently as well (states the spec calls terminal). The runner
# also ties this to the code's empty-out-set states, so it can't silently drift.
TRANSCRIBED_TERMINALS: frozenset[str] = frozenset(
    {"completed", "denied", "cancelled", "no_show"}
)


@dataclass(frozen=True)
class ProofResult:
    """One invariant's z3 verdict. `proved` is derived from the solver, not asserted."""

    name: str
    status: str  # "unsat" | "sat" | "unknown"
    proved: bool
    detail: str


def _build_edge_relation(transitions: dict[str, frozenset[str]] | None = None):
    """Build a z3 enum sort for the states and a fully-pinned `Edge` relation.

    Returns ``(ctx, State, by_name, Edge, facts)`` where ``facts`` asserts
    ``Edge(s, t)`` for every allowed transition and ``Not(Edge(s, t))`` for
    every disallowed one -- so `Edge` is a total, concrete relation. Any model
    z3 finds therefore corresponds to a real transition in the transcription.

    Each call gets its OWN ``z3.Context`` so the four proofs are fully isolated
    (z3's global context rejects re-declaring the ``State`` enum sort, and
    isolation keeps repeated calls -- e.g. from the test suite -- independent).
    """
    transitions = transitions or TRANSCRIBED_TRANSITIONS
    names = sorted(transitions)
    ctx = z3.Context()
    State, consts = z3.EnumSort("State", names, ctx=ctx)
    by_name = dict(zip(names, consts))
    Edge = z3.Function("Edge", State, State, z3.BoolSort(ctx))
    facts = []
    for src in names:
        allowed = transitions[src]
        for dst in names:
            atom = Edge(by_name[src], by_name[dst])
            facts.append(atom if dst in allowed else z3.Not(atom))
    return ctx, State, by_name, Edge, facts


def _is_terminal(x, by_name):
    return z3.Or(*[x == by_name[t] for t in sorted(TRANSCRIBED_TERMINALS)])


def prove_terminal_sinks() -> ProofResult:
    """S1: no terminal state has an outgoing transition (terminals are sinks)."""
    ctx, State, by_name, Edge, facts = _build_edge_relation()
    solver = z3.Solver(ctx=ctx)
    solver.add(*facts)
    src = z3.Const("src", State)
    dst = z3.Const("dst", State)
    # Negation: some terminal `src` has an edge to some `dst`.
    solver.add(_is_terminal(src, by_name))
    solver.add(Edge(src, dst))
    res = solver.check()
    return ProofResult(
        "S1_terminal_sinks",
        str(res),
        res == z3.unsat,
        "unsat => no terminal (completed/denied/cancelled/no_show) has any outgoing edge",
    )


def prove_irreflexive() -> ProofResult:
    """S2: no self-loop (the idempotency property `check_transition` relies on)."""
    ctx, State, by_name, Edge, facts = _build_edge_relation()
    solver = z3.Solver(ctx=ctx)
    solver.add(*facts)
    s = z3.Const("s", State)
    # Negation: some state has a self-loop.
    solver.add(Edge(s, s))
    res = solver.check()
    return ProofResult(
        "S2_irreflexive",
        str(res),
        res == z3.unsat,
        "unsat => no state s allows s -> s, so a replayed command cannot re-apply a transition",
    )


def prove_acyclic() -> ProofResult:
    """S3: acyclic -- no state reaches itself via >= 1 transitions.

    A directed graph on ``n`` nodes is acyclic iff it has no walk using ``n``
    edges: a DAG's walks are simple (a repeated node would be a cycle), so the
    longest walk has <= n-1 edges; a cyclic graph admits arbitrarily long walks
    (loop around the cycle). So "there exists a walk of exactly ``n`` edges" is
    precisely the negation of acyclicity -- z3 ``unsat`` proves S3.
    """
    ctx, State, by_name, Edge, facts = _build_edge_relation()
    n = len(TRANSCRIBED_TRANSITIONS)  # number of states
    solver = z3.Solver(ctx=ctx)
    solver.add(*facts)
    nodes = [z3.Const(f"p{i}", State) for i in range(n + 1)]  # n edges, n+1 nodes
    for i in range(n):
        solver.add(Edge(nodes[i], nodes[i + 1]))
    res = solver.check()
    return ProofResult(
        "S3_acyclic",
        str(res),
        res == z3.unsat,
        f"unsat => no walk of {n} edges exists, so no state reaches itself (no replay loop)",
    )


def prove_no_dead_end() -> ProofResult:
    """S4: every non-terminal state can reach some terminal state.

    For each non-terminal source, z3 is asked for a bounded walk (<= n-1 edges)
    that ends in a terminal state. A ``sat`` verdict yields an explicit witness
    path; because `Edge` and the terminal predicate are pinned to the real
    transcription, that path is genuine. S4 holds iff every non-terminal source
    is ``sat``. A dead-end would show up as ``unsat`` for that source.
    """
    ctx, State, by_name, Edge, facts = _build_edge_relation()
    names = sorted(TRANSCRIBED_TRANSITIONS)
    nonterminals = [nm for nm in names if nm not in TRANSCRIBED_TERMINALS]
    k = len(names) - 1  # a reachable terminal is reachable by a simple path <= n-1 edges
    per_source: dict[str, str] = {}
    all_reach = True
    for source in nonterminals:
        solver = z3.Solver(ctx=ctx)
        solver.add(*facts)
        nodes = [z3.Const(f"n{i}", State) for i in range(k + 1)]
        solver.add(nodes[0] == by_name[source])
        for i in range(k):
            # Either take a real edge, or -- once at a terminal -- stall there.
            solver.add(
                z3.Or(
                    Edge(nodes[i], nodes[i + 1]),
                    z3.And(_is_terminal(nodes[i], by_name), nodes[i + 1] == nodes[i]),
                )
            )
        solver.add(_is_terminal(nodes[k], by_name))  # the walk ends terminal
        res = solver.check()
        per_source[source] = str(res)
        if res != z3.sat:
            all_reach = False
    status = "sat" if all_reach else "unsat/unknown"
    return ProofResult(
        "S4_no_dead_end",
        status,
        all_reach,
        f"sat for every non-terminal source => each reaches a terminal; per-source={per_source}",
    )


def prove_state_invariants() -> list[ProofResult]:
    """Run S1..S4 and return their z3 verdicts, in order."""
    return [
        prove_terminal_sinks(),
        prove_irreflexive(),
        prove_acyclic(),
        prove_no_dead_end(),
    ]


if __name__ == "__main__":  # pragma: no cover - manual debugging aid
    for r in prove_state_invariants():
        verdict = "PROVED" if r.proved else "REFUTED"
        print(f"[{verdict:7}] {r.name:18} z3={r.status:8} {r.detail}")
