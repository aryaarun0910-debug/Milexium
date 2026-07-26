"""Metis alters no canonical state and authorises no operation -- MX-ARCH-PROHIBITIONS-016.

    | Metis | must never alter canonical state, or authorise an operation |

ADR-0076 recorded this as one of the two prohibitions that "already hold": Metis
"imports types and vocabularies from Themis and never a store or a writer". It
held. It was not tested, and it was not quite what the README said either -- see
THE FINDING below.

WHY THE BOUNDARY IS THE ONE WORTH SPENDING A FILE ON. Metis is the layer that
proposes: a demand forecast, a CP-SAT assignment, a pooling decision, a capacity
value. Every one of those is a HYPOTHESIS. The moment a proposal can also write
the record of what happened, the distinction between "the solver suggested
vehicle 3" and "vehicle 3 was assigned" stops being visible in the ledger, and
the evidence pack -- the entire product -- reconstructs a decision from rows the
proposer wrote about itself. The prohibition is not tidiness. It is what makes
`aletheia/evidence` mean anything.

It holds today BY CONSTRUCTION, which is the strongest form and also the most
fragile: nothing stops the next packet from passing a store into a solver for
convenience, and nothing would have noticed. The failure messages below are
written for that person. They are long on purpose -- someone will legitimately
want a store in Metis (to read a champion model, to page a large instance in),
and the message has to be enough to make them stop and choose deliberately.

HOW THIS IS ASSERTED. Against the syntax tree, like
`test_pack_third_party_verification.test_standalone_verifier_imports_nothing_from_this_repository`,
and with the persistence surface of Themis **derived from Themis itself** rather
than hand-listed. A hand-listed deny list goes stale the day a store is renamed,
and goes stale silently -- it keeps passing. Here, a Themis module counts as
persistence if it defines a writer method or imports a database driver, and
`test_the_persistence_surface_is_derived_correctly` checks that derivation
against both a known-writer list and a known-NOT-writer list, so the set can
neither collapse to empty nor swell to everything without failing.

THE FINDING: METIS IMPORTS ONE PERSISTENCE MODULE, AND IT IS NOT THE FOUR TYPES.
The packet brief and the README both say Metis imports only `entities`, `ids`,
`time` and `vocab` from Themis. That is not what the tree says. Metis also
imports:

  metis/forecast/runtime.py:27      from themis.core.model_registry import ModelRegistry
  metis/forecast/serve_drift.py:76  from themis.core.drift import ...

`themis.core.drift` is pure statistics (PSI, KS, CUSUM) and writes nothing.
`themis.core.model_registry` is a different matter: it defines `register()` and
`promote()`, and the same module carries `PersistentModelRegistry` over a real
`CoreDatabase`. Metis holds a `ModelRegistry` and calls exactly one method on it
-- `champion(task)`, a read -- but the WRITE SURFACE IS IN SCOPE at the call
site. The prohibition survives on discipline, not on structure, in that one
place. It is pinned below rather than fixed: this packet owns tests, and Program
E owns `metis/forecast/`.

WHAT IS NOT MECHANISED HERE. This file proves Metis cannot reach a writer. It
does not prove Metis's proposals are *correct*, and it cannot prove that a value
Metis returns is not later written by a caller who should not have -- that is
Themis's own append-only boundary (ADR-0074) and Argus's, and both are tested
elsewhere.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# --------------------------------------------------------------------------- #
# What "a store, a writer, a session, a persistence call" means, concretely     #
# --------------------------------------------------------------------------- #

DRIVERS = frozenset(
    {
        "sqlite3",
        "psycopg",
        "psycopg2",
        "asyncpg",
        "sqlalchemy",
        "minio",
        "boto3",
        "duckdb",
        "pyarrow",
    }
)
"""Anything that opens a session to a database or an object store. A layer that
holds one of these has a connection, and a connection is a writer whatever the
method is called."""

WRITER_DEFINITIONS = frozenset(
    {
        # canonical stores
        "append", "append_event", "append_decision_alternative", "create_tenant",
        "record_block", "record_run_piece", "record_deadhead_segment",
        "record_outcome", "insert_vehicle_observation", "insert_stop_time_observation",
        # ontology store
        "record_fact", "record_event", "record_action", "record_identity_resolution",
        "register_object", "assert_relationship", "take_snapshot",
        # core: registry, promotion, migrations, feature store
        "register", "promote", "register_challenger", "evaluate_and_maybe_promote",
        "migrate", "write",
        # estate
        "acquire", "put_object",
        # raw session surface
        "commit", "rollback", "execute", "executemany", "execute_ddl",
    }
)
"""A Themis module that DEFINES one of these is a place canonical state changes.
Used to classify Themis, never to scan Metis -- `append` alone would match every
`list.append` in the solver."""

WRITER_CALLS = WRITER_DEFINITIONS - {"append", "write", "register", "acquire"}
"""The same vocabulary minus the four names that collide with ordinary Python
(`list.append`, `file.write`, `re.match(...).register` is not a thing but
`register` is a common local verb, `acquire` is `threading.Lock.acquire`). The
two names that matter most for the recorded finding -- `ModelRegistry.register`
and `.promote` -- are covered by `test_metis_calls_no_mutator_of_the_one_registry_it_holds`
by name, so dropping `register` here costs nothing."""

AUTHORISATION_MODULES = (
    "themis.canonical.state_machine",
    "themis.canonical.lifecycle",
    "themis.canonical.lifecycle_verify",
    "themis.ontology.actions",
)
"""The other half of the prohibition. "Authorise an operation" is deciding that a
request may legally move from one state to the next, or that an actor holds the
permission for an act. Those decisions live in Themis. Metis may compute that an
assignment is *feasible*; it may not conclude that it is *permitted*."""

# The surface Metis is permitted to read from Themis. An allow list ON PURPOSE,
# and pinned tight: the point is that adding to it is a decision someone makes
# deliberately with the failure message in front of them, not a diff nobody reads.
PERMITTED_THEMIS_MODULES: dict[str, str] = {
    "themis.canonical.entities": "the canonical entity types. Data, no behaviour, no store.",
    "themis.canonical.ids": "the typed UUIDv7 id kinds, so a VehicleId cannot be passed where a DriverId belongs.",
    "themis.canonical.time": "the UTC-aware datetime type and its validator.",
    "themis.canonical.vocab": (
        "the closed vocabularies -- ReasonCode, MobilityAid, ServiceRequestState. Metis "
        "must speak the SAME words Themis governs; a second copy of ReasonCode in the "
        "solver is how a denial reason drifts out of the ledger's vocabulary."
    ),
    "themis.core.drift": (
        "PSI, KS and CUSUM, as pure functions over arrays. Program D owns them "
        "(ADR-0034) and metis/forecast/serve_drift.py imports them read-only rather "
        "than re-implementing a second, subtly different PSI."
    ),
    "themis.core.model_registry": (
        "THE RECORDED FINDING -- see the module docstring. Metis holds a `ModelRegistry` "
        "to resolve the champion model for a task. The class also defines `register()` "
        "and `promote()`, and the module carries `PersistentModelRegistry` over a real "
        "database, so this is the one import where the prohibition rests on Metis "
        "choosing not to call something rather than on it being unable to."
    ),
}


# --------------------------------------------------------------------------- #
# Walkers                                                                       #
# --------------------------------------------------------------------------- #


def _files(root: str) -> tuple[Path, ...]:
    return tuple(
        p
        for p in sorted((REPO_ROOT / root).rglob("*.py"))
        if "__pycache__" not in p.parts
    )


@lru_cache(maxsize=None)
def _parsed(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports(tree: ast.Module) -> tuple[tuple[str, int], ...]:
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((a.name, node.lineno) for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.append((node.module, node.lineno))
    return tuple(out)


def _imported_names(tree: ast.Module, module: str) -> frozenset[str]:
    """The individual names taken out of one module (`from X import a, b`)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            names.update(a.name for a in node.names)
    return frozenset(names)


