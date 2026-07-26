"""Argus invents no fact, constraint, reason or recommendation -- MX-ARCH-PROHIBITIONS-016.

    | Argus | must never invent a fact, constraint, reason or recommendation |

WRITTEN BEFORE THE LAYER EXISTS, ON PURPOSE.
ADR-0076 recorded this as the prohibition with no test and the one most likely to
be violated, "because that is where an LLM will eventually sit". When this file
was started, `argus/` was a FastAPI app, a Python SDK, a generated TypeScript SDK
and a demo -- about 3,500 lines with no generation in any of it.

A prohibition added after the thing it prohibits has arrived is negotiated
against working code; one that is already there is a constraint the new code is
written to. The tests below are thin -- they have a thin surface to bind -- and
they fail when violated, which is the only property that matters at this stage.

`argus/command_centre/` LANDED WHILE THIS WAS BEING WRITTEN, and it carries the
runtime half of the same idea: `command_centre/attribution.py` makes a `Figure`
impossible to construct without a `Source`, over a closed set of origins, with
attribution following the weakest input. That is a stronger guarantee than
anything here for the values that pass through it, and it is not duplicated.

The two are complements, not alternatives, and the difference is worth being
precise about: `attribution.py` binds values that go through `Figure`, at run
time, in the module that chose to use it. This file binds the API and SDK
surfaces structurally, whether or not the author opted in -- which is the half
that still holds when the next surface is written by someone who has not read
`attribution.py`. Neither subsumes the other, and the command centre's own
internals are NOT asserted here (see WHAT IS NOT COVERED).

THE PROPERTY: EVERY VALUE ARGUS RENDERS IS READ OFF SOMETHING IT WAS HANDED.
Argus is the operator's window. What makes the window trustworthy is not that it
is accurate; it is that it has no opinions -- every number, every reason code,
every column name in a response came off an object built by Themis, Metis or
Aletheia, and can be followed back to the row or the artifact that produced it.
A value composed in the API layer has no such trail: it looks identical to one
that has, and no amount of downstream verification recovers the difference.

So the mechanisable form is: at every construction of an operator-facing response
model, the value of each field is an expression rooted in something the function
was given. Not a string literal Argus wrote. Not a number Argus computed from
constants. Not an f-string. `test_every_value_the_api_renders_is_read_off_something_it_was_handed`
is that rule.

FOUR GUARDS FOR THE LAYER THAT HAS NOT ARRIVED YET, and they are the point of
writing early:

  * `test_argus_holds_no_text_generator` -- the day someone adds `import
    anthropic` to `argus/`, this goes red. That is not a refusal of the idea; it
    is a demand that whoever does it comes back and extends the traceability rule
    to cover what the generator emits, because a generated sentence is exactly a
    fact, constraint, reason or recommendation with no source id behind it. Two
    weaker siblings sit beside it, kept SEPARATE so the strong rule cannot be
    relaxed by arguing about the weak one: no model or solver of Argus's own, and
    no numeric library (which is the broadest claim here and is labelled as the
    one most likely to have a legitimate reason to move).
  * `test_argus_draws_no_unseeded_randomness` -- an unseeded draw makes the demo
    unreproducible, and reproducibility is the product.
  * `test_argus_defines_no_vocabulary_of_its_own` -- a second ReasonCode enum in
    the API is how a denial reason drifts out of the ledger's vocabulary.
  * `test_the_operator_facing_vocabularies_are_the_themis_objects_not_argus_copies`
    -- the column list and PII categories a validation response advertises are
    the SAME objects `themis.connect` enforces against, by identity, not a copy
    that agrees today.

WHAT IS NOT COVERED, and it is a lot -- do not read this file as more than it is:

  * **The demo's narrative prose is not checked.** `argus/demo/walkthrough.py`
    composes sentences from figures it measured (e.g. the `unmeasured_reason` at
    walkthrough.py:1052 is an f-string over two counts). Those sentences ARE
    traceable -- every number in them came from the data -- but nothing here
    proves that, and an f-string is not a structure a test can follow. If the
    demo ever states a figure it did not measure, this file will not catch it;
    `test_claim_discipline.py` polices the vocabulary of published claims and is
    the nearest thing there is.
  * **`argus/command_centre/` is walked but barely touched.** The two whole-layer
    guards below (no generator, no unseeded draw, no vocabulary of its own) DO
    cover it. The claim-field rule finds nothing there, because the command centre
    routes its values through `Figure`/`Source` rather than through keyword
    arguments named `reason` -- so its attribution is enforced by its own types
    and by its own packet's tests, not by this file. Nothing here is pinned to its
    internals deliberately: it is under active construction, and a conformance
    file that named its types would break on every rename for no gain.
  * **The TypeScript SDK is not walked** -- it is generated from the OpenAPI
    contract and `test_api_contract_drift.py` gates it.
  * **Nothing proves the values Argus passes through are CORRECT.** That is the
    layers beneath, and it is what `aletheia/` exists for. This file proves only
    that Argus did not make them up.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ARGUS = REPO_ROOT / "argus"
API_APP = ARGUS / "api" / "app.py"
SDK_CLIENT = ARGUS / "sdk" / "client.py"

# --------------------------------------------------------------------------- #
# The vocabulary of invention                                                   #
# --------------------------------------------------------------------------- #

TEXT_GENERATORS = frozenset(
    {
        "anthropic", "openai", "cohere", "vertexai", "llama_cpp",
        "transformers", "langchain", "llama_index", "ollama", "mistralai",
    }
)
"""The layer this file was written ahead of. A language model emits sentences on
demand, and a sentence on demand IS a fact, a constraint, a reason or a
recommendation with nothing behind it. The strongest of the three rules below."""

MODELS_AND_SOLVERS = frozenset(
    {
        "xgboost", "sklearn", "lightgbm", "catboost", "torch", "tensorflow",
        "ortools", "pulp", "cvxpy", "z3",
    }
)
"""A forecast reaches Argus through `metis.forecast` and a schedule through
`metis.decide`. Behind those sit a model registry, a version, a vintage, a
conformal interval and a drift monitor. A model or solver loaded HERE produces a
number with none of them -- a second opinion that looks exactly like the governed
one on the page."""

NUMERIC_LIBRARIES = frozenset({"numpy", "pandas", "scipy"})
"""THE WEAKEST OF THE THREE, and separated so it cannot borrow the others'
authority.

