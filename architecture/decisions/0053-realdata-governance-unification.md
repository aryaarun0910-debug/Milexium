# ADR-0053: Unify data governance without moving a file

- **Status:** Accepted
- **Date:** 2026-07-25

## Context

The repository has two data trees, and the clutter is genuine enough to be
noticed: `realdata/` and `data/`. They are **not** duplicates — they have
different origins and, until now, different governance models.

- **`realdata/`** — the original product. Real panels, the five trained models,
  `train_real_models.py`, `leakage_audit.py`, the model cards. Hand-acquired
  before the governed estate existed, with **no declared rights record**.
- **`data/`** — the governed estate (blueprint 17, ADR-0013). Manifest-gated:
  rights **must** be declared, checksum verified, content-addressed promotion,
  MinIO-backed (ADR-0036).

The obvious tidy-up — merge them — is the wrong move.

## Decision

**Unify the governance, not the location.**

`realdata/` paths are load-bearing:

- the evidence registry pins those panels **and their sha256** — 52 hash pins —
  and those hashes had to be made cross-platform-stable via `.gitattributes`
  after CI caught a CRLF/LF mismatch. Moving files changes recorded provenance;
- conformance suites read those exact paths (forecast, the feature-store leakage
  proof on `aar_daily.csv`, the teardown demo on `raw_tlc/`);
- 54 files reference them and nine ADRs cite them;
- and `realdata/` is the founder's pre-expansion work, which the expansion is not
  meant to reorganise.

A move would be a large, high-blast-radius refactor whose only benefit is
tidiness, and it would weaken the evidence chain to buy it.

**The inconsistency actually worth closing was different:** `realdata/` held real
TLC/MTA/Chicago data with **no rights declaration**, while `data/` refuses a
single byte without one. `tools/build_realdata_manifests.py` writes acquisition
manifests describing those sources — licence, commercial-use position,
provenance, retention — pointing at their **existing paths**.

**Governance-only, and honest about it.** Nothing is moved, copied, re-downloaded
or checksum-promoted, and **no `.acquired.json` record is written**. Those
datasets never went through `packages.estate.acquire`, and writing an acquired
record would assert a free-space guard, a quarantine step and a checksum-verified
promotion that never happened — **forging exactly the provenance the estate
exists to make trustworthy**. Each manifest instead carries `already_present_at`
entries saying plainly where the bytes live and how they got there.

## Consequences

- **Five sources now declare rights**: NYC Access-A-Ride, NYC TLC trip records,
  MTA AFC ridership, Chicago TNP, and the NTD agency-economics extract. All are
  open data permitting commercial use; each manifest addresses the commercial
  question explicitly rather than leaving it silent.
- **16 conformance tests** hold it closed: every manifest loads, declares
  substantive rights with no placeholder, addresses commercial use, points at
  paths that **actually exist** (a governance record pointing at nothing is worse
  than none, because it looks like coverage), and — the one that matters —
  **asserts no `.acquired.json` was forged**.
- The script is idempotent with a `--check` mode, so drift is detectable.
- Both `README`s now state the distinction, so the next reader does not have to
  rediscover why there are two trees.

**Also removed in the same pass:** four `outreach/_contacts_batch_*.csv` staging
files whose content was merged into `contact_research_worksheet.csv` — genuinely
redundant intermediates, unlike everything else examined.

**Audit finding, recorded because the honest answer was "not much":** the
repository is not meaningfully cluttered. Zero tracked `__pycache__` or `.pyc`,
an 81:79 code-to-test file ratio, and all 51 ADRs live. There is no dead code
worth archiving to a branch, and `kaggle/` in particular must **not** be — it
holds transfer-learning results where the **negative** results were deliberately
kept as evidence, so archiving them would quietly delete part of the honesty
record. Declutter was scoped to what was actually redundant rather than expanded
to justify the exercise.