def _defined_functions(tree: ast.Module) -> frozenset[str]:
    return frozenset(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _attribute_calls(tree: ast.Module) -> tuple[tuple[str, int], ...]:
    return tuple(
        (node.func.attr, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    )


def _module_name(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


@lru_cache(maxsize=1)
def themis_persistence_modules() -> frozenset[str]:
    """Every Themis module that can change stored state, DERIVED from Themis.

    Not a hand-written list. A hand-written list of stores would keep passing on
    the day `storage.py` is renamed, which is the failure mode this whole packet
    is about: the rule survives as text after the thing it named has moved.
    """
    found: set[str] = set()
    for path in _files("themis"):
        tree = _parsed(path)
        defines_writer = bool(_defined_functions(tree) & WRITER_DEFINITIONS)
        holds_driver = any(
            name.split(".")[0] in DRIVERS for name, _line in _imports(tree)
        )
        if defines_writer or holds_driver:
            found.add(_module_name(path))
    return frozenset(found)


METIS_FILES = _files("metis")


# --------------------------------------------------------------------------- #
# 0. Neither the walker nor the derived surface is empty                        #
# --------------------------------------------------------------------------- #


def test_the_walker_is_looking_at_metis_and_not_at_an_empty_set() -> None:
    """Every assertion in this file has the shape "nothing in Metis does X". All
    of them pass over an empty file list. Ten vacuous tests were found in this
    repository this month and every one of them had a fixture that never reached
    the case; an empty walk is the same defect one level up."""
    assert (REPO_ROOT / "pyproject.toml").is_file(), f"REPO_ROOT is wrong: {REPO_ROOT}"
    assert len(METIS_FILES) >= 15, (
        f"only {len(METIS_FILES)} modules found under metis/; the walker is looking in "
        "the wrong place and every assertion below is vacuous"
    )
    assert any(p.name == "runtime.py" for p in METIS_FILES)
    assert any(p.name == "cpsat.py" for p in METIS_FILES)


def test_the_persistence_surface_is_derived_correctly() -> None:
    """The deny list is computed from Themis, so it has to be checked in BOTH
    directions or it proves nothing.

    Too narrow (it collapses to a handful, or to nothing) and "Metis imports no
    persistence module" becomes true by having nothing to be true about. Too wide
    (every Themis module counts) and it would already be failing, so someone would
    weaken it. Both bounds are asserted."""
    persistence = themis_persistence_modules()

    must_be_writers = {
        "themis.canonical.storage",
        "themis.canonical.postgres_storage",
        "themis.canonical.observation_store",
        "themis.ontology.store",
        "themis.core.feature_store",
        "themis.core.model_registry",
        "themis.core.promotion",
        "themis.core.migrations",
        "themis.estate.acquire",
    }
    missing = sorted(must_be_writers - persistence)
    assert missing == [], (
        "these Themis modules write canonical state and the derivation no longer "
        f"classifies them as persistence, so Metis could import them freely: {missing}. "
        "Either a writer method was renamed (extend WRITER_DEFINITIONS) or the module "
        "moved."
    )

    must_not_be_writers = {
        "themis.canonical.entities",
        "themis.canonical.ids",
        "themis.canonical.time",
        "themis.canonical.vocab",
        "themis.core.drift",
    }
    overreach = sorted(must_not_be_writers & persistence)
    assert overreach == [], (
        f"the derivation now calls these persistence modules: {overreach}. They are the "
        "types and vocabularies Metis is SUPPOSED to read; if the derivation swallows "
        "them the deny list bans everything and will simply be deleted by whoever hits "
        "it next."
    )

    assert len(persistence) >= 8, (
        f"only {len(persistence)} Themis persistence modules derived; the derivation has "
        "collapsed and 'Metis imports none of them' means nothing"
    )
    assert len(persistence) < len(_files("themis")), (
        "every Themis module is classified as persistence; the derivation is useless"
    )


# --------------------------------------------------------------------------- #
# 1. Metis alters no canonical state                                            #
# --------------------------------------------------------------------------- #


def test_metis_imports_no_store_writer_or_session_from_themis() -> None:
    """The prohibition, structurally.

    `themis.core.model_registry` is the one recorded exception and it is pinned by
    name, not waved through by a wildcard -- see `PERMITTED_THEMIS_MODULES` and
    `test_metis_calls_no_mutator_of_the_one_registry_it_holds`.
    """
    persistence = themis_persistence_modules()
    allowed_persistence = {"themis.core.model_registry"}

    offenders: list[str] = []
    for path in METIS_FILES:
        for module, lineno in _imports(_parsed(path)):
            if module in persistence and module not in allowed_persistence:
                rel = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel}:{lineno}  import {module}")

    assert offenders == [], (
        "Metis has taken a dependency on a Themis module that WRITES:\n"
        + "\n".join(offenders)
        + "\n\n"
        "WHY THIS IS REFUSED RATHER THAN REVIEWED. Metis proposes; it does not record. "
        "A solver that can reach a store can write the record of the decision it just "
        "made, and from that point the ledger no longer distinguishes 'the solver "
        "suggested vehicle 3' from 'vehicle 3 was assigned' -- which is the single "
        "distinction the evidence pack exists to preserve, and the one an FTA or "
        "disability-advocate review will ask about first.\n\n"
        "IF YOU NEED STATE IN METIS, and that is a real need, the shapes that keep the "
        "boundary are:\n"
        "  * take the data as an ARGUMENT. Every solver here already does: the caller "
        "    (argus.sdk / argus.api) reads Themis and hands Metis plain values.\n"
        "  * take a narrow READ-ONLY protocol, not the store class. `ModelRegistry` is "
        "    the precedent and also the cautionary tale -- see this module's docstring "
        "    for why it is not a clean one.\n"
        "  * return a proposal and let the CALLER write it. That is what makes the "
        "    written record an act by an identified actor rather than a side effect.\n\n"
        "If none of those work, the boundary genuinely needs to move, and that is an "
        "ADR, not an import."
    )


def test_metis_reads_only_the_themis_surface_that_has_been_thought_about() -> None:
    """The allow list, and it is deliberately tighter than the deny list.

    A new Themis import that happens not to be a writer today still passes
    `test_metis_imports_no_store_writer_or_session_from_themis`, and would put a
    module into Metis's dependency cone whose future is somebody else's decision.
    `themis.core.model_registry` is exactly how that goes wrong: nothing about it
    was a writer when Metis first imported it for a type annotation.
    """
    offenders: list[str] = []
    for path in METIS_FILES:
        for module, lineno in _imports(_parsed(path)):
            if not module.startswith("themis"):
                continue
            if module in PERMITTED_THEMIS_MODULES:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            offenders.append(f"{rel}:{lineno}  import {module}")

    assert offenders == [], (
        "Metis reads a part of Themis this boundary has not been reasoned about:\n"
        + "\n".join(offenders)
        + "\n\nThe surface Metis is allowed, and why each one is there:\n"
        + "\n".join(f"  {m}\n      {why}" for m, why in PERMITTED_THEMIS_MODULES.items())
        + "\n\nAdding to that list is a legitimate thing to do. Do it explicitly, with "
        "the reason written next to it, and check the new module against "
        "`themis_persistence_modules()` first -- if it is in there, you are adding a "
        "writer to the layer that must not write."
    )


def test_metis_holds_no_database_driver_or_object_store_client() -> None:
    """A store reached through Themis is one channel. `import sqlite3` is the
    other, and it is the one a hand-written deny list of Themis modules would
    never see. `themis.canonical.storage` is a thin wrapper over exactly this."""
    offenders: list[str] = []
    for path in METIS_FILES:
        for module, lineno in _imports(_parsed(path)):
            if module.split(".")[0] in DRIVERS:
                rel = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel}:{lineno}  import {module}")

    assert offenders == [], (
        "Metis has opened its own connection, bypassing Themis entirely:\n"
        + "\n".join(offenders)
        + "\n\nThis is worse than importing a Themis store, not better: a Themis store "
        "at least carries the tenant scoping, the RLS GUC and the hash chain. A raw "
        "driver in the solver has none of them."
    )


def test_metis_calls_no_method_that_writes() -> None:
    """Imports are the door; this is the room. A store could also arrive as a
    constructor argument with no import at all -- `def solve(problem, store)` --
    and be duck-typed. Method names cannot hide the same way."""
    offenders: list[str] = []
    for path in METIS_FILES:
        for attr, lineno in _attribute_calls(_parsed(path)):
            if attr in WRITER_CALLS:
                rel = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel}:{lineno}  .{attr}(...)")

    assert offenders == [], (
        "Metis calls a method that changes stored state:\n"
        + "\n".join(offenders)
        + "\n\nIf the object was passed in rather than imported, the import checks above "
        "would not have seen it -- which is why this one exists. Metis returns "
        "proposals; the caller records them."
    )


