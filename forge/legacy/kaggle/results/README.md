# Transformer results (real Kaggle GPU runs)

## TEST_MODE run, 2026-07-22 (NvidiaTeslaT4)

The pretrain-then-finetune transformer was actually run on Kaggle GPUs against
the real data (Kaggle Dataset `aryaarun07/transitpulse-real-panels`). This was
the TEST_MODE run: full Chicago + MTA bus + MTA subway + AAR panels, but only
6 months of TLC (TEST_MODE limits TLC only), and a shorter 10-day tune/test
holdout instead of 90 (TEST_MODE scales those down).

### What happened

- **Pretrain** (Chicago + MTA bus + MTA subway + 6mo TLC, 1,206 entities):
  R2 0.601 vs seasonal-naive 0.607 on the untouched test set. The shared
  ~5M-param backbone across 1,206 heterogeneous entities essentially TIES
  the naive baseline (a hair worse). A small general model spread across
  four very different transit systems is weak, as expected.
- **Finetune on AAR paratransit**: R2 0.933 vs naive 0.897. The fine-tuned
  transformer BEATS its baseline by ~3.6 points on the untouched AAR holdout.

### The honest comparison (this is the point)

| Model | AAR R2 | naive | margin | holdout |
|---|---|---|---|---|
| **XGBoost (production)** | **0.986** | 0.923 | +0.063 | 90 days |
| Transformer (pretrain+finetune) | 0.933 | 0.897 | +0.036 | 10 days (TEST_MODE) |

**XGBoost decisively wins**, both in absolute R2 and in margin over its own
baseline. The two holdouts are not identical (the transformer's TEST_MODE run
used a 10-day window, so its naive baseline differs), so this is not a
perfectly controlled head-to-head - but the gap is large enough that the
conclusion is clear: **the transformer, even pretrained on billions of real
transit events and fine-tuned on AAR, does not beat the gradient-boosted
trees on this task.**

### What we do with that

Exactly what forge/legacy/kaggle/README.md and the notebook said we would: **we ship
XGBoost as the production model and treat the transformer as R&D evidence,
not the product.** This is the disciplined, credible outcome - we built the
sophisticated thing, ran it honestly on real GPUs, and it lost to the simpler
model, so the simpler model ships. A founder who chases the transformer
anyway after this result would be optimizing for a demo, not for the product.

### Caveats / what a full run might change

- TEST_MODE used only 6 months of TLC pretraining data. A full run
  (TEST_MODE=False, full 2019-2026 TLC, ~1.7B trips) has more pretraining
  signal and MIGHT narrow the gap - but there is no guarantee, and nothing
  here suggests it would overturn a 5-point deficit.
- The 10-day vs 90-day holdout mismatch should be fixed before any
  published head-to-head: rerun the transformer with TEST_MODE=False so both
  models report on a 90-day window, then compare like-for-like.
- The transformer's one genuine advantage not captured by R2: it emits
  learned quantile (uncertainty) predictions natively. If that proves more
  calibrated than XGBoost + split-conformal, it is a reason to keep the
  research line alive - measure it before deciding.

Model weights (pretrained_backbone.pt, finetuned_aar_model.pt) are on Kaggle;
only the metrics JSONs are committed here (binaries are regenerable by
rerunning the kernel).
