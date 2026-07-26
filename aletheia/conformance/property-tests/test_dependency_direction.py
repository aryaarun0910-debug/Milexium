"""The direction of dependency between the five authority layers -- MX-ARCH-PROHIBITIONS-016.

ADR-0076 renamed the tree by authority and wrote the direction down:

    themis    ->  (nothing above it)
    metis     ->  themis TYPES only -- never a store, a writer or a persistence call
    aletheia  ->  themis
    argus     ->  themis, metis, aletheia
    talos     ->  (nothing -- it ships them)
    forge     ->  anything, and NOTHING may import forge

It was documented and not enforced, which in this repository is the same as not
being true yet. "Append-only" was also a rule in prose, and a direct SQL UPDATE
walked straight through it (ADR-0063 -> ADR-0074). This module turns the
direction into a test.

ASSERTED AGAINST THE SYNTAX TREE, NOT AGAINST GREP. The model is
`test_pack_third_party_verification.test_standalone_verifier_imports_nothing_from_this_repository`.
A grep for "import argus" misses `from argus.sdk import x`, misses a function-local
import indented four spaces, and hits every line of prose that names the word.
`ast.walk` sees `Import` and `ImportFrom` wherever they are -- module level,
inside a function, inside a `try` -- and sees nothing else.

WHAT THIS DOES NOT SEE, STATED RATHER THAN LEFT TO BE DISCOVERED. An `import`
statement is one of two ways to take a dependency on another module's code. The
other is to load a file and execute it, and `test_no_layer_loads_and_executes_python_from_forge`
below exists because that second channel is not hypothetical here -- it is in
use, in a shipping module, today. See that test.

TWO CLASSES OF MODULE, AND WHY THE DISTINCTION IS NOT AN ESCAPE HATCH

The direction constrains **the product**. `aletheia/conformance/` is the test
tree and `aletheia/benchmarks/` is the measurement tree: a test that could not
import the thing it tests would not be a test, and `aletheia/conformance/`
imports all five layers precisely because all five are under test. `talos/tools/`
and `talos/contracts/generate.py` are build and ops scripts -- talos ships the
other layers, so its scripts read them; `generate.py` imports `argus.api.app` for
the sole purpose of emitting that app's OpenAPI contract.

That carve-out is bounded three ways, and each bound is its own test:

1. `test_the_exemption_is_opt_in_so_new_code_is_policed_by_default` -- exemption
   requires a named entry HERE. A new directory (`argus/command_centre/`, which
   appeared while this was being written) is product code from its first commit,
   not an unclassified special case waiting for someone to decide.
2. `test_nothing_in_any_layer_imports_forge` -- the carve-out does not extend to
   forge. Test trees and build scripts are bound by that one too.
3. `test_the_carve_out_is_load_bearing_and_not_decorative` -- the carve-out must
   actually be carrying edges the shipping rule would reject. If it ever stops,
   it is dead weight and should be deleted, and this test says so.

FINDINGS RECORDED HERE RATHER THAN FIXED (the packet's owned paths are tests
only; three other agents hold the source):

- **`aletheia/benchmarks/` imports `metis`** in 21 places. Under the direction as
  written that is a violation; under the reading that a benchmark is a
  measurement instrument rather than product code, it is what a solver benchmark
  is for. It is carved out and named.
- **`talos/contracts/generate.py` imports `argus.api.app`**, and 4 talos modules
  import `themis` (6 sites) across `contracts/` and `tools/`. "talos -> nothing"
  is the least accurate line in the table.
- **`aletheia/verify/formal.py` executes Python from `forge/`.** This is the one
  that matters; it is a shipping module, and see the test for the detail.

The load-bearing half of the rule holds with ZERO exemptions and is asserted as
such: themis imports nothing above it, metis reaches nothing above it, the
aletheia evidence library reaches only themis, argus reaches only down, and no
`import forge` statement exists anywhere in the tree.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# --------------------------------------------------------------------------- #
# The rule                                                                      #
# --------------------------------------------------------------------------- #

LAYERS = ("themis", "metis", "aletheia", "argus", "talos", "forge")

PERMITTED: dict[str, frozenset[str]] = {
    "themis": frozenset({"themis"}),
    "metis": frozenset({"metis", "themis"}),
    "aletheia": frozenset({"aletheia", "themis"}),
    "argus": frozenset({"argus", "themis", "metis", "aletheia"}),
    "talos": frozenset({"talos"}),
}

RULE_TEXT: dict[str, str] = {
    "themis": "themis governs what is true; nothing may sit beneath it, so it imports no layer",
    "metis": "metis proposes; it may read themis TYPES and nothing else",
    "aletheia": "aletheia proves; it reads themis and nothing else",
    "argus": "argus shows; it reads themis, metis and aletheia, and is read by none of them",
    "talos": "talos ships the others; it is not a dependency of any of them",
}

TOP_LEVEL_ALIASES: dict[str, str] = {
    # `pythonpath = [".", "aletheia"]` (pyproject.toml) makes `aletheia/conformance/`
    # importable as bare `conformance`, and 45 fixture imports are spelled that
    # way. Resolved here so those edges are attributed to aletheia rather than
    # silently ignored as a non-layer import -- an unresolved alias is how an
    # import walker becomes vacuous.
    "conformance": "aletheia",
}

# --------------------------------------------------------------------------- #
# Which modules are the product, and which are the tools that check and ship it #
# --------------------------------------------------------------------------- #

EXPECTED_SHIPPING_TREES: tuple[str, ...] = (
    "themis",
    "metis",
    "aletheia/evidence",
    "aletheia/verify",
    "aletheia/replay",
    "argus/api",
    "argus/sdk",
    "argus/demo",
)
"""The product trees that exist today. NOT the definition of "shipping" -- that
is `everything under the five layers that is not explicitly exempt`, so a new
tree is POLICED by default rather than unclassified.