def test_metis_opens_no_file_for_writing() -> None:
    """Metis reads: a trained xgboost artifact, a Cordeau DARP instance, a
    calibration file. It writes nothing. A written file is state, and state
    written by the proposer is state nobody else can attribute."""
    offenders: list[str] = []
    write_modes = ("w", "a", "x", "+")
    for path in METIS_FILES:
        rel = path.relative_to(REPO_ROOT).as_posix()
        tree = _parsed(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in ("write_text", "write_bytes", "mkdir", "touch", "unlink", "rmdir"):
                offenders.append(f"{rel}:{node.lineno}  .{name}(...)")
                continue
            if name != "open":
                continue
            mode = None
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                mode = node.args[1].value
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = kw.value.value
            if isinstance(mode, str) and any(c in mode for c in write_modes):
                offenders.append(f"{rel}:{node.lineno}  open(..., {mode!r})")

    assert offenders == [], (
        "Metis writes to the filesystem:\n" + "\n".join(offenders)
    )


# --------------------------------------------------------------------------- #
# 2. The one exception, held to account                                         #
# --------------------------------------------------------------------------- #


def test_metis_names_only_the_read_side_of_the_one_registry_it_holds() -> None:
    """`themis/core/model_registry.py` carries three things: `ModelRegistry` (the
    in-memory catalog), `PersistentModelRegistry` (the same contract over a real
    database), and the `CoreDatabase` it needs. Metis takes the first and only the
    first.

    That distinction is the whole reason the exception is tolerable, so it is
    asserted rather than assumed. `from themis.core.model_registry import
    PersistentModelRegistry` would put a live database handle inside the forecast
    runtime with no other line of code changing."""
    forbidden = {"PersistentModelRegistry", "CoreDatabase"}
    offenders: list[str] = []
    for path in METIS_FILES:
        taken = _imported_names(_parsed(path), "themis.core.model_registry")
        rel = path.relative_to(REPO_ROOT).as_posix()
        for name in sorted(taken & forbidden):
            offenders.append(f"{rel}  imports {name}")

    assert offenders == [], (
        "Metis has taken the DURABLE half of the model registry:\n"
        + "\n".join(offenders)
        + "\n\n`ModelRegistry` is an in-memory catalog Metis is handed. "
        "`PersistentModelRegistry` is a database session. Holding the second means the "
        "forecast runtime can write the model catalog it is supposed to be reading, and "
        "a champion pointer written by the layer that serves the champion is not "
        "evidence of anything."
    )


def test_metis_calls_no_mutator_of_the_one_registry_it_holds() -> None:
    """The registry's own write surface, by name, checked against the real class
    so the list cannot go stale.

    `WRITER_CALLS` deliberately drops `register` because it collides with ordinary
    verbs; this test puts it back for the two names that actually matter, and
    derives them from `ModelRegistry` itself rather than trusting this docstring."""
    from themis.core.model_registry import ModelRegistry

    mutators = {"register", "promote"}
    for name in mutators:
        assert callable(getattr(ModelRegistry, name, None)), (
            f"ModelRegistry.{name} no longer exists; this test is now checking for a "
            "method that cannot be called and proves nothing"
        )

    offenders: list[str] = []
    for path in METIS_FILES:
        for attr, lineno in _attribute_calls(_parsed(path)):
            if attr in mutators:
                rel = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel}:{lineno}  .{attr}(...)")

    assert offenders == [], (
        "Metis calls a ModelRegistry mutator:\n"
        + "\n".join(offenders)
        + "\n\nMetis resolves the champion (`registry.champion(task)`) and serves it. "
        "Deciding WHICH model is champion is a promotion decision with an evaluation "
        "and an audit trail behind it (themis/core/promotion.py, ADR-0041/0048). A "
        "serving path that can promote can promote itself."
    )


