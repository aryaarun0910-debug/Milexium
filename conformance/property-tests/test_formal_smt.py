"""Conformance tests for the z3-backed formal invariants (packet MX-G-FORMAL-SMT-002).

Skips cleanly on a machine without z3 (``importorskip`` at module load) so the
Python-only CI path stays green; the orchestrator wires ``z3-solver`` into CI so
these RUN there. Covers:

  * each invariant (S1..S4 state machine, H1 hash chain) actually proves via z3;
  * the spec-consistency checks pass (transcription == real contract);
  * two NEGATIVE controls that show the ties are load-bearing --
      1. flipping one transition in a copy of the transcription makes the
         consistency check FAIL (so drift between prover and code is caught);
      2. dropping the H-injectivity axiom makes H1 no longer ``unsat`` (so the
         collision-freeness axiom is doing the real work, honestly).
"""

from __future__ import annotations

import pytest

z3 = pytest.importorskip("z3")  # noqa: F841 - skip whole module when z3 is absent

from packages.verify import formal  # noqa: E402 - after importorskip, by design

state_machine_smt = formal.state_machine_smt
hash_chain_smt = formal.hash_chain_smt


# --- Each invariant proves via z3 -------------------------------------------

def test_terminal_sinks_proved() -> None:
    """S1: terminal states are sinks -- z3 unsat of the negation."""
    res = state_machine_smt.prove_terminal_sinks()
    assert res.proved, res.detail
    assert res.status == "unsat"


def test_irreflexive_proved() -> None:
    """S2: no self-loop -- z3 unsat of the negation."""
    res = state_machine_smt.prove_irreflexive()
    assert res.proved, res.detail
    assert res.status == "unsat"


def test_acyclic_proved() -> None:
    """S3: acyclic -- z3 unsat that any |States|-edge walk exists."""
    res = state_machine_smt.prove_acyclic()
    assert res.proved, res.detail
    assert res.status == "unsat"


def test_no_dead_end_proved() -> None:
    """S4: every non-terminal reaches a terminal -- z3 sat witness per source."""
    res = state_machine_smt.prove_no_dead_end()
    assert res.proved, res.detail
    assert res.status == "sat"


def test_tamper_evidence_proved() -> None:
    """H1: tamper-evidence relative to the injectivity axiom -- z3 unsat of the negation."""
    res = hash_chain_smt.prove_tamper_evidence()
    assert res.proved, res.detail
    assert res.status == "unsat"


def test_prove_all_reports_every_invariant_proved() -> None:
    results = formal.prove_all()
    expected = {
        "S1_terminal_sinks",
        "S2_irreflexive",
        "S3_acyclic",
        "S4_no_dead_end",
        "H1_tamper_evidence",
    }
    assert set(results) == expected
    assert all(r.proved for r in results.values()), {
        name: r.status for name, r in results.items()
    }


# --- Spec-consistency ties the independent proof to the real code -----------

def test_spec_consistency_transitions_passes() -> None:
    result = formal.check_spec_consistency()
    assert result.consistent, result.detail


def test_spec_consistency_terminals_passes() -> None:
    result = formal.check_terminal_consistency()
    assert result.consistent, result.detail


# --- Negative controls: the ties are load-bearing ---------------------------

def test_flipping_one_transition_fails_consistency() -> None:
    """Flip one transition in a COPY of the transcription -> consistency FAILS.

    Proves the equality check against SERVICE_REQUEST_TRANSITIONS is real: if
    the prover's transcription ever drifted from the code, this would catch it.
    """
    mutated = {
        state: set(targets)
        for state, targets in state_machine_smt.TRANSCRIBED_TRANSITIONS.items()
    }
    # "completed" is terminal in the real contract; make it (illegally) point
    # back to "requested" -- a single flipped edge.
    mutated["completed"] = {"requested"}

    result = formal.check_spec_consistency(mutated)
    assert not result.consistent
    assert "completed" in result.detail

    # And the un-mutated transcription still passes, so the flip is what broke it.
    assert formal.check_spec_consistency().consistent


def test_dropping_injectivity_axiom_breaks_tamper_evidence() -> None:
    """Drop the collision-freeness axiom -> H1 is no longer unsat.

    Documents (and enforces) that the tamper-evidence guarantee is proved
    RELATIVE TO H-injectivity: with the axiom the negation is unsat (proved);
    without it, z3 finds a model where two different chains share a final hash,
    so the theorem is refuted. The axiom is doing the real work -- honestly.
    """
    with_axiom = hash_chain_smt.prove_tamper_evidence(with_injectivity=True)
    without_axiom = hash_chain_smt.prove_tamper_evidence(with_injectivity=False)

    assert with_axiom.proved and with_axiom.status == "unsat"
    assert not without_axiom.proved
    assert without_axiom.status == "sat"