The distinction is not academic: `argus/command_centre/` appeared in this tree
while this packet was being written. Under a rule that demanded classification,
the concurrent packet building it would have gone red for a reason that had
nothing to do with the direction. Under a fail-safe default it is bound by the
direction from its first commit, which is the outcome that was actually wanted.

This tuple is therefore a staleness check, not a gate: `test_the_expected_shipping_trees_still_hold_modules`
fails if one of them empties out, because that means a rename has moved the
product somewhere this file is not looking."""

NON_SHIPPING_TREES: dict[str, str] = {
    "aletheia/conformance": (
        "the conformance suite. A test imports what it tests; this tree imports all "
        "five layers because all five are under test. It ships nothing."
    ),
    "aletheia/benchmarks": (
        "the measurement tree. A solver benchmark exists to drive metis.decide and "
        "time it. FINDING: under the direction as written this is a violation, and it "
        "is 21 import sites."
    ),
    "talos/contracts": (
        "the contract generator. `generate.py` imports `argus.api.app` to emit that "
        "app's OpenAPI document. FINDING: 'talos -> nothing' does not describe this."
    ),
    "talos/tools": (
        "build and ops scripts (repository audit, evidence registry, manifest and "
        "model-card builders). FINDING: 2 of them import themis; the other 2 themis "
        "readers are in talos/contracts."
    ),
}


@dataclass(frozen=True)
class Violation:
    path: str
    lineno: int
    statement: str
    source_layer: str
    target_layer: str

    def __str__(self) -> str:
        return (
            f"{self.path}:{self.lineno}  {self.statement}\n"
            f"      {self.source_layer} -> {self.target_layer} is not permitted: "
            f"{RULE_TEXT[self.source_layer]}"
        )


# --------------------------------------------------------------------------- #
# The walker                                                                    #
# --------------------------------------------------------------------------- #


def _imports_in_tree(tree: ast.Module) -> tuple[tuple[str, int, str], ...]:
    """Every absolute module name this syntax tree imports, as
    (name, line, statement).

    Relative imports (`from . import x`) are skipped: they cannot cross a layer
    boundary by construction, because a relative import is resolved inside the
    importing package.
    """
    found: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            names = ", ".join(a.name for a in node.names)
            found.append((node.module, node.lineno, f"from {node.module} import {names}"))
    return tuple(found)


def imported_modules(source: str) -> tuple[tuple[str, int, str], ...]:
    return _imports_in_tree(ast.parse(source))


def target_layer(module_name: str) -> str | None:
    """The authority layer a module name belongs to, or None if it is stdlib or
    third-party."""
    top = module_name.split(".")[0]
    top = TOP_LEVEL_ALIASES.get(top, top)
    return top if top in LAYERS else None


def _violations_from(
    rel_path: str, imports: tuple[tuple[str, int, str], ...]
) -> tuple[Violation, ...]:
    """Every edge in one module that the direction forbids."""
    source_layer = rel_path.split("/")[0]
    allowed = PERMITTED.get(source_layer)
    if allowed is None:
        return ()
    out: list[Violation] = []
    for module_name, lineno, statement in imports:
        target = target_layer(module_name)
        if target is None or target in allowed:
            continue
        out.append(Violation(rel_path, lineno, statement, source_layer, target))
    return tuple(out)


def violations_in(rel_path: str, source: str) -> tuple[Violation, ...]:
    return _violations_from(rel_path, imported_modules(source))


def _python_files() -> tuple[Path, ...]:
    files: list[Path] = []
    for layer in ("themis", "metis", "aletheia", "argus", "talos"):
        for path in sorted((REPO_ROOT / layer).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            files.append(path)
    return tuple(files)


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


@lru_cache(maxsize=None)
def _parsed(path: Path) -> ast.Module:
    """Parse once. Ten tests walk the same ~225 modules, several of which are
    over a thousand lines; re-parsing (and re-walking) per test cost more wall
    clock than every assertion in this file put together."""
    return ast.parse(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _imports_of(path: Path) -> tuple[tuple[str, int, str], ...]:
    return _imports_in_tree(_parsed(path))


@lru_cache(maxsize=None)
def _forge_executor(path: Path) -> bool:
    return _executes_python_from_forge_tree(_parsed(path))


def _exempt_tree_of(rel_path: str) -> str | None:
    """The declared non-shipping tree this module sits in, or None -- and None is
    the FAIL-SAFE answer: a module in no declared exemption is product code and is
    policed. Exemption is opt-in and requires an edit to this file."""
    for tree in NON_SHIPPING_TREES:
        if rel_path == tree or rel_path.startswith(tree + "/"):
            return tree
    return None


ALL_FILES = _python_files()
SHIPPING_FILES = tuple(f for f in ALL_FILES if _exempt_tree_of(_rel(f)) is None)
NON_SHIPPING_FILES = tuple(f for f in ALL_FILES if _exempt_tree_of(_rel(f)) is not None)

# A floor, not a count. The walker finding nothing because a path moved is the
# exact way an import test goes quietly vacuous, so the population it walked is
# asserted rather than assumed. Deliberately well below today's numbers (223 and
# 130) so a packet that deletes a module does not fail this file spuriously.
_MINIMUM_FILES_WALKED = 150
_MINIMUM_SHIPPING_FILES = 80


def _report(violations) -> str:
    return "\n".join(str(v) for v in violations)


# --------------------------------------------------------------------------- #
# 1. The walker itself is not vacuous                                           #
# --------------------------------------------------------------------------- #


def test_the_walker_is_looking_at_the_repository_and_not_at_an_empty_set() -> None:
    """The first way this file could lie is by walking nothing at all -- a moved
    directory, a rename, a bad `parents[3]`. Then every assertion below passes
    over an empty sequence and the suite reports success for having checked
    nothing. That is the exact shape of the ten vacuous tests found in this
    repository this month."""
    assert (REPO_ROOT / "pyproject.toml").is_file(), f"REPO_ROOT is wrong: {REPO_ROOT}"
    assert len(ALL_FILES) >= _MINIMUM_FILES_WALKED, (
        f"only {len(ALL_FILES)} python files found under the five layers; the walker "
        "is looking in the wrong place"
    )
    assert len(SHIPPING_FILES) >= _MINIMUM_SHIPPING_FILES, (
        f"only {len(SHIPPING_FILES)} shipping modules found; the layer roots have "
        "moved and the direction rule is policing almost nothing"
    )


@pytest.mark.parametrize(
    "rel_path,statement,expected_target",
    [
        # One case per rule in the table, so no single rule can be the only one
        # the walker actually enforces.
        ("themis/canonical/storage.py", "from metis.decide import solve", "metis"),
        ("themis/canonical/storage.py", "import aletheia.verify", "aletheia"),
        ("metis/forecast/runtime.py", "from argus.sdk import MilexiumClient", "argus"),
        ("metis/decide/solver.py", "from aletheia.replay import teardown", "aletheia"),
        ("aletheia/evidence/packs.py", "import metis.forecast", "metis"),
        ("aletheia/replay/teardown.py", "from argus.api.app import create_app", "argus"),
        ("argus/sdk/client.py", "import talos.tools.audit_repository", "talos"),
        ("talos/tools/audit_repository.py", "from themis.canonical import Tenant", "themis"),
        # spelled the way pythonpath makes it available, not as `aletheia.conformance`
        ("metis/decide/ir.py", "from conformance.fixtures.builders import x", "aletheia"),
    ],
)
def test_the_walker_rejects_a_violating_edge_it_is_shown(
    rel_path: str, statement: str, expected_target: str
) -> None:
    """The second way this file could lie is by having a walker that never returns
    anything. Every assertion below is of the form "the violation set is empty",
    and a broken walker satisfies all of them.

    So the walker is shown a violation of each rule and must find it. This is the
    mutation these tests would otherwise be missing: the real tree is clean, so
    nothing else here ever exercises the failure path."""
    found = violations_in(rel_path, statement + "\n")

    assert len(found) == 1, f"the walker missed {rel_path}: {statement!r}"
    assert found[0].target_layer == expected_target
    assert found[0].lineno == 1
    assert rel_path in str(found[0])
    assert RULE_TEXT[rel_path.split("/")[0]] in str(found[0])


def test_the_walker_sees_an_import_that_is_not_at_module_level() -> None:
    """A function-local import is the natural way a violating edge gets added --
    it is what a developer reaches for to break a circular import, and it is
    invisible to a grep of the header block."""
    source = (
        "def build():\n"
        "    if True:\n"
        "        try:\n"
        "            from argus.api.app import create_app\n"
        "        except ImportError:\n"
        "            create_app = None\n"
    )
    found = violations_in("metis/forecast/runtime.py", source)

    assert len(found) == 1
    assert found[0].target_layer == "argus"
    assert found[0].lineno == 4


def test_the_walker_does_not_fire_on_prose_that_merely_names_a_layer() -> None:
    """The other half of the same point. A docstring is not an edge, and a test
    that cannot tell the difference gets deleted the first time it cries wolf."""
    source = (
        '"""This module is read by argus.api and never reads it back.\n\n'
        'See talos/contracts/generate.py. Do not import forge here."""\n'
        "from themis.canonical.vocab import ReasonCode\n"
        "COMMENT = 'argus'  # not an import either\n"
    )
    assert violations_in("metis/decide/ir.py", source) == ()