def test_the_recorded_finding_is_still_the_finding() -> None:
    """The docstring above makes a specific, checkable claim about the tree: Metis
    reads `themis.core.model_registry` and `themis.core.drift` in addition to the
    four type modules, contrary to the README and to ADR-0076.

    Asserted, because a finding that stops being true and stays written down is
    how the next reader is misled -- which is the failure this packet exists to
    stop. If Program E removes the registry import, this test goes red and the
    docstring gets corrected instead of rotting."""
    read: set[str] = set()
    for path in METIS_FILES:
        for module, _lineno in _imports(_parsed(path)):
            if module.startswith("themis"):
                read.add(module)

    assert "themis.core.model_registry" in read, (
        "Metis no longer imports themis.core.model_registry. The finding recorded in "
        "this module's docstring, and the exception carved in "
        "test_metis_imports_no_store_writer_or_session_from_themis, are both stale -- "
        "delete them and tighten the rule."
    )
    assert "themis.core.drift" in read, (
        "Metis no longer imports themis.core.drift; update this module's docstring"
    )
    assert read >= {
        "themis.canonical.entities",
        "themis.canonical.ids",
        "themis.canonical.time",
        "themis.canonical.vocab",
    }, f"the four type modules are no longer all read by Metis: {sorted(read)}"


