"""Z3 model of the append-only hash chain and its tamper-evidence theorem.

Packet MX-G-FORMAL-SMT-002 (Phase-3 gate item G).

INDEPENDENCE (ADR-0028 / ADR-0003): the chain rule below is transcribed BY HAND
from ADR-0003 -- the append-only, hash-chained event log. It does NOT import
``app.canonical.events``. The rule modelled here is:

    hash[0]  = H(NIL, content[0])          # genesis: prev_hash at index 0 is NIL
    hash[k]  = H(hash[k-1], content[k])     # every later link chains the prior hash

(The real ``compute_hash`` also folds in ``sequence``, ``aggregate_id`` and
``idempotency_key``; for a single fixed aggregate those are determined by the
index/position, so the load-bearing recurrence is prev-hash + content, which is
what the theorem needs.)

HONEST SCOPE -- read this before trusting the theorem:

``H`` is an UNINTERPRETED function together with ONE explicit axiom, injectivity
(collision-freeness):

    H(p1, c1) == H(p2, c2)  =>  p1 == p2  AND  c1 == c2

The tamper-evidence theorem H1 is proved *RELATIVE TO* this axiom. It does NOT
prove SHA-256 collision resistance. It proves the conditional: IF the hash is
collision-free, THEN a valid chain's content is uniquely pinned by its genesis,
its length and its final hash -- so you cannot alter any ``content[k]`` and
still reproduce the published final hash. Dropping the injectivity axiom makes
the theorem's negation satisfiable again (see the negative control in
``app/verify/formal.py`` / the conformance test), which is the honest
statement that the whole guarantee rests on the collision-freeness assumption.
"""

from __future__ import annotations

from dataclasses import dataclass

import z3


@dataclass(frozen=True)
class ProofResult:
    """The tamper-evidence theorem's z3 verdict. `proved` is the solver's, not asserted."""

    name: str
    status: str  # "unsat" | "sat" | "unknown"
    proved: bool
    detail: str


def _chain_hashes(H, nil, contents):
    """Hashes for one chain: hash[0]=H(NIL,c0); hash[k]=H(hash[k-1],ck)."""
    hashes = []
    prev = nil
    for c in contents:
        prev = H(prev, c)
        hashes.append(prev)
    return hashes


def prove_tamper_evidence(length: int = 6, with_injectivity: bool = True) -> ProofResult:
    """H1: chain determinism / tamper-evidence, proved by z3 ``unsat`` of the negation.

    Sets up two chains A and B of equal ``length`` sharing the same genesis
    (both start from the distinguished ``NIL`` prev-hash). Asserts they share
    the same final hash, then asserts (the negation of the theorem) that their
    content differs at some index. Under the injectivity axiom this is ``unsat``
    -- i.e. equal genesis + equal final hash forces identical content at every
    index. With ``with_injectivity=False`` the same query is ``sat`` (H is free
    to collide), which is the documented negative control.
    """
    # Own context per call so repeated calls (e.g. axiom-on then axiom-off in
    # the negative control) stay fully isolated from each other.
    ctx = z3.Context()
    Hashv = z3.DeclareSort("Hashv", ctx)
    Content = z3.DeclareSort("Content", ctx)
    H = z3.Function("H", Hashv, Content, Hashv)
    NIL = z3.Const("NIL", Hashv)

    solver = z3.Solver(ctx=ctx)

    if with_injectivity:
        p1, p2 = z3.Consts("p1 p2", Hashv)
        c1, c2 = z3.Consts("c1 c2", Content)
        solver.add(
            z3.ForAll(
                [p1, c1, p2, c2],
                z3.Implies(H(p1, c1) == H(p2, c2), z3.And(p1 == p2, c1 == c2)),
            )
        )

    ca = [z3.Const(f"ca{i}", Content) for i in range(length)]
    cb = [z3.Const(f"cb{i}", Content) for i in range(length)]
    ha = _chain_hashes(H, NIL, ca)
    hb = _chain_hashes(H, NIL, cb)

    # Same genesis (both start at NIL, by construction) and same final hash.
    solver.add(ha[-1] == hb[-1])
    # Negation of the theorem: the two chains differ in content somewhere.
    solver.add(z3.Or(*[ca[i] != cb[i] for i in range(length)]))

    res = solver.check()
    detail = (
        f"length={length}, injectivity_axiom={'ON' if with_injectivity else 'OFF'}; "
        f"z3 returned {res} for the negation "
        f"(unsat => content is uniquely pinned by genesis + length + final hash)"
    )
    return ProofResult("H1_tamper_evidence", str(res), res == z3.unsat, detail)


if __name__ == "__main__":  # pragma: no cover - manual debugging aid
    r = prove_tamper_evidence()
    verdict = "PROVED" if r.proved else "REFUTED"
    print(f"[{verdict:7}] {r.name:18} z3={r.status:8} {r.detail}")
    off = prove_tamper_evidence(with_injectivity=False)
    print(f"[control] axiom OFF -> z3={off.status} (expected sat: theorem no longer holds)")