# --------------------------------------------------------------------------- #
# 2. The direction, on the product                                              #
# --------------------------------------------------------------------------- #


def test_no_shipping_module_imports_a_layer_the_rule_does_not_permit() -> None:
    """The rule itself, over every module that is part of the product. Zero
    exemptions -- if this needs one, the direction has changed and that is an
    ADR, not an entry in a list."""
    found: list[Violation] = []
    for path in SHIPPING_FILES:
        found.extend(_violations_from(_rel(path), _imports_of(path)))

    assert found == [], (
        f"{len(found)} import(s) break the authority direction ADR-0076 declares:\n"
        + _report(found)
    )


def test_themis_imports_no_layer_above_it() -> None:
    """Called out separately because it is the keystone. Themis governs what is
    true and permissible; every other layer reads it. The instant themis reads
    back -- a forecast to decide a state transition, a solver to decide
    feasibility -- the canonical layer's meaning depends on the thing it was
    supposed to be the ground for, and no amount of testing above it recovers
    that. Covers the whole of `themis/`, shipping or not."""
    found: list[Violation] = []
    for path in ALL_FILES:
        if _rel(path).split("/")[0] != "themis":
            continue
        found.extend(_violations_from(_rel(path), _imports_of(path)))

    assert found == [], "themis reads a layer above it:\n" + _report(found)