# --------------------------------------------------------------------------- #
# 3. Metis authorises nothing                                                   #
# --------------------------------------------------------------------------- #


def test_metis_imports_nothing_that_decides_what_is_permitted() -> None:
    """The second half of the prohibition, and the half with no test before this
    one.

    "Authorise an operation" is not "compute that it is possible". Metis is
    supposed to say a trip is INFEASIBLE -- that is arithmetic over windows,
    capacities and travel times, and `metis/decide/feasibility.py` is exactly that.
    It is not supposed to say a request may legally move to SCHEDULED, or that an
    actor holds the permission to make an override. Those are state-machine and
    authority decisions, they live in Themis, and they are where the audit trail
    is attached."""
    offenders: list[str] = []
    for path in METIS_FILES:
        for module, lineno in _imports(_parsed(path)):
            if module in AUTHORISATION_MODULES:
                rel = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel}:{lineno}  import {module}")

    assert offenders == [], (
        "Metis reads the modules that decide what is PERMITTED:\n"
        + "\n".join(offenders)
        + "\n\nA solver that consults the state machine is one refactor from applying "
        "it. Metis proposes an assignment; Themis decides whether the request may "
        "legally move, and records who moved it. Feasibility is arithmetic and belongs "
        "here; permission is authority and does not."
    )


