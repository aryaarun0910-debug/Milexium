# ADR-0076: Renaming by authority, and merging the two data trees

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-REPO-AUTHORITY-RENAME-015
- **Follows:** ADR-0075 (reorganisation by concern)

## Context

ADR-0075 grouped 23 flat directories into 10 **by concern**. This groups them by
**authority** — which layer is permitted to do what — and finishes a merge
ADR-0075 declined.

## Decision

### Six directories, each an authority boundary

```
themis/      canonical, ontology, connect, estate, core     governed reality
metis/       forecast, decide                               bounded intelligence
aletheia/    evidence, verify, replay, conformance,         reproducible evidence
             benchmarks, artifacts
argus/       api, sdk, sdk-typescript, demo                 operational surface
talos/       infra, ops, contracts, tools                   dependable delivery
forge/       knowledge, research, business, legacy          where we build it
data/        acquired/ + curated/                           the governed corpus
```

> **Themis** governs what is true and permissible. **Metis** proposes what should
> happen next. **Aletheia** proves why the decision was made. **Argus** lets the
> operator see, question and control it. **Talos** keeps it running.

The names are not decoration: each marks a boundary that already exists in the
code. Two are already enforced — **Metis imports types and vocabularies from
Themis and never a store or a writer**, and Aletheia's independence is asserted
against the verifier's own AST. `forge/` may import anything and **nothing may
import `forge/`**.

All five names were checked clear of stdlib collisions before the move, which
matters because ADR-0075 hit exactly that with `platform` — a name that can never
be a package prefix. `talos/` replaces it and `talos.tools` is a legal import.

### The data merge ADR-0075 declined

`data/` and `realdata/` were two roots for one concern. ADR-0075 declined the
merge on the grounds that `realdata/` paths were "pinned by sha256".

**That reasoning was wrong, and it was stated twice.** The hashes are of file
*content*. Moving a file and updating its recorded path preserves every
verification; the cost is updating recorded paths, which is work, not a
constraint. It was a technically defensible answer that happened to require no
effort.

```
data/acquired/    came through themis/estate — checksum-verified,
                  free-space guarded, quarantined before promotion
data/curated/     hand-acquired before that pipeline existed
```

Named for **how the bytes got here**, which is the only distinction that was ever
real. Both declare rights in committed manifests (ADR-0053).

**Provenance was proved, not assumed:** all 19 `.acquired.json` records were
repointed, **and every recorded sha256 re-verified against the bytes at the new
path — 19 verified, 0 mismatches.** `verify_evidence_registry()` returns clean
and a fresh `build_registry()` equals the committed one exactly. A hash failure
would have meant bytes moved rather than paths, and would have stopped the merge.

## Consequences

**2688 passed, 1 skipped** — restored to the ADR-0075 baseline. Demo runs;
`audit_repository.py` reports 0 errors, 0 warnings.

### Three failures the move caused, and what each teaches

1. **13 collection errors** — `pythonpath` still named `evidence` and `platform`.
   Loud, trivial, found immediately.
2. **93 skips against a baseline of 1.** Every Cordeau DARP test skipped with
   *"benchmark archive not acquired"* because the acquired records still pointed
   at `data/benchmarks/`. **This is the dangerous class:** 92 tests stopped
   running and the suite still reported success. A skip is not a pass, and a move
   that turns real tests into skips looks exactly like a move that worked.
3. **A test rooted at `data/` while the code rooted at `data/acquired/`** — the
   MinIO backing test wrote a manifest somewhere `inventory()` never looks, then
   failed for a reason that had nothing to do with MinIO.

The estate code (`acquire.py`, `catalog.py`) had to move its root to
`data/acquired/`; `data/curated/` is deliberately **not** reachable from there,
because nothing in curated came through quarantine.

## Honest limitations

- **Three structural moves in a row**, each finding a defect the previous grep
  missed. The tree should now be frozen while Argus is built against it.
- The layer prohibitions are **documented, not all enforced**. Themis's and
  Argus's have no test — and Argus's is the one most likely to be violated,
  because that is where an LLM will eventually sit. Writing the test before the
  layer is the right order, and is the next packet.
- The knowledge-graph snapshot under `aletheia/artifacts/` still references
  pre-move paths. Deliberate: it is a dated record, and it is due for
  regeneration anyway (145+ commits stale, still says `TransitPulse`).
- `forge/knowledge/docs/JOURNAL.md` and `forge/knowledge/docs/archive/` retain
  old paths **by design** — append-only records whose value is being wrong about
  today and right about the day they were written.