def test_no_layer_imports_argus_except_the_tools_that_check_and_ship_it() -> None:
    """Argus is the top of the stack: the operator's surface. Nothing beneath it
    may depend on it, or the layers below acquire an opinion about how they are
    displayed. Stated as its own test because it is the edge most likely to be
    added by convenience -- an SDK helper is right there and does the thing."""
    offenders: list[str] = []
    for path in ALL_FILES:
        rel = _rel(path)
        layer = rel.split("/")[0]
        if layer == "argus":
            continue
        for module_name, lineno, statement in _imports_of(path):
            if target_layer(module_name) != "argus":
                continue
            if _exempt_tree_of(rel) is not None:
                continue
            offenders.append(f"{rel}:{lineno}  {statement}")

    assert offenders == [], (
        "a module beneath argus imports it; the operational surface may read the "
        "layers below and none of them may read it back:\n" + "\n".join(offenders)
    )


# --------------------------------------------------------------------------- #
# 3. forge isolation -- the rule that keeps research from becoming load-bearing  #
# --------------------------------------------------------------------------- #


def test_nothing_in_any_layer_imports_forge() -> None:
    """`forge/` holds ADRs, research, business material and the relocated Kaggle
    experiment. It may reference the product freely; the product may never
    reference it. An import in this direction would make a market-sizing script
    or a negative research result a runtime dependency of a paratransit
    scheduler.

    NO carve-out. This one binds the test trees and the build scripts too, which
    is why it is walked over every file rather than over SHIPPING_FILES."""
    offenders: list[str] = []
    for path in ALL_FILES:
        for module_name, lineno, statement in _imports_of(path):
            if module_name.split(".")[0] == "forge":
                offenders.append(f"{_rel(path)}:{lineno}  {statement}")

    assert offenders == [], (
        "forge is imported by the product; nothing may import forge:\n"
        + "\n".join(offenders)
    )


