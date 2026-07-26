"""Program G: formal-methods runner (packet MX-G-FORMAL-SMT-002).

A thin runner over the z3 prover modules in ``forge/knowledge/architecture/formal/``. Two jobs:

1. ``prove_all()`` -- run every machine-checked invariant (S1..S4 on the
   ServiceRequest state machine, H1 on the append-only hash chain) and collect
   the per-invariant z3 verdict.
2. ``check_spec_consistency()`` -- assert the prover's INDEPENDENT transcription
   of the transition table equals the code's ``SERVICE_REQUEST_TRANSITIONS``
   exactly (and ``check_terminal_consistency()`` for the terminal set).

INDEPENDENCE (ADR-0028): the PROVER modules never import
``themis.canonical``. Only THIS runner imports the code table, and only for
the consistency check -- so the proofs stay independent of the code they
reason about, while a loud, separate equality test still ties them to the real
contract. Flip one transition on either side and the consistency check fails.

The prover modules live under ``forge/knowledge/architecture/formal/`` (a docs tree, not a
Python package), so they are loaded here by file path -- no ``__init__.py`` is
added to that tree.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FORMAL_DIR = _REPO_ROOT / "forge" / "knowledge" / "architecture" / "formal"


def _load(module_name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, _FORMAL_DIR / filename)
    if spec is None or spec.loader is None:  # pragma: no cover - only on a broken checkout
        raise ImportError(f"cannot load prover module {filename} from {_FORMAL_DIR}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses can resolve the module's string
    # annotations (`from __future__ import annotations`) via sys.modules.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


state_machine_smt = _load("architecture_formal_state_machine_smt", "state_machine_smt.py")
hash_chain_smt = _load("architecture_formal_hash_chain_smt", "hash_chain_smt.py")


@dataclass(frozen=True)
class ConsistencyResult:
    """Whether the prover's transcription still matches the code contract."""

    consistent: bool
    detail: str


def prove_all() -> dict[str, object]:
    """Run every formal invariant; return ``name -> ProofResult`` (with `.proved`
    and `.status` from z3)."""
    results: dict[str, object] = {}
    for res in state_machine_smt.prove_state_invariants():
        results[res.name] = res
    h1 = hash_chain_smt.prove_tamper_evidence()
    results[h1.name] = h1
    return results


def _code_transitions_as_strings() -> dict[str, frozenset[str]]:
    """The code's transition table, keyed/valued by enum *value* strings.

    Imported HERE, on the runner side, ONLY -- the prover modules must not do
    this (ADR-0028). This is the one seam that ties the independent proof to the
    real code.
    """
    from themis.canonical.state_machine import (  # noqa: PLC0415 - deliberately runner-local
        SERVICE_REQUEST_TRANSITIONS,
    )

    return {
        state.value: frozenset(target.value for target in targets)
        for state, targets in SERVICE_REQUEST_TRANSITIONS.items()
    }


def check_spec_consistency(
    transcription: dict[str, frozenset[str]] | None = None,
) -> ConsistencyResult:
    """Assert the transcribed transition table equals ``SERVICE_REQUEST_TRANSITIONS``.

    ``transcription`` defaults to the prover's real transcription; the test
    suite passes a deliberately-mutated copy to prove this tie is load-bearing.
    """
    if transcription is None:
        transcription = state_machine_smt.TRANSCRIBED_TRANSITIONS
    transcribed = {state: frozenset(targets) for state, targets in transcription.items()}
    code = _code_transitions_as_strings()

    if transcribed == code:
        return ConsistencyResult(
            True, f"transcription == SERVICE_REQUEST_TRANSITIONS ({len(code)} states)"
        )

    diffs = []
    for state in sorted(set(transcribed) | set(code)):
        a = set(transcribed.get(state, frozenset()))
        b = set(code.get(state, frozenset()))
        if a != b:
            diffs.append(f"{state}: transcription={sorted(a)} != code={sorted(b)}")
    return ConsistencyResult(False, "MISMATCH -- " + "; ".join(diffs))


def check_terminal_consistency() -> ConsistencyResult:
    """Assert the transcribed terminal set equals the code's empty-out-set states."""
    code = _code_transitions_as_strings()
    code_terminals = frozenset(state for state, targets in code.items() if not targets)
    transcribed_terminals = frozenset(state_machine_smt.TRANSCRIBED_TERMINALS)
    if code_terminals == transcribed_terminals:
        return ConsistencyResult(True, f"terminals match: {sorted(code_terminals)}")
    return ConsistencyResult(
        False,
        f"MISMATCH -- transcription={sorted(transcribed_terminals)} != "
        f"code={sorted(code_terminals)}",
    )


def main() -> int:
    """Print each invariant + z3 verdict and the spec-consistency checks."""
    print("Milexium formal invariants (z3-backed) -- packet MX-G-FORMAL-SMT-002\n")

    results = prove_all()
    all_proved = True
    for name, res in results.items():
        proved = res.proved  # type: ignore[attr-defined]
        status = res.status  # type: ignore[attr-defined]
        detail = res.detail  # type: ignore[attr-defined]
        all_proved = all_proved and proved
        verdict = "PROVED" if proved else "REFUTED"
        print(f"  [{verdict:7}] {name:20} z3={status:8} {detail}")

    print()
    cons = check_spec_consistency()
    term = check_terminal_consistency()
    print(f"  [{'OK' if cons.consistent else 'FAIL':7}] spec-consistency (transitions)  {cons.detail}")
    print(f"  [{'OK' if term.consistent else 'FAIL':7}] spec-consistency (terminals)    {term.detail}")

    ok = all_proved and cons.consistent and term.consistent
    print("\nRESULT:", "ALL GREEN" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
