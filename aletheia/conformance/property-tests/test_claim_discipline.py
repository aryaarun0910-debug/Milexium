"""Conformance for outward-facing dollar claims (MX-CLAIMS-DOLLAR-SWEEP-013).

What these tests are actually protecting
----------------------------------------
Everything under `forge/business/ntd/` and `forge/business/outreach/` either generates a claim that is sent
to a real US transit agency, or is itself the copy that gets sent. One of them
(`forge/business/ntd/peer_position.py`) is the backend for a self-serve widget destined for a
public website, where anybody can punch in an agency and read the result. These
are not drafts. A wrong number here leaves the building.

The specific claim this file exists to keep dead is the SAVINGS claim: that an
agency's deadhead figure, or its distance from the national median, is worth $X
a year to that agency. The arithmetic behind it is fine. The diagnosis is not:

- Deadhead share does not identify an expensive agency. Pearson +0.017, OLS
  R2 0.0003, n=405 (forge/research/h5b_structure_vs_cost.json). Spearman +0.024
  against cost per trip across 406 operators, versus +0.738 for cost per HOUR,
  with cost-per-trip quartile medians flat at $48.53 (lowest deadhead quartile)
  to $54.09 (highest) -- forge/business/outreach/panel_findings.json, finding
  `dr_deadhead_predicts_cost_per_trip`, REJECTED by the panel gate on effect
  size.
- The distance to the median is not known to be recoverable. Asserting it is
  is a causal claim, and aletheia/replay/teardown.py already refuses to emit a
  savings envelope without the operator's own fixed/variable cost split. Copy
  does not get a lower standard than code.

A dollar figure that is pure arithmetic on the agency's own filing ("these
empty vehicle-hours cost $X at your own reported cost per hour") is permitted
while labelled an accounting identity whose recoverability is unknown. What is
never permitted is presenting any figure as a saving, an opportunity, or a
benefit of adopting Milexium.

The second property here is narrower and is its own class of defect: a
GENERATOR THAT REINTRODUCES A CORRECTED CLAIM. talos/tools/build_model_cards.py wrote
"validated as the right objective" and "not a production model" into
forge/knowledge/docs/MODEL_CARDS.md, both of which were corrected in the document by hand. The
next run would have silently undone the fix -- and would additionally have
deleted the ADR-0001 status paragraph, which existed only in the document and
not in the generator. So the generator is run here, into a temp path, and its
OUTPUT is checked.
"""

from __future__ import annotations

import ast
import csv
import pathlib
import re

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]
_SCANNED_TREES = ("forge/business/ntd", "forge/business/outreach")
_TEXT_SUFFIXES = {".py", ".md", ".json", ".csv", ".txt", ".yaml", ".yml"}

# Directories excluded from the sweep, each for a reason that is about
# evidence, not convenience. Anything else new under forge/business/ntd/ or forge/business/outreach/ is
# scanned by default -- the sweep opts things OUT, never in, so a file added
# tomorrow is covered without anyone remembering to add it.
_EXCLUDED_DIRS = {
    # Generated, gitignored and disposable by design (forge/business/outreach/README.md).
    # Regenerate with build_peer_insight.py + generate_v3_emails.py.
    "drafts",
    # Superseded copy kept as a record of what the outreach used to say. Erasing
    # it would destroy the evidence that the claim was made and later killed,
    # which is the same reason forge/knowledge/docs/JOURNAL.md is left alone.
    "archive",
    "__pycache__",
    "raw",
}

# Status values in forge/business/outreach/contact_research_worksheet.csv that mark a row as a
# HISTORICAL RECORD rather than live copy.
_RECORD_STATUS = re.compile(r"SENT|sent 2026|DECLINED", re.I)

# The exact organisations that were sent a dollar figure before this packet.
# Pinned by name rather than counted, because a count is satisfied by the wrong
# thirteen: an earlier version of this test asserted ">= 13 rows still carry
# the old hook" and stayed green when one sent row was quietly regenerated into
# the new wording, since a fourteenth row covered for it.
#
# Their `email_hook` is what the agency actually received. It is preserved
# verbatim and MUST stay that way -- editing a sent record so a claim test goes
# green is falsifying the record, which is strictly worse than the claim.
_SENT_A_DOLLAR_FIGURE = frozenset({
    # 3 sent 2026-07-21, v1 hook: "trimming that by even 10 percent points to
    # something like $X a year"
    "SamTrans", "Intercity Transit", "Laketran",
    # 10 sent 2026-07-24 (v3 tranche 1): "At your cost per hour the gap is
    # roughly $X a year"
    "OMNI", "Ann Arbor Area Transportation", "Transit",
    "Area Regional Transit", "City of Tallahassee",
    "Tulare County Regional Transit Agency", "Riverside Connect", "STEP",
    "Pomona Valley Transportation", "Bayway",
    # Contacted, replied with an explicit opt-out, now do_not_contact. Listed
    # here because the row still carries a dollar hook, so it is part of the
    # record even though its status is DECLINED rather than SENT.
    "Anne Arundel County",
})