_CODE_LOADERS = frozenset(
    {"spec_from_file_location", "exec_module", "run_path", "run_module"}
)

_KNOWN_FORGE_EXECUTORS: dict[str, str] = {
    "aletheia/verify/formal.py": (
        "FINDING, reported not fixed (this packet owns tests, not source). A SHIPPING "
        "module: `import aletheia.verify.formal` loads and executes "
        "forge/knowledge/architecture/formal/state_machine_smt.py and hash_chain_smt.py "
        "at module import time, by file path. The AST import walk above cannot see it, "
        "which is the point of this test -- 'nothing may import forge' is enforced "
        "against `import` and a dynamic load is not one. Two mitigations, both real: "
        "aletheia/verify/__init__.py does NOT import `formal`, so `import aletheia.verify` "
        "does not drag forge in; and the loaded modules are z3 proofs whose independence "
        "from themis is itself the point of ADR-0028. It is still a code dependency from "
        "a shipping module onto a docs tree, and it was confirmed by running it rather "
        "than inferred from the source: after `import aletheia.verify.formal`, "
        "sys.modules holds two entries whose __file__ is under forge/."
    ),
    "aletheia/conformance/property-tests/test_panel_findings.py": (
        "The conformance tree loading forge/business/outreach/*.py to check the claims "
        "those scripts make. Less severe -- it is a test, it ships nothing, and policing "
        "forge's claims is what it is for -- but it is the same mechanism and is pinned "
        "here so the pair is one list rather than one known case and one unnoticed one."
    ),
}


def _executes_python_from_forge_tree(tree: ast.Module) -> bool:
    """Conservative: a module that both names a `forge` path segment in CODE
    position (not in a docstring or comment) and calls a dynamic code loader.

    Deliberately over-approximating rather than attempting dataflow. Reading a
    markdown or JSON file out of forge is NOT a code dependency and is done in a
    dozen places legitimately -- `aletheia/evidence/packs.py` cites ADR paths,
    `talos/tools/audit_repository.py` audits the tree. What this looks for is the
    conjunction: a forge path AND the machinery to execute one.
    """
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                docstrings.add(id(node.value))

    names_forge = any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and "forge" in node.value.replace("\\", "/").split("/")
        for node in ast.walk(tree)
    )
    if not names_forge:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in _CODE_LOADERS:
                return True
    return False


def _executes_python_from_forge(source: str) -> bool:
    return _executes_python_from_forge_tree(ast.parse(source))


