# Formal invariants (z3-backed)

Machine-checked proofs of two load-bearing Milexium properties, discharged with
the free [z3](https://github.com/Z3Prover/z3) SMT solver. Packet
**MX-G-FORMAL-SMT-002** (Phase-3 gate item G).

Every result here is a **z3 solver verdict**, not a Python `assert`: a property
is "proved" because z3 returned `unsat` on its negation (or `sat` on a
constructive witness), never because a test hard-coded the answer.

## What is proved

### State machine — `state_machine_smt.py`

A z3 model of the `ServiceRequest` lifecycle (8 states; terminals COMPLETED,
DENIED, CANCELLED, NO_SHOW). The transition relation is pinned to a concrete
table, and four invariants are discharged:

| ID | Property | How z3 proves it |
|----|----------|------------------|
| **S1** | Terminal states are sinks (no outgoing transition) | `unsat` of "a terminal has an outgoing edge" |
| **S2** | Irreflexive — no self-loop (the idempotency property `check_transition` relies on) | `unsat` of "some state has a self-loop" |
| **S3** | Acyclic — no state reaches itself via ≥1 transitions (strict lifecycle progression, no replay loop) | `unsat` that a walk of `|States|` edges exists — a DAG on *n* nodes has no walk with ≥ *n* edges, so this is exactly the negation of acyclicity |
| **S4** | No non-terminal dead-end — every non-terminal reaches some terminal | `sat`: z3 returns a witnessing path to a terminal for **every** non-terminal source (a constructive certificate; the `Edge` relation is pinned to the real table, so any model is a genuine path) |

### Hash chain — `hash_chain_smt.py`

A z3 model of the append-only, hash-chained event log (ADR-0003). The chain rule
is transcribed as `hash[0] = H(NIL, content[0])`,
`hash[k] = H(hash[k-1], content[k])`.

| ID | Property | How z3 proves it |
|----|----------|------------------|
| **H1** | Tamper-evidence / chain determinism: two valid chains of equal length, same genesis (`prev_hash = NIL` at index 0) and same final hash have identical content at every index — you cannot alter any `content[k]` and still match the published final hash | `unsat` of the negation ("same final hash but content differs somewhere"), bounded length 6 |

## Independence design (ADR-0028)

The moat is verifiability, so the prover must not mark its own homework:

- **The prover modules transcribe the spec by hand.** `state_machine_smt.py`
  and `hash_chain_smt.py` contain their *own* copy of the transition table /
  chain rule, transcribed from the ADRs and `MASTER_ROADMAP`. They **do not
  import** `app.canonical.state_machine` or `app.canonical.events` —
  they reason over their own transcription.
- **A separate consistency test ties that transcription to the real code.**
  `app/verify/formal.py` (the runner, not the prover) is the *only* place
  that imports the code table, and only to assert
  `TRANSCRIBED_TRANSITIONS == SERVICE_REQUEST_TRANSITIONS` (and the terminal set)
  **exactly**. If either side drifts, that check fails loudly.

This gives both halves of the guarantee: the proof is about an independent
model (so a shared bug in the generator can't hide inside it), *and* the model
is provably the same as the code that ships (so the proof isn't about some
unrelated toy machine). The conformance suite includes a negative control that
flips one transition in a copy of the transcription and confirms the
consistency check then fails — i.e. the tie is load-bearing.

## Honest scope — the hash-chain axiom

H1 is proved **relative to an explicit collision-freeness axiom**: `H` is an
**uninterpreted** function plus the injectivity axiom

```
H(p1, c1) == H(p2, c2)  =>  p1 == p2  AND  c1 == c2
```

This **does not prove SHA-256 collision resistance.** It proves the conditional:
*if* the hash is collision-free, *then* a valid chain's content is uniquely
pinned by its genesis, length and final hash. The security of the real chain
still rests on SHA-256's collision resistance as a cryptographic assumption —
exactly as ADR-0003 states the mechanism is "tamper-evident, not immutable and
not a compliance certificate."

The conformance suite makes this honest and checkable with a second negative
control: **dropping the injectivity axiom makes H1's negation satisfiable
again** (z3 returns `sat` — it finds two different chains sharing a final hash).
That demonstrates the axiom is doing the real work, and the guarantee is not
free.

## Running

```bash
# print each invariant + z3 verdict and the spec-consistency checks
py -3 -m app.verify.formal

# the conformance tests (skip cleanly if z3 is not installed)
py -3 -m pytest evidence/conformance/property-tests/test_formal_smt.py -q
```

## Files

- `state_machine_smt.py` — z3 model + S1..S4 proofs (independent transcription)
- `hash_chain_smt.py` — z3 model + H1 tamper-evidence theorem (uninterpreted `H` + injectivity axiom)
- `../../../app/verify/formal.py` — thin runner: `prove_all()` + the spec-consistency checks (the only place the code table is imported)
- `../../../evidence/conformance/property-tests/test_formal_smt.py` — conformance tests, including the two negative controls