# The claim patterns. Each is a phrase that presents money as recoverable, an
# opportunity, or a benefit -- not merely the presence of a "$".
_SAVINGS_CLAIM = re.compile(
    r"""
      worth\s+about\s*\$                  # "worth about $X a year to you"
    | is\s+worth\s*\$
    | \$[\d,.]+\s*(?:[MKk]\s*)?(?:a|per)\s+year\s+(?:to|in)\s+(?:you|savings)
    | (?:savings?|save[sd]?)\s+(?:of\s+)?\$
    | \$[\d,.]+\s*(?:[MKk]\s*)?(?:in|of)\s+(?:annual\s+)?savings
    | value\s+of\s+a\s+\d+\s*percent\s+deadhead
    | value_10pct_deadhead_cut
    | modelled_gap_value_usd
    | deadhead_dollars_per_yr
    | savings_calculator
    | compute_savings
    | (?:gap|deadhead)\s+is\s+roughly\s*\$   # the v3 line
    | trimming\s+that\s+by\s+even\s+\d+\s*percent
    | closing\s+(?:even\s+)?a?\s*\w*\s*of\s+that\s+gap\s+is\s+worth
    | savings\s+are\s+real\s+money
    """,
    re.I | re.X,
)


def _scanned_files() -> list[pathlib.Path]:
    out = []
    for tree in _SCANNED_TREES:
        root = _REPO / tree
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            if _EXCLUDED_DIRS & set(part.lower() for part in p.relative_to(root).parts[:-1]):
                continue
            out.append(p)
    return sorted(out)


# Prose that RETIRES a claim is not the claim. These documents deliberately
# record what was removed and why -- deleting that would destroy the evidence
# that the claim was made and later killed, which is exactly why
# forge/knowledge/docs/JOURNAL.md is left alone too.
#
# The excuse is OPT-IN and this list is the whole of it. It is deliberately not
# available to generated artifacts (forge/business/ntd/market_sizing.md,
# forge/business/outreach/targets_ntd.csv, forge/business/outreach/peer_insights.json ...), because a
# generated file never legitimately narrates its own history: anything a
# generator writes is live copy. That polarity matters -- an earlier draft of
# this test excused any hit sitting near the words "does not" or "rejected",
# and a restored $94M line in market_sizing.md slipped through it because the
# paragraph underneath happened to say the relationship was rejected.
_HISTORY_DOCS = {
    "forge/business/ntd/README.md",
    "forge/business/outreach/README.md",
    "forge/business/outreach/design_partner_pitch.md",
    "forge/business/outreach/craft_notes.md",
}
_RETIREMENT_LANGUAGE = re.compile(
    r"REMOVED|removed|no longer|used to|rejected|REJECTED|retired|gone",
)
_RETIREMENT_WINDOW = 3