def test_no_layer_loads_and_executes_python_from_forge_beyond_the_two_known_cases() -> None:
    """The second channel, and the one the import walk is blind to.

    An `import` is not the only way to depend on another module's code:
    `importlib.util.spec_from_file_location` + `exec_module` takes the same
    dependency by file path and leaves no import statement behind. This is not
    hypothetical here -- see `_KNOWN_FORGE_EXECUTORS` for the two modules that do
    it, one of which ships.

    The known set is PINNED, in both directions. A third module doing this fails.
    So does removing one of the two without updating this list -- deliberately,
    because a grandfather clause that outlives the case it grandfathered is how a
    prohibition rots back into prose. If you fix `formal.py`, delete its entry and
    this test goes green again.
    """
    executors = {
        _rel(path)
        for path in ALL_FILES
        if _forge_executor(path)
    }

    unexpected = sorted(executors - set(_KNOWN_FORGE_EXECUTORS))
    assert unexpected == [], (
        "a module executes Python out of forge/ and is not in the recorded set. "
        "forge is research, business material and architectural record: it may "
        "reference the product, and the product may not depend on it. Nothing here "
        "is entitled to a second grandfather clause:\n" + "\n".join(unexpected)
    )

    stale = sorted(set(_KNOWN_FORGE_EXECUTORS) - executors)
    assert stale == [], (
        "these modules no longer execute Python from forge -- good. Delete them from "
        "_KNOWN_FORGE_EXECUTORS so the exemption does not outlive its case:\n"
        + "\n".join(stale)
    )


def test_the_forge_executor_detector_can_tell_a_citation_from_a_dependency() -> None:
    """The detector is an over-approximation, so it has to be shown both sides or
    it proves nothing: an over-approximation that fires on everything is a
    permanent red, and one that fires on nothing is the vacuous test this packet
    exists to stop writing."""
    depends = (
        "import importlib.util\n"
        "from pathlib import Path\n"
        "d = Path(__file__).parents[2] / 'forge' / 'research' / 'thing'\n"
        "spec = importlib.util.spec_from_file_location('t', d / 'x.py')\n"
    )
    assert _executes_python_from_forge(depends)

    cites = (
        '"""Rationale in forge/knowledge/architecture/decisions/0076.md."""\n'
        "from pathlib import Path\n"
        "DOC = Path('forge/knowledge/docs/MODEL_CARDS.md')\n"
        "text = DOC.read_text()\n"
    )
    assert not _executes_python_from_forge(cites), (
        "reading a document out of forge is a citation, not a dependency; a detector "
        "that cannot tell them apart would condemn a dozen honest call sites"
    )

    loads_elsewhere = (
        "import importlib.util\n"
        "spec = importlib.util.spec_from_file_location('t', 'talos/tools/x.py')\n"
    )
    assert not _executes_python_from_forge(loads_elsewhere)


# --------------------------------------------------------------------------- #
# 4. The carve-out is bounded, and it is carrying weight                        #
# --------------------------------------------------------------------------- #


def test_the_exemption_is_opt_in_so_new_code_is_policed_by_default() -> None:
    """The failure mode a carve-out invites: someone adds a directory and it
    inherits whichever default the code happened to pick.

    The default here is POLICED. Exemption costs an entry in `NON_SHIPPING_TREES`
    with a reason beside it, in this file, in a diff someone reads. Asserted
    directly rather than trusted, because it is the single line that decides
    whether every rule above applies to code written next month.

    This is not hypothetical. `argus/command_centre/` -- the operational surface
    ADR-0076 said the tree should be frozen for -- landed while this packet was
    being written, and it is bound by the direction because of this default and
    for no other reason."""
    for hypothetical in (
        "argus/command_centre/render.py",
        "argus/ui/dashboard.py",
        "themis/newthing/store.py",
        "metis/plan/solver.py",
        "aletheia/attest/pack.py",
    ):
        assert _exempt_tree_of(hypothetical) is None, (
            f"{hypothetical} would be EXEMPT from the direction rule without anyone "
            "declaring it so. Exemption must be opt-in."
        )

    # And the exemption list is exactly what the docstring says it is, so it
    # cannot grow without a diff to this file.
    assert set(NON_SHIPPING_TREES) == {
        "aletheia/conformance",
        "aletheia/benchmarks",
        "talos/contracts",
        "talos/tools",
    }, (
        f"the exemption list has changed to {sorted(NON_SHIPPING_TREES)}. Every entry "
        "is a place the authority direction is NOT enforced; adding one is a decision, "
        "and this assertion is where it gets made deliberately."
    )