@pytest.mark.parametrize("module", AUTHORISATION_MODULES)
def test_the_authorisation_modules_named_here_actually_exist(module: str) -> None:
    """A deny list naming a module that has been renamed away denies nothing, and
    reads exactly like one that denies something."""
    path = REPO_ROOT / (module.replace(".", "/") + ".py")
    assert path.is_file(), (
        f"{module} is named in AUTHORISATION_MODULES but does not exist. The rule above "
        "is now partly vacuous -- find where it moved."
    )


# --------------------------------------------------------------------------- #
# 4. The checks themselves reject the case they were written for                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source,expected",
    [
        ("from themis.canonical.storage import SqliteCanonicalStore\n", "storage"),
        ("import themis.canonical.postgres_storage\n", "postgres_storage"),
        ("from themis.ontology.store import OntologyStore\n", "ontology.store"),
        ("from themis.core.feature_store import CoreDatabase\n", "feature_store"),
    ],
)
def test_the_import_check_rejects_a_store_when_it_is_shown_one(
    source: str, expected: str
) -> None:
    """Metis is clean, so nothing above ever exercises the failure path. Every
    assertion in section 1 is "the offender list is empty", and a check that can
    never populate that list satisfies all of them while proving nothing. This is
    the mutation, run against the real derived persistence surface."""
    persistence = themis_persistence_modules()
    tree = ast.parse(source)
    hit = [m for m, _ln in _imports(tree) if m in persistence]

    assert hit, f"the derived persistence surface does not contain {expected}"
    assert any(expected in m for m in hit)


