# Technology vendoring process

The dossier (`blueprint/20-dossier-coverage-ledger.md`) maps 80 software-to-
silicon technologies and 72 intelligence-layer projects to Milexium landing
points. The expansion plan is **explicit** that these are not to be bulk-cloned:

> "Do not vendor upstream projects blindly; independently validate maturity,
> license, security, and benchmark claims." — blueprint 20
>
> "Every external dependency must be pinned by version and commit with license,
> SBOM, upstream provenance, and local patch records." — orchestration instructions

So there is no "download all the technology" step. There is a **gate**: nothing
lands under `third_party/` without a completed review manifest and an ADR, and
almost nothing in the dossier needs vendoring for the current product direction
(a transport decision *runtime* other software integrates) — that direction is
served by the SDK/API surface, the canonical/decision/evidence contracts, and
the standards adapters, not by FPGA toolchains, homomorphic-encryption
libraries, or self-evolving-agent frameworks.

## The gate: what must exist before code lands in `third_party/<name>/`

1. **A review manifest** (`third_party/<name>/REVIEW.md`) covering:
   - upstream repo, pinned **version + commit SHA**;
   - **license** and whether it permits Milexium's intended (commercial) use;
   - **maturity**: release cadence, maintenance status, issue/security history;
   - **security**: known CVEs, dependency footprint, whether it runs untrusted
     input, sandbox needs;
   - **benchmark claim validation**: does the upstream performance claim
     actually hold on a Milexium-relevant workload, measured, not quoted;
   - **why vendor vs. reimplement vs. call as a service**: the blueprint's
     build-vs-buy rule (blueprint 02) applies.
2. **An ADR** in `architecture/decisions/` recording the decision and the
   review outcome (e.g. the TurboVec decision is pre-gated by ADR-0005, which
   already says a dedicated license/security/maturity ADR is required first).
3. **Provenance + patch records**: `third_party/<name>/` carries the upstream
   `LICENSE`, a `PROVENANCE.json` (source URL, commit, retrieval date, sha256
   of the vendored tree), and any local patches as explicit `.patch` files —
   never silent edits to vendored code.
4. **An entry in `THIRD_PARTY_NOTICES`** at the repo root.

## Current status

**Nothing is vendored yet.** `workstreams/DOSSIER_COVERAGE.md` tracks all 152
dossier entries as Specified. The candidates most likely to clear this gate
*first*, when a concrete capability needs them (not before), are the ones that
serve the runtime-integration direction and have permissive licenses and real
maturity:

| Candidate | Landing | Why it might be first | Gate status |
|---|---|---|---|
| pgvector | C — semantic index | Already the second `SemanticIndex` backend behind the exact-search reference (ADR-0005); Postgres extension, permissive license | Not started — needs the PostGIS-style extension-install step + a benchmark vs. `ExactSearchIndex` |
| OR-Tools (CP-SAT) | F — Decide | The roadmap's own scheduler already targets it; Apache-2.0, mature | Held: overlaps Arya's direct YC-roadmap task (see IMPLEMENTATION_STATUS.md) |
| OSRM / valhalla | F/H — routing | Turns the OSM `networks/` estate into travel-time matrices; permissive | Not started — needs a concrete routing capability to justify |

TurboVec, Lean 4, veRL, world-model and silicon toolchains, FHE/MPC libraries,
etc. are **not** near the gate — they serve programs (J/K/L) with no current
product pull and, in several cases, need GPUs or hardware this environment
doesn't have. Vendoring them now would be exactly the "infrastructure before
demand" risk `blueprint/15-risks-and-falsification.md` warns against.