def test_the_expected_shipping_trees_still_hold_policed_modules() -> None:
    """A staleness check, not a gate. If `aletheia/verify/` were renamed, every
    rule above would keep passing over a tree that no longer contains the code it
    was written for -- the quiet version of the failure this packet exists to
    stop."""
    shipping = {_rel(p) for p in SHIPPING_FILES}
    for tree in EXPECTED_SHIPPING_TREES:
        assert (REPO_ROOT / tree).is_dir(), f"{tree} is no longer a directory"
        assert any(rel.startswith(tree + "/") for rel in shipping), (
            f"{tree} holds no policed module any more. Either it emptied out or it has "
            "been swallowed by an exemption; both mean the direction rule stopped "
            "covering product code without saying so."
        )


def test_every_exempt_tree_still_exists() -> None:
    """A carve-out for a directory that has been renamed away covers nothing and
    reads as though it covers something."""
    for tree in NON_SHIPPING_TREES:
        assert (REPO_ROOT / tree).is_dir(), (
            f"{tree} is exempt from the direction rule but is not a directory. A stale "
            "exemption is an exemption nobody is watching."
        )


def test_every_non_shipping_tree_states_a_reason() -> None:
    """An exemption with no justification beside it is the prose rule this packet
    exists to replace, moved into a dict."""
    for tree, reason in NON_SHIPPING_TREES.items():
        assert len(reason) > 40, (
            f"{tree} is exempt from the direction rule with no reason recorded. An "
            "exemption whose justification is not written down is the prose rule this "
            "packet exists to replace."
        )


def test_the_carve_out_is_load_bearing_and_not_decorative() -> None:
    """The anti-vacuity assertion, and the finding, in one.

    If the non-shipping trees contained no edge the shipping rule would reject,
    the carve-out would be protecting nothing and every test above would pass
    identically without it -- at which point it should be deleted and the rule
    applied to the whole tree. It is not decorative: it is carrying real
    violations of the direction as ADR-0076 states it, and this test names them
    so they are a recorded finding rather than a silent allowance."""
    carried: list[Violation] = []
    for path in NON_SHIPPING_FILES:
        carried.extend(_violations_from(_rel(path), _imports_of(path)))

    assert carried, (
        "no module in the non-shipping trees breaks the direction any more. The "
        "carve-out is now dead weight: empty NON_SHIPPING_TREES and police the whole "
        "tree with one rule."
    )

    by_source = {v.path.split("/")[0] for v in carried}
    assert "aletheia" in by_source, (
        "aletheia/benchmarks no longer imports metis -- the recorded finding has "
        "changed; update this file's docstring"
    )
    assert "talos" in by_source, (
        "talos no longer imports themis or argus -- 'talos -> nothing' has become "
        "true; update this file's docstring and drop talos/ from NON_SHIPPING_TREES"
    )


def test_the_recorded_talos_finding_is_still_exactly_what_the_docstring_says() -> None:
    """The docstring above makes a specific claim about talos: `contracts/generate.py`
    reaches up into argus, and `tools/` reaches down into themis. A docstring
    that describes the tree as it was six months ago is worse than no docstring,
    so the claim is asserted rather than written."""
    reaches: dict[str, set[str]] = {}
    for path in ALL_FILES:
        rel = _rel(path)
        if not rel.startswith("talos/"):
            continue
        for module_name, _lineno, _statement in _imports_of(path):
            target = target_layer(module_name)
            if target and target != "talos":
                reaches.setdefault(target, set()).add(rel)

    assert reaches.get("argus") == {"talos/contracts/generate.py"}, (
        f"talos reaches argus from {sorted(reaches.get('argus', ()))}; the docstring "
        "says only the OpenAPI contract generator does"
    )
    assert reaches.get("themis"), "talos no longer reads themis; the docstring is stale"
    assert "aletheia" not in reaches and "metis" not in reaches, (
        f"talos has started reading {sorted(set(reaches) - {'themis', 'argus'})}. It "
        "ships the layers; a build script that reads the solver or the evidence "
        "library is doing something a build script should not."
    )