def test_the_call_check_rejects_a_write_when_it_is_shown_one() -> None:
    """The channel with no import to police: a store handed in as an argument and
    duck-typed. `test_metis_calls_no_method_that_writes` is the only thing looking
    at it, so it has to be shown that it can see."""
    source = (
        "def solve(problem, store):\n"
        "    result = _optimise(problem)\n"
        "    store.append_event(tenant_id=t, payload=result)\n"
        "    return result\n"
    )
    calls = {attr for attr, _ln in _attribute_calls(ast.parse(source))}

    assert calls & WRITER_CALLS == {"append_event"}, (
        "a duck-typed store passed as an argument writes with no import to see; if this "
        "check cannot spot the call, that whole channel is unpoliced"
    )


def test_the_call_check_does_not_fire_on_ordinary_python() -> None:
    """The other direction. `list.append`, `dict.update`, `str.replace` and
    `set.add` are everywhere in a solver. A check that flagged them would be
    deleted within a week, and deleting it would be the right call."""
    source = (
        "def build(rows):\n"
        "    out = []\n"
        "    out.append(rows)\n"
        "    seen = set()\n"
        "    seen.add(1)\n"
        "    meta = {}\n"
        "    meta.update({'a': 1})\n"
        "    return ','.join(out).replace(' ', '')\n"
    )
    calls = {attr for attr, _ln in _attribute_calls(ast.parse(source))}

    assert calls & WRITER_CALLS == set()


def test_the_write_mode_check_rejects_a_write_and_permits_a_read() -> None:
    """Metis reads model artifacts and DARP instances off disk, so `open` cannot
    be banned outright -- only the modes that write. Both directions, because a
    check that refused every open would make the forecast runtime unable to load a
    champion."""
    def modes(source: str) -> list[str]:
        found = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name == "open" and node.args and len(node.args) >= 2:
                    if isinstance(node.args[1], ast.Constant):
                        found.append(node.args[1].value)
        return found

    assert any(c in m for m in modes("f = open(p, 'wb')\n") for c in "wax+")
    assert not any(c in m for m in modes("f = open(p, 'rb')\n") for c in "wax+")