def _python_emitted_strings(path: pathlib.Path) -> list[tuple[int, str]]:
    """Every string literal a module can EMIT, excluding docstrings.

    Scanning raw lines of a generator conflates two opposite things: a claim
    the code prints, and a comment explaining that the claim was deleted. The
    AST separates them exactly. Comments never reach the tree at all, and
    docstrings are dropped explicitly, so what is left is what can reach an
    agency. Multi-line implicit concatenation and f-strings are reassembled,
    which makes this STRICTER than a line scan -- the original offending copy
    was split across source lines and a line scan would have missed half of it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))

    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            out.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    parts.append(v.value)
                else:
                    parts.append("<expr>")
            out.append((node.lineno, "".join(parts)))
    return out


def _offending_lines(path: pathlib.Path) -> list[tuple[int, str]]:
    if path.suffix.lower() == ".py":
        hits = []
        for lineno, literal in _python_emitted_strings(path):
            # Newlines in a literal are formatting, not sentence boundaries.
            flat = " ".join(literal.split())
            if _SAVINGS_CLAIM.search(flat):
                hits.append((lineno, flat[:200]))
        return hits

    rel = path.relative_to(_REPO).as_posix()
    may_narrate_its_own_history = rel in _HISTORY_DOCS
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    hits = []
    for n, line in enumerate(lines, start=1):
        if not _SAVINGS_CLAIM.search(line):
            continue
        if may_narrate_its_own_history:
            lo = max(0, n - 1 - _RETIREMENT_WINDOW)
            window = "\n".join(lines[lo:n + _RETIREMENT_WINDOW])
            if _RETIREMENT_LANGUAGE.search(window):
                continue
        hits.append((n, line.strip()[:200]))
    return hits


def test_the_sweep_actually_reaches_the_files_that_matter() -> None:
    """A claim test that scans nothing passes for the wrong reason. Silence is
    not a pass -- the same rule the panel-findings gate holds itself to."""
    scanned = {p.relative_to(_REPO).as_posix() for p in _scanned_files()}
    for required in (
        "forge/business/ntd/peer_position.py",              # the public website widget
        "forge/business/ntd/build_economics.py",
        "forge/business/ntd/build_outreach_targets.py",
        "forge/business/ntd/market_sizing.md",
        "forge/business/outreach/build_contact_worksheet.py",
        "forge/business/outreach/generate_design_partner_emails.py",
        "forge/business/outreach/build_peer_insight.py",
        "forge/business/outreach/generate_v3_emails.py",
        "forge/business/outreach/peer_insights.json",
        "forge/business/outreach/design_partner_pitch.md",
        "forge/business/outreach/targets_ntd.csv",
    ):
        assert required in scanned, f"{required} is not being scanned"
    assert len(scanned) >= 20, f"only {len(scanned)} files scanned; sweep is too narrow"


def test_the_savings_calculator_is_gone_not_reworded() -> None:
    """Its entire purpose was to produce an unsupported number, so the module
    was removed rather than softened. peer_position.py replaced it and computes
    a national position instead."""
    assert not (_REPO / "forge" / "business" / "ntd" / "savings_calculator.py").exists()
    assert (_REPO / "forge" / "business" / "ntd" / "peer_position.py").exists()
    src = (_REPO / "forge" / "business" / "ntd" / "peer_position.py").read_text(encoding="utf-8")
    assert "def compare_agency" in src
    assert "def compute_savings" not in src


def test_no_artifact_emits_a_savings_or_opportunity_dollar_claim() -> None:
    offenders: list[str] = []
    for path in _scanned_files():
        rel = path.relative_to(_REPO).as_posix()
        if rel == "forge/business/outreach/contact_research_worksheet.csv":
            # Owned row-by-row by the sent-record test below, which has to tell
            # a preserved record apart from live copy. A file-level scan cannot.
            continue
        for n, line in _offending_lines(path):
            offenders.append(f"{rel}:{n}: {line}")
    assert not offenders, (
        "savings/opportunity dollar claim found in outward-facing copy:\n  "
        + "\n  ".join(offenders)
        + "\n\nA dollar figure may only appear as an accounting identity on the "
          "agency's own filing, labelled as one, stating that recoverability is "
          "unknown. Never as a saving, an opportunity, or a benefit of adopting "
          "Milexium. See forge/business/ntd/README.md."
    )


def test_the_deadhead_value_column_is_gone_from_the_economics_table() -> None:
    """`value_10pct_deadhead_cut` was the per-agency savings figure that every
    downstream hook read. Removing the column is what makes the claim
    unreachable rather than merely unwritten."""
    with open(_REPO / "forge" / "business" / "ntd" / "agency_economics.csv", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    assert "value_10pct_deadhead_cut" not in header
    # The accounting identity itself stays, and is what the honest figure is
    # computed from.
    assert "deadhead_cost" in header
    assert "cost_per_vrh" in header and "trips_per_vrh" in header


def test_the_deadhead_cost_identity_travels_with_its_caveat() -> None:
    """The one dollar figure allowed to survive is allowed ONLY while labelled.
    If the label is ever dropped, the figure becomes the claim again."""
    src = (_REPO / "forge" / "business" / "ntd" / "peer_position.py").read_text(encoding="utf-8")
    note = src[src.index("DEADHEAD_IDENTITY_NOTE"):src.index("def _load")]
    assert "Accounting identity, not a saving" in note
    assert "recoverable is unknown" in note
    market = (_REPO / "forge" / "business" / "ntd" / "market_sizing.md").read_text(encoding="utf-8")
    assert "accounting identit" in market.lower()
    assert "94,399,949" not in market, "the $94M deadhead opportunity is back"


def test_the_sent_record_is_preserved_and_not_quietly_rewritten() -> None:
    """13 agencies were sent a hedged dollar figure before this packet. Their
    hooks are deliberately left as they were: the record of what an agency
    actually received is evidence, and editing it to pass a test would be
    falsifying it. This test fails if a SENT row's hook is ever regenerated
    into the new wording, which would erase that record."""
    path = _REPO / "forge" / "business" / "outreach" / "contact_research_worksheet.csv"
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    by_name = {r["short_name"]: r for r in rows}

    missing = sorted(_SENT_A_DOLLAR_FIGURE - by_name.keys())
    assert not missing, f"rows for organisations already contacted vanished: {missing}"

    erased = sorted(
        name for name in _SENT_A_DOLLAR_FIGURE
        if not _SAVINGS_CLAIM.search(by_name[name].get("email_hook", "") or "")
    )
    assert not erased, (
        "the email_hook of an organisation that was ALREADY SENT a dollar "
        f"figure has been rewritten: {erased}. That column is the record of "
        "what they received. Cleaning up live copy must never edit it."
    )

    # ...and every row that is NOT part of that record must be clean.
    live = [
        f"{r['short_name']} [{r.get('status', '')[:40]}]: {r.get('email_hook', '')[:120]}"
        for r in rows
        if r["short_name"] not in _SENT_A_DOLLAR_FIGURE
        and _SAVINGS_CLAIM.search(r.get("email_hook", "") or "")
    ]
    assert not live, (
        "live worksheet rows still carry a savings hook:\n  " + "\n  ".join(live)
    )


# --------------------------------------------------------------------------
# generators that reintroduce a corrected claim
# --------------------------------------------------------------------------


def _generated_model_cards(tmp_path: pathlib.Path) -> str:
    """Run talos/tools/build_model_cards.py for real, into a temp path.

    Checking the SOURCE for banned strings would be weaker: the claim can be
    assembled from fragments, or restored from a JSON field. What ships is the
    output, so the output is what is asserted on.
    """
    out = tmp_path / "MODEL_CARDS.md"
    src = (_REPO / "talos" / "tools" / "build_model_cards.py").read_text(encoding="utf-8")
    marker = 'OUT = ROOT / "forge" / "knowledge" / "docs" / "MODEL_CARDS.md"'
    assert marker in src, "build_model_cards.py output path moved; update this test"
    src = src.replace(marker, f"OUT = __import__('pathlib').Path(r'{out}')")
    exec(compile(src, "build_model_cards.py", "exec"),
         {"__file__": str(_REPO / "talos" / "tools" / "build_model_cards.py"),
          "__name__": "__main__"})
    return out.read_text(encoding="utf-8")


@pytest.mark.skipif(
    not (_REPO / "data" / "curated" / "metrics_real.json").exists(),
    reason="committed data/curated metrics absent",
)
def test_the_model_card_generator_cannot_reintroduce_a_banned_claim(tmp_path) -> None:
    generated = _generated_model_cards(tmp_path)

    # The status contract is the ONE place the vocabulary is legitimately used,
    # because stating the prohibition requires naming it. Everything else is
    # a capability claim.
    body = "\n".join(
        line for line in generated.splitlines()
        if not line.startswith("**Status: Demonstrated, never Validated.**")
    )
    for banned in ("validated", "Validated"):
        assert banned not in body, (
            f"talos/tools/build_model_cards.py regenerated the word {banned!r} into "
            "forge/knowledge/docs/MODEL_CARDS.md outside the status contract. ADR-0001 reserves "
            "it for consented operator data against a declared baseline; "
            "Milexium has none."
        )
    assert "it is R&D evidence and is not shipped" in generated
    assert "not a production model: nothing here is deployed" in generated


@pytest.mark.skipif(
    not (_REPO / "data" / "curated" / "metrics_real.json").exists(),
    reason="committed data/curated metrics absent",
)
def test_the_generator_carries_the_status_contract_it_used_to_delete(tmp_path) -> None:
    """The ADR-0001 status paragraph existed only in forge/knowledge/docs/MODEL_CARDS.md, so
    every regeneration deleted it. A claim that only exists in generated output
    has to be owned by the generator."""
    generated = _generated_model_cards(tmp_path)
    assert "**Status: Demonstrated, never Validated.**" in generated
    assert "consented operator data against a declared baseline" in generated
