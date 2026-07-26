# ADR-0075: Reorganising by concern

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-REPO-REORG-014

## Context

23 flat top-level directories with four different concerns adjacent to each
other: the product, the proof it works, the business, and research. Nothing at
the root told a reader which was which.

## Decision

Ten meaningful directories, grouped by concern:

```
app/         the product      canonical connect core decide estate evidence
                              forecast ontology replay sdk sdk-typescript verify api
platform/    delivery         infra ops contracts tools
evidence/    the proof        conformance benchmarks artifacts
knowledge/   the record       architecture docs workstreams
business/    go-to-market     outreach ntd reference_agency
_legacy/     kept, not used   kaggle third_party crates
data/ realdata/ research/ demo/                                    unchanged
```

`realdata/` deliberately stays put: its paths are pinned in the evidence registry
and read directly by the forecast, leakage and teardown suites. **`_legacy/`
means moved, not removed** — `_legacy/kaggle/` still holds the transfer-learning
work whose *negative* results were deliberately kept as evidence.

All 493 files moved with `git mv`, staged as **pure renames: 0 insertions, 0
deletions**, so history follows the files.

## Consequences

**2688 passed, 1 skipped** before and after, measured on the same tree, and
independently re-verified by the orchestrator. Demo runs in 1.9 s and its pack
re-derives (76 checks, 0 mismatches). Contract-drift output byte-identical; SDK
type-drift sha256 unchanged; TS 19/19; `cargo metadata` resolves; evidence
registry re-derives exactly; 139 markdown files, 0 broken links.

*(The packet brief said the baseline was 2,689. The agent measured 2,688 before
touching anything — the gap predates the move and comes from a different commit
in the briefing snapshot. It reported what it measured on both sides of the same
tree, which is the right answer.)*

### `platform` collides with the standard library

`platform/tools` can **never** be importable as `platform.tools` — `import
platform` resolves to `Lib/platform.py`, so the dotted path fails with *"'platform'
is not a package"*. Verified empirically that a bare `platform/` directory does
not shadow the stdlib: a directory without `__init__.py` is only a namespace
portion, and a real module later on `sys.path` still wins.

Resolved with `pythonpath = [".", "evidence", "platform"]`, which also keeps
`conformance.*` module identity byte-identical. **Consequence created and named
rather than hidden:** `contracts`, `infra`, `ops`, `artifacts` and `benchmarks`
are now importable top-level names under pytest. Nothing imports them; it is a
small new shadowing surface.

### The failure that would have been silent

Every tree that gained a level had repo-root-relative path arithmetic pointing
one level short — 42 `parents[2]`→`parents[3]` across conformance, plus
`platform/tools`, `contracts/generate.py`, benchmarks, and four outreach scripts.

Most would have failed loudly. **One would not**:
`business/ntd/fetch_census_latent_demand.py` loaded `.env` via
`HERE.parent / ".env"`, which after the move resolves to `business/.env` — so it
would have found no Census key and simply **fetched nothing**, silently.

Also invisible to any `packages/` grep: **70 bare quoted path segments**
(`_REPO / "packages" / "canonical"`), fixed individually with match-count
assertions so a silent miss was impossible.

### Remaining old-path references: 353, each justified

154 in `JOURNAL.md` and 11 in `docs/archive/` — **deliberately not rewritten**,
because those are append-only dated records and rewriting them destroys the
evidence of what was true when. 184 in the 2026-07-21 knowledge-graph snapshot,
same reasoning (and that graph is 145 commits stale and due for regeneration).
Four are prose, not paths — including two inside strings that **ship in emitted
evidence packs**, where a rewrite would have been a behaviour change.

## Bugs found and deliberately not fixed

1. **CI does not run its own declared test scope.** The workflow runs
   `pytest app/ evidence/conformance/`, which overrides `testpaths` — so
   `realdata`, `business/ntd`, `business/reference_agency` and `platform/tools`
   are never exercised there. Harmless today (no test files), but **the first
   test added to any of them will be green by omission.** The path was corrected
   and the scope left exactly as it was; widening it is a CI-policy change, not a
   move.
2. **The build-machine-path leak check is weak by construction** — it greps for a
   directory literal, so it only catches leaks from a checkout in a directory
   with that exact name. The `C:\\` / `/Users/` markers beside it do the real
   work.

## Follow-up

This is the *structural* reorganisation, by concern. A second, **semantic**
rename — by authority boundary (Themis / Metis / Aletheia / Argus / Talos) — is
planned as its own packet, deliberately separate so each move is reviewable and
bisectable on its own.