These are not generators. Banning them asserts something broader -- that Argus
performs no computation of its own -- which happens to be true today: the demo
builds its feature dicts with `math.sin`, the command centre routes every figure
through `metis`, and no module under `argus/` imports any of the three.

It is here because an aggregate computed in the presentation layer is a number
with no artifact behind it, which is the prohibition in its quietest form -- a
mean is a claim. But reshaping data for a chart is a real need with an honest
answer, so this rule is the one most likely to have a legitimate reason to move,
and its failure message says so rather than pretending otherwise."""

RANDOM_MODULE_FUNCTIONS = frozenset(
    {
        "random", "randint", "randrange", "choice", "choices", "sample",
        "shuffle", "uniform", "gauss", "normalvariate", "betavariate",
        "triangular", "getrandbits", "seed",
    }
)
"""Called on the `random` MODULE these draw from a process-global generator whose
seed nobody stated. Called on a `random.Random(seed)` instance they are
reproducible, and `argus/demo/walkthrough.py` does exactly that."""

CLAIM_FIELDS = frozenset(
    {
        "reason", "reasons", "reason_code", "reason_codes", "unmeasured_reason",
        "recommendation", "recommendations", "rationale", "explanation",
        "justification", "cause", "confidence", "probability", "score",
        "saving", "savings", "roi", "constraint", "constraints",
        "failed_constraints", "interpretation",
    }
)
"""The four things the prohibition names, in the shapes they take as field names.

