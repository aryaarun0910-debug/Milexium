# ADR-0033: Machine-checked formal invariants (z3/SMT) on load-bearing properties

- **Status:** Accepted
- **Date:** 2026-07-24
- **Packet:** MX-G-FORMAL-SMT-002 (Phase-3 gate item G)

## Context

Program G (Verify/formal) had, until now, only *plain-Python* verifiers
(`packages/verify/` hash-chain / schema / state checkers) — a manual precursor
to formal methods, explicitly **not** formal verification (IMPLEMENTATION_STATUS
blocker #5). Phase 3's G gate calls for 1–2 genuinely machine-checked invariants
on a load-bearing property. The free `z3-solver` pip package (z3 5.0.0) is the
lowest-friction path and is now installed.

The founder's constraint was explicit: **do not fake a proof.** Every result
must be a solver verdict, not a Python `assert` dressed up as a theorem.

## Decision

Two SMT models under `architecture/formal/`, discharged by z3, with a thin
runner `packages/verify/formal.py` and conformance tests.

**State machine (`state_machine_smt.py`) — four invariants on the
ServiceRequest lifecycle**, over a fully-pinned `Edge` relation (every
allowed transition asserted `Edge(s,t)`, every disallowed one `Not(Edge(s,t))`):

- **S1 terminal sinks** — z3 `unsat` of "a terminal has an outgoing edge".
- **S2 irreflexive** — z3 `unsat` of "some state has a self-loop" (the
  idempotency property `check_transition` relies on).
- **S3 acyclic** — z3 `unsat` that a walk of `|States|`(=8) edges exists. A
  directed graph on `n` nodes is acyclic iff it has no `n`-edge walk (a repeated
  node would be a cycle admitting arbitrarily long walks), so this query is
  exactly the negation of acyclicity — the lifecycle is a strict progression
  with no replay loop.
- **S4 no dead-end** — z3 `sat`: a constructive witness path to a terminal for
  every non-terminal source (`Edge` and the terminal predicate pinned to the
  real table, so each model is a genuine path).

**Hash chain (`hash_chain_smt.py`) — one invariant, honestly scoped:**

- **H1 tamper-evidence / chain determinism** — `hash` modelled as an
  **uninterpreted** function `H` with ONE explicit axiom, injectivity
  (`H(p1,c1)==H(p2,c2) ⟹ p1==p2 ∧ c1==c2`). Two chains of equal length sharing
  the NIL genesis and the same final hash are asserted to differ in content
  somewhere (the theorem's negation); z3 returns `unsat` at bounded length 6.
  I.e. **you cannot alter any `content[k]` and still reproduce the published
  final hash.** This is proved *relative to* the collision-freeness axiom and
  does **not** claim to prove SHA-256 collision resistance — the honest
  conditional "if H is collision-free, then a valid chain's content is uniquely
  pinned by genesis + length + final hash." A negative control drops the axiom
  and shows the negation becomes `sat`, making the dependency checkable.

**Independence (ADR-0028).** The prover modules transcribe the transition table
/ chain rule **by hand from the ADRs** and never import `packages.canonical`
(confirmed: the only mentions are in docstrings). Only the runner's
`check_spec_consistency()` / `check_terminal_consistency()` import the code's
`SERVICE_REQUEST_TRANSITIONS` — a single, runner-local *differential* seam that
asserts transcription == code, so drift on either side fails loudly without the
prover ever importing the code it reasons about (the same stance as the Rust
differential parity tests). A negative control flips one transition in a copy of
the transcription and confirms the consistency check then FAILS.

## Consequences

- **10 conformance tests** (`conformance/property-tests/test_formal_smt.py`),
  each asserting the exact z3 status (`unsat` for S1–S3/H1, `sat` for S4) plus
  both spec-consistency checks and the two load-bearing negative controls.
  `py -3 -m packages.verify.formal` prints each verdict and `RESULT: ALL GREEN`.
- The test `importorskip`s z3 so a machine without it skips cleanly; the CI
  Python job installs the new `.[formal]` extra (`z3-solver==5.0.0.0`) so the
  proofs **RUN on CI**, not skip.
- **Program G moves from "plain-Python precursor" to "machine-checked
  invariants exist"** — blocker #5 is partially cleared: two load-bearing
  properties (lifecycle safety, tamper-evidence) are now formally verified, the
  verifier stays independent of the generator, and no proof is faked.
- **Honest limits:** models are bounded (8 states; chain length 6 — sufficient
  for these decidable/uninterpreted-function queries). H1's guarantee is
  conditional on the injectivity axiom. The real `compute_hash` also folds in
  `sequence`/`aggregate_id`/`idempotency_key`; for a single fixed aggregate
  those are position-determined, so the modelled prev-hash+content recurrence is
  the load-bearing core. This is a first formal slice, not a full TLA+/Lean
  specification of the whole system.
