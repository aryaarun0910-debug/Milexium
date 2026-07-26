# ADR-0025: Machine-checkable evidence artifacts — forecast leaderboard + evidence registry (Phase 2 proof)

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

IMPLEMENTATION_STATUS "Phase 2 — undeniable public evidence" items 3 and 4:
package the repo's real numbers into reproducible, third-party-checkable
artifacts. `knowledge/docs/MASTER_ROADMAP.md` already envisioned "a machine-readable
evidence registry mapping every public metric to its script, dataset manifest,
split dates, artifact, and limitation." Both are the anti-overclaim tooling:
every number pinned to a source, so a skeptic can verify without a pilot.

## Decision

**Forecast leaderboard** (`evidence/benchmarks/quality/build_forecast_leaderboard.py` →
`forecast_leaderboard.{json,md}`): reads the committed metrics
(`realdata/metrics_real.json`, `metrics_ntd_monthly.json`) and emits a
leaderboard where every value carries the exact source file + json-path it came
from. Headline is R² vs each model's own seasonal-naive baseline (MAE/RMSE/MAPE
alongside). Deliberately **no cross-model ranking** (R²/MAE aren't comparable
across grains). The kaggle transformer is excluded to a `not-shipped` block,
mirroring `knowledge/docs/MODEL_CARDS.md`.

**Evidence registry** (`platform/tools/build_evidence_registry.py` →
`evidence/artifacts/evidence-registry/registry.json` + `README.md`): scans the committed
evidence surface and emits 20 claims + 8 provenance manifests, each pairing a
value + baseline with a status label (Exists/…/Production) **and** a
plain-language limitation. A `verify_evidence_registry()` re-checks it: every
source file exists, every recorded panel sha256 that names a present file is
recomputed and must match, every claim has a limitation + valid status, and a
claim with no source is flagged untraceable.

Both are **generated, never authored** — a value is emitted only if the
generator actually read it from a committed source (anti-fabrication), and the
tests re-read the cited source and compare, proving traceability rather than
trusting a hand-copied number.

## The honesty this surfaced (worth acting on)

The point of these artifacts is that they make drift and overclaim visible.
They surfaced real cross-document inconsistencies between narrative prose and
the committed source-of-truth metrics — none a fabrication, but each something
a hostile reviewer could pick at:

- **AAR headline drift**: `realdata/README.md` prose says MAE "20.4" / conformal
  "97.8%"; the committed `metrics_real.json` gives MAE **20.12** and decile-only
  conformal **98.11%**. The README's 97.8% is actually the hour-bucket×decile
  Mondrian variant (0.977), so the two docs headline *different conformal
  variants* — a "which variant do we headline" decision, not a typo.
- **NTD MAPE units**: source stores a fraction; `MODEL_CARDS.md` renders ×100.
- The "calendar-only ties naive" finding exists only as README prose (no
  committed JSON), so it can't be machine-verified like the rest.

These are flagged for a doc-reconciliation pass (reconcile the README prose to
the committed metrics as the single source of truth); the registry itself now
pins the exact committed values.

## Consequences

- A reviewer can browse `evidence/benchmarks/quality/forecast_leaderboard.md` and
  `evidence/artifacts/evidence-registry/README.md` and independently trace/verify every
  public number — the checkable substitute for traction.
- The leaderboard **does not hide losses**: the NTD temporal split loses to
  naive on R² (0.885 vs 0.972) and is shown as such; the weather-barely-helps
  and calendar-only-ties-naive findings are recorded. Honesty is the credibility.
- Generated artifacts carry a `generated_at` timestamp and are committed as
  durable evidence (regenerable); the leaderboard-in-registry link is indexed
  by presence, not content-hash, to avoid coupling.
- Everything is **Demonstrated** on real aggregate data — not operator-Validated.
- Completes Phase 2. The flagged README/metrics reconciliation is a recommended
  follow-up, deliberately left to the product owner since it involves a
  which-variant-to-headline judgment.