`detail` is deliberately NOT here. It is the FastAPI `HTTPException` field, and
every f-string in it describes the REQUEST -- a body over a size ceiling, an
aggregate with no history -- not the operator's data. Excluding the name is
honest; the one `detail` that reaches a response model (`VerifyViolation.detail`)
is covered by the traceability rule below, where it is read off the violation
object."""

# The operator-facing response models. Every one of these is something an
# operator or an auditor reads as a statement about their service.
DOMAIN_RESPONSE_MODELS = frozenset(
    {
        "RecordedEvent",
        "VerifyViolation",
        "VerifyResponse",
        "SemanticLossNote",
        "RowValidation",
        "OperatorExportValidationResponse",
    }
)

META_RESPONSE_MODELS = {
    "HealthResponse": (
        "liveness. `status='ok'` is a statement about the PROCESS, not about the "
        "operator's data, and there is nothing beneath Argus that could source it."
    ),
    "VersionResponse": (
        "the API, SDK and contract version strings. Argus is the thing being "
        "versioned, so it is the correct source for its own version."
    ),
}


# --------------------------------------------------------------------------- #
# Walkers                                                                       #
# --------------------------------------------------------------------------- #


def _argus_files() -> tuple[Path, ...]:
    return tuple(
        p for p in sorted(ARGUS.rglob("*.py")) if "__pycache__" not in p.parts
    )


@lru_cache(maxsize=None)
def _parsed(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


ARGUS_FILES = _argus_files()


def _top_level_imports(tree: ast.Module) -> tuple[tuple[str, int], ...]:
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((a.name.split(".")[0], node.lineno) for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.append((node.module.split(".")[0], node.lineno))
    return tuple(out)


def _invented_constants(value: ast.AST) -> list[str]:
    """The literals in one expression that would be Argus's own invention.

    A non-empty STRING is content: a reason, a status, a label an operator reads.
    A FLOAT is a measurement or a rate, and Argus measures nothing. An f-string is
    both, assembled. Those are refused.

    `None`, `True`, `False` and integers are NOT. `None` is absence -- `reason=None
    if quarantine is None else quarantine.reason` says "there was no quarantine",
    which is a fact about the data, not a claim about it. A bare integer appears as
    a comparison operand (`len(violations) == 0`) or an index; it carries no
    content on its own. A bare integer that IS the whole value is refused
    separately below, because `rows_checked=0` would be a count nobody counted.
    """
    bad: list[str] = []
    for node in ast.walk(value):
        if isinstance(node, ast.JoinedStr):
            bad.append("f-string")
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, str) and node.value != "":
                bad.append(f"string {node.value[:40]!r}")
            elif isinstance(node.value, float):
                bad.append(f"float {node.value!r}")
    if isinstance(value, ast.Constant) and isinstance(value.value, (int, float)) and not isinstance(
        value.value, bool
    ):
        bad.append(f"bare number {value.value!r}")
    return bad


def _domain_model_constructions(tree: ast.Module) -> list[tuple[int, str, ast.keyword]]:
    """Every keyword argument at every construction of an operator-facing model.

    Covers both spellings: `RowValidation(...)` by name, and `cls(...)` inside a
    classmethod of one of the models (`RecordedEvent.from_event`).
    """
    found: list[tuple[int, str, ast.keyword]] = []

    def collect(call: ast.Call, model_name: str) -> None:
        for kw in call.keywords:
            if kw.arg is None:  # **kwargs -- opaque, reported by the caller
                continue
            found.append((call.lineno, model_name, kw))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in DOMAIN_RESPONSE_MODELS:
                collect(node, node.func.id)

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in DOMAIN_RESPONSE_MODELS:
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id == "cls"
                ):
                    collect(inner, node.name)
    return found


# --------------------------------------------------------------------------- #
# 0. Not vacuous                                                                #
# --------------------------------------------------------------------------- #


def test_the_walker_is_looking_at_argus_and_not_at_an_empty_set() -> None:
    """Every assertion in this file has the shape "nothing in argus does X", and
    all of them pass over an empty file list."""
    assert (REPO_ROOT / "pyproject.toml").is_file(), f"REPO_ROOT is wrong: {REPO_ROOT}"
    assert len(ARGUS_FILES) >= 8, (
        f"only {len(ARGUS_FILES)} modules found under argus/; the walker is looking in "
        "the wrong place and every assertion below is vacuous"
    )
    assert API_APP.is_file() and SDK_CLIENT.is_file()


def test_the_response_models_named_here_still_exist() -> None:
    """A traceability rule keyed on model names that have been renamed away
    inspects nothing, and reads exactly like one that inspects everything."""
    declared = {
        node.name
        for node in ast.walk(_parsed(API_APP))
        if isinstance(node, ast.ClassDef)
    }
    missing = sorted((DOMAIN_RESPONSE_MODELS | set(META_RESPONSE_MODELS)) - declared)

    assert missing == [], (
        f"these response models no longer exist in argus/api/app.py: {missing}. Until "
        "the lists here are updated, the traceability rule is silently skipping them."
    )


def test_every_response_model_is_classified_as_operator_facing_or_meta() -> None:
    """A new response model must be put on one side of the line deliberately. The
    default is not "meta" -- there is no default."""
    responses = {
        node.name
        for node in ast.walk(_parsed(API_APP))
        if isinstance(node, ast.ClassDef) and node.name.endswith(("Response", "Event", "Validation", "Note", "Violation"))
    }
    unclassified = sorted(responses - DOMAIN_RESPONSE_MODELS - set(META_RESPONSE_MODELS))

    assert unclassified == [], (
        f"these response models are neither operator-facing nor declared meta: "
        f"{unclassified}. Add them to DOMAIN_RESPONSE_MODELS (every field must be read "
        "off something handed in) or to META_RESPONSE_MODELS with the reason written "
        "down -- a model that describes the PROCESS rather than the operator's data is "
        "the only thing that belongs there."
    )


def test_every_meta_exemption_states_a_reason() -> None:
    """A response model exempted from the traceability rule with no reason written
    beside it is a hole nobody will find on the way past."""
    for name, reason in META_RESPONSE_MODELS.items():
        assert len(reason) > 40, f"{name} is exempt with no reason recorded"


# --------------------------------------------------------------------------- #
# 1. Every rendered value is read off something Argus was handed                 #
# --------------------------------------------------------------------------- #


def test_every_value_the_api_renders_is_read_off_something_it_was_handed() -> None:
    """THE RULE.

    At every construction of an operator-facing response, each field's value must
    be an expression over things the function received -- a parameter, a local
    holding what a call returned, a constant imported from the layer that owns it.
    Never a string Argus wrote, never a number Argus picked, never an f-string.

    The difference matters because it is invisible in the response. An operator
    reading `reason: "vehicle capacity exhausted"` cannot tell whether that came
    off a `ReasonCode` in the ledger or was assembled by the API because it seemed
    like the likely explanation. One is evidence; the other is a guess wearing
    evidence's clothes, and this is the layer where that substitution is easiest
    to make and hardest to notice."""
    offenders: list[str] = []
    keywords_checked = 0

    for path in ARGUS_FILES:
        for lineno, model, kw in _domain_model_constructions(_parsed(path)):
            keywords_checked += 1
            invented = _invented_constants(kw.value)
            if invented:
                offenders.append(
                    f"{_rel(path)}:{lineno}  {model}({kw.arg}={ast.unparse(kw.value)[:70]})"
                    f"\n      composed here rather than read off an input: {invented}"
                )

    assert keywords_checked >= 20, (
        f"only {keywords_checked} response fields were inspected. The construction "
        "sites have moved and this rule is now checking almost nothing -- which is "
        "how it would keep passing while the layer it guards was rewritten."
    )
    assert offenders == [], (
        "Argus composed a value instead of reading one:\n"
        + "\n".join(offenders)
        + "\n\nArgus is the operator's window, and what makes a window trustworthy is "
        "that it has no opinions. Every value in a response has to be followable back "
        "to the row, the artifact or the vocabulary that produced it. If the value "
        "genuinely does not exist below this layer, that is not a reason to write it "
        "here -- it is the finding."
    )


def test_no_claim_shaped_field_anywhere_in_argus_is_handed_a_literal() -> None:
    """The same rule, narrowed to the four words in the prohibition and widened to
    the whole of `argus/` -- the SDK and the demo included, not just the API.

    A reason, a recommendation, a rationale or a confidence assembled in the
    presentation layer is the prohibition's own example. This catches it at any
    call site, in any module here, whether or not the receiving type is one of the
    response models above."""
    offenders: list[str] = []
    claims_checked = 0

    for path in ARGUS_FILES:
        for node in ast.walk(_parsed(path)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            callee = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if callee == "HTTPException":
                continue  # see CLAIM_FIELDS -- an HTTP status describes the request
            for kw in node.keywords:
                if kw.arg not in CLAIM_FIELDS:
                    continue
                claims_checked += 1
                literal = [
                    bad
                    for bad in _invented_constants(kw.value)
                    if bad.startswith(("string", "f-string", "float", "bare number"))
                ]
                if literal:
                    offenders.append(
                        f"{_rel(path)}:{node.lineno}  {callee}({kw.arg}="
                        f"{ast.unparse(kw.value)[:70]})  -> {literal}"
                    )

    assert claims_checked >= 8, (
        f"only {claims_checked} claim-shaped arguments found in argus/ (12 today, "
        "spread across argus/api, argus/sdk and argus/demo); CLAIM_FIELDS has drifted "
        "out of step with the code and this rule now checks almost nothing"
    )
    assert offenders == [], (
        "Argus wrote a reason, a recommendation or a confidence of its own:\n"
        + "\n".join(offenders)
        + "\n\nThe reason a request was denied lives in the ledger as a ReasonCode the "
        "solver returned. The reason an export row was quarantined lives on the "
        "adapter's own quarantine record. Argus repeats them; it does not supply one "
        "when the layers beneath left the field empty -- a denial with no reason is "
        "reported as having no reason, which is the demo's best moment and not a gap "
        "to be filled in here."
    )


def test_the_traceability_check_rejects_an_invented_value_when_it_is_shown_one() -> None:
    """The mutation. Every assertion above is "the offender list is empty", which a
    check that never returns anything satisfies. `argus/api/app.py` is clean, so
    nothing else here exercises the failure path."""
    invented = ast.parse(
        "RowValidation(\n"
        "    row_index=index,\n"
        "    accepted=True,\n"
        "    reason='likely a capacity constraint',\n"
        "    confidence=0.87,\n"
        "    failed_field=f'{column} looks wrong',\n"
        "    semantic_loss=(),\n"
        "    pii_rejection=False,\n"
        "    pii_columns=(),\n"
        ")\n"
    )
    flagged = {
        kw.arg
        for _lineno, _model, kw in _domain_model_constructions(invented)
        if _invented_constants(kw.value)
    }

    assert flagged == {"reason", "confidence", "failed_field"}, (
        f"the check flagged {sorted(flagged)}; it must catch the composed string, the "
        "invented confidence and the f-string, and must NOT flag the structural "
        "True/False or the empty tuples"
    )


def test_the_traceability_check_accepts_the_shapes_a_pass_through_actually_uses() -> None:
    """The other direction, and the more important one: a rule that fired on
    ordinary pass-through code would be turned off within a week.

    Every shape here appears in `argus/api/app.py` today -- a comparison against
    zero, a conditional on absence, a comprehension over an input, a constant
    imported from the layer that owns it."""
    honest = ast.parse(
        "VerifyResponse(\n"
        "    aggregate_id=aggregate_id,\n"
        "    verified=len(violations) == 0,\n"
        "    violations=tuple(\n"
        "        VerifyViolation(aggregate_id=v.aggregate_id, sequence=v.sequence,\n"
        "                        kind=v.kind, detail=v.detail)\n"
        "        for v in violations\n"
        "    ),\n"
        ")\n"
        "RowValidation(\n"
        "    row_index=index,\n"
        "    accepted=quarantine is None,\n"
        "    reason=None if quarantine is None else quarantine.reason,\n"
        "    pii_columns=tuple(sorted(str(c) for c, v in row.items() if v == REDACTION_MARKER)),\n"
        ")\n"
    )
    flagged = {
        (model, kw.arg)
        for _lineno, model, kw in _domain_model_constructions(honest)
        if _invented_constants(kw.value)
    }

    assert flagged == set(), f"the rule fires on honest pass-through code: {sorted(flagged)}"


# --------------------------------------------------------------------------- #
# 2. The SDK passes through; it does not decide                                 #
# --------------------------------------------------------------------------- #


def test_the_sdk_returns_nothing_it_composed_itself() -> None:
    """`MilexiumClient` is the Python surface, and `argus/api/app.py` is described
    in its own docstring as "pure composition over it". So the SDK is where an
    invented value would do the most damage: it would reach the HTTP layer looking
    exactly like a value from the store.

    Every public method must return an expression rooted in something -- a call
    into the layers beneath, a parameter, an attribute. A bare literal return is a
    value with no origin."""
    tree = _parsed(SDK_CLIENT)
    offenders: list[str] = []
    returns_checked = 0

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "MilexiumClient":
            continue
        for method in node.body:
            if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if method.name.startswith("_"):
                continue
            for stmt in ast.walk(method):
                if not isinstance(stmt, ast.Return) or stmt.value is None:
                    continue
                returns_checked += 1
                grounded = any(
                    isinstance(n, (ast.Name, ast.Attribute, ast.Call))
                    for n in ast.walk(stmt.value)
                )
                composed = isinstance(stmt.value, ast.JoinedStr) or (
                    isinstance(stmt.value, ast.Constant)
                    and stmt.value.value is not None
                )
                if composed or not grounded:
                    offenders.append(
                        f"{_rel(SDK_CLIENT)}:{stmt.lineno}  {method.name} -> "
                        f"{ast.unparse(stmt.value)[:70]}"
                    )

    assert returns_checked >= 8, (
        f"only {returns_checked} public returns inspected on MilexiumClient; the class "
        "has moved and this rule is checking almost nothing"
    )
    assert offenders == [], (
        "the SDK returns a value it made up rather than one it was given:\n"
        + "\n".join(offenders)
    )


# --------------------------------------------------------------------------- #
# 3. Guards for the layer that has not arrived yet                              #
# --------------------------------------------------------------------------- #


def _imports_of_any(banned: frozenset[str]) -> list[str]:
    offenders: list[str] = []
    for path in ARGUS_FILES:
        for top, lineno in _top_level_imports(_parsed(path)):
            if top in banned:
                offenders.append(f"{_rel(path)}:{lineno}  import {top}")
    return offenders


def test_argus_holds_no_text_generator() -> None:
    """THE FORWARD GUARD, and the reason this file was written before the layer.

    A language model inside `argus/` produces content on demand, and content
    produced on demand is a fact, a constraint, a reason or a recommendation with
    nothing behind it. That is the prohibition, verbatim.

    This is NOT a refusal of the idea. It is a demand that adding one is a
    deliberate act, with the traceability rule extended to cover what it emits,
    rather than an import nobody reviewed."""
    offenders = _imports_of_any(TEXT_GENERATORS)

    assert offenders == [], (
        "Argus has acquired the ability to write sentences of its own:\n"
        + "\n".join(offenders)
        + "\n\nIf this is deliberate -- and it will be, one day -- then before it "
        "lands: every value the generator emits needs a source id it can be followed "
        "back to, and `test_every_value_the_api_renders_is_read_off_something_it_was_handed` "
        "has to be extended to cover that path. A generated sentence in an operator's "
        "denial explanation is the single most expensive thing this repository could "
        "ship: it is indistinguishable from a real one, and there is no artifact behind "
        "it. Deleting this test instead of extending that one is how it would happen."
    )


def test_argus_holds_no_model_and_no_solver_of_its_own() -> None:
    """A forecast reaches Argus through `metis.forecast`, and a schedule through
    `metis.decide`. Behind those sit a registry, a version, a vintage, a conformal
    interval and a drift monitor -- the machinery that makes a number quotable.

    A model or solver loaded here produces a number with none of it, rendered on
    the same page, in the same typeface, as one that has all of it."""
    offenders = _imports_of_any(MODELS_AND_SOLVERS)

    assert offenders == [], (
        "Argus holds a model or a solver of its own:\n"
        + "\n".join(offenders)
        + "\n\nWhatever it computes should be computed in metis, where it acquires a "
        "model version and a drift monitor, and handed to Argus to render. If the "
        "computation genuinely belongs to the presentation layer, that is worth an ADR, "
        "because it is the first number on the page with no artifact behind it."
    )


def test_argus_computes_nothing_of_its_own_with_a_numeric_library() -> None:
    """The weakest of the three import rules, and labelled as such so it cannot
    borrow the other two's authority.

    numpy, pandas and scipy are not generators. What this asserts is broader --
    that Argus performs no computation of its own -- and it is true today: the
    demo builds its feature dicts with `math.sin`, the command centre routes every
    figure through metis, and no module under `argus/` imports any of the three.

    It is worth holding because an aggregate computed in the presentation layer is
    the prohibition in its quietest form: a mean is a claim, and a mean taken here
    has no artifact behind it. But reshaping data for a chart is a real need, so of
    everything in this file this is the rule most likely to have a legitimate
    reason to move."""
    offenders = _imports_of_any(NUMERIC_LIBRARIES)

    assert offenders == [], (
        "Argus has acquired a numeric library:\n"
        + "\n".join(offenders)
        + "\n\nBefore relaxing this -- and it may well be the right call, it is the "
        "weakest rule here -- check what it is for. RESHAPING a value that metis or "
        "aletheia already computed, so it can be plotted, does not invent anything and "
        "is a fair reason to move this rule. COMPUTING a new figure here does: the "
        "result reaches the operator with no model version, no artifact and no source "
        "id, sitting next to figures that have all three."
    )


def test_argus_draws_no_unseeded_randomness() -> None:
    """`argus/demo/walkthrough.py` shuffles a drift reference window, and does it
    through `random.Random(DRIFT_SPLIT_SEED)` -- reproducible, and the seed is a
    named constant. A module-level `random.shuffle(...)` would look identical at
    the call site and make the demo's numbers different on every run.

    The demo ends by verifying itself. A figure that changes between runs cannot
    be verified by anyone, including us."""
    offenders: list[str] = []
    for path in ARGUS_FILES:
        for node in ast.walk(_parsed(path)):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            receiver = node.func.value
            if isinstance(receiver, ast.Name) and receiver.id in ("random", "secrets"):
                if node.func.attr in RANDOM_MODULE_FUNCTIONS or receiver.id == "secrets":
                    offenders.append(
                        f"{_rel(path)}:{node.lineno}  {ast.unparse(node)[:70]}"
                    )

    assert offenders == [], (
        "Argus draws from a generator whose seed nobody stated:\n"
        + "\n".join(offenders)
        + "\n\nUse `random.Random(SOME_NAMED_SEED)` and name the constant, as "
        "argus/demo/walkthrough.py already does. The demo's value is that its numbers "
        "can be reproduced and checked; an unseeded draw removes that silently."
    )


def test_the_randomness_check_can_tell_a_seeded_generator_from_the_global_one() -> None:
    """The mutation, both ways. The real tree uses only the seeded form, so nothing
    above exercises the failure path -- and a check that flagged the seeded form
    too would be a permanent red on correct code."""

    def offenders(source: str) -> list[str]:
        out = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                receiver = node.func.value
                if isinstance(receiver, ast.Name) and receiver.id in ("random", "secrets"):
                    if node.func.attr in RANDOM_MODULE_FUNCTIONS or receiver.id == "secrets":
                        out.append(ast.unparse(node))
        return out

    assert offenders("random.shuffle(rows)\n") == ["random.shuffle(rows)"]
    assert offenders("x = random.uniform(0, 1)\n")
    assert offenders("token = secrets.token_hex(8)\n")
    assert offenders("random.Random(DRIFT_SPLIT_SEED).shuffle(rows)\n") == [], (
        "the seeded form is the CORRECT one and is in use today; flagging it would "
        "make this rule the first thing anyone deletes"
    )


def test_argus_defines_no_vocabulary_of_its_own() -> None:
    """The words an operator sees -- reason codes, mobility aids, request states --
    are Themis's, because Themis governs what is permissible to say. A second
    vocabulary in the presentation layer starts identical and drifts, and the
    drift is invisible: the API keeps returning plausible strings that no longer
    correspond to anything in the ledger."""
    offenders: list[str] = []
    for path in ARGUS_FILES:
        for node in ast.walk(_parsed(path)):
            if not isinstance(node, ast.ClassDef):
                continue
            for base in node.bases:
                name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", None)
                if name in ("Enum", "StrEnum", "IntEnum", "Flag", "IntFlag"):
                    offenders.append(f"{_rel(path)}:{node.lineno}  class {node.name}({name})")

    assert offenders == [], (
        "Argus defines a closed vocabulary of its own:\n"
        + "\n".join(offenders)
        + "\n\nImport it from themis.canonical.vocab. If the word you need is not there, "
        "that is a gap in the governed vocabulary and it is Themis's to close -- adding "
        "it here means the ledger and the screen can disagree about what happened."
    )


def test_the_operator_facing_vocabularies_are_the_themis_objects_not_argus_copies() -> None:
    """Traceability at runtime rather than in the syntax tree.

    `POST /operator-exports/validate` tells an operator which columns Milexium
    accepts and which categories it refuses. Those two lists MUST be the same
    objects `themis.connect.operator_export` enforces against -- not a copy that
    happens to agree today, because a copy that drifts tells the operator to send
    a column the adapter will quarantine, and the operator has no way to know
    which of the two was right.

    Asserted by identity (`is`), not equality. Equality would still pass the day
    someone inlines the tuple, which is exactly the change that creates the second
    copy."""
    from argus.api.app import OperatorExportValidationResponse
    from themis.connect.operator_export import CANONICAL_COLUMNS, PII_CATEGORIES

    fields = OperatorExportValidationResponse.model_fields

    assert fields["canonical_columns"].default is CANONICAL_COLUMNS, (
        "the column list the API advertises is no longer the object the adapter "
        "enforces. Two lists, one operator, and nothing to say which is authoritative."
    )
    assert fields["pii_categories"].default is PII_CATEGORIES, (
        "the PII category list the API advertises is no longer the object the adapter "
        "refuses on."
    )


def test_the_response_that_promises_nothing_was_stored_cannot_claim_otherwise() -> None:
    """The one claim Argus makes about itself rather than about the data, and the
    only kind it is entitled to make: `persisted` is a statement about what THIS
    endpoint did, and the model refuses to carry a true value for it.

    Included here because it is the shape the whole file argues for -- a claim
    that cannot be made is better than one that is merely not made."""
    from pydantic import ValidationError

    from argus.api.app import OperatorExportValidationResponse

    with pytest.raises(ValidationError, match="stores nothing"):
        OperatorExportValidationResponse(
            rows_checked=0, accepted=0, quarantined=0, pii_rejected=0,
            persisted=True, results=(),
        )
