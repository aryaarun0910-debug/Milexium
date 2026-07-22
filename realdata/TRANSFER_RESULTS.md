# Cross-city transfer learning: does pretraining on other transit help paratransit?

`pretrain_finetune_xgboost.py` (+ `transfer_control.py`). Results:
`pretrain_finetune_results.json`. The honest test of the transformer notebook's
central bet - whether pretraining on big mass-transit corpora helps forecast
paratransit - run with XGBoost continued-boosting, which actually completes on
this hardware.

## Setup

Same AAR holdout, generic features only (calendar + weather + demand-history
lags, NO zone identity, so the feature schema is shared across datasets and a
booster can continue training across them).

- **A** = AAR only, no pretraining.
- **B** = pretrained on 3M rows sampled from Chicago TNP + MTA bus + MTA subway,
  then continued-boosted on AAR.
- **C** = production model (adds borough identity), for reference.

## Result

| Model | AAR R2 | MAE | vs naive (0.923) |
|---|---|---|---|
| A: AAR only, no pretrain | 0.9862 | 20.10 | +0.063 |
| **B: pretrain (Chicago+MTA) then finetune** | **0.9913** | **17.18** | **+0.068** |
| C: production (AAR + borough) | 0.9857 | 20.12 | +0.063 |

Pretraining lifts R2 from 0.9862 to 0.9913 and cuts MAE from 20.1 to 17.2 -
a **15% reduction in forecast error** on the untouched holdout.

## The control that makes this credible (transfer, not just more trees)

Continued-boosting gives B more total trees than A, so the gain could be raw
capacity. `transfer_control.py` rules that out: train AAR-only with escalating
tree budgets and see if it reaches B.

| AAR-only, no pretrain | R2 |
|---|---|
| 400 trees | 0.9862 |
| 750 trees | 0.9863 |
| 1200 trees | 0.9860 |
| 2000 trees | 0.9857 (overfitting) |

**AAR-only plateaus at ~0.986 regardless of tree count** - more capacity does
not close the gap. B reaches 0.9913. Therefore the improvement is genuinely from
the pretrained structure, not from a bigger ensemble. Controlled, positive
transfer result.

## Why this, when the transformer LOST

The transformer (pretrain+finetune neural net on Kaggle) scored 0.933, below
XGBoost's 0.986. XGBoost continued-boosting wins where the transformer lost, and
the likely reason is sample efficiency: a from-scratch neural model needs large
finetune data to overcome a weak base; XGBoost adds a few targeted trees on top
of a strong pretrained base, a gentler and more data-efficient transfer. The
pretrained trees encode generic time-and-recent-history demand structure
(rush-hour shape, weekly cycle, lag response) that is shared across transit
modes and that AAR's own ~93k rows cannot fully learn alone.

## What we do with it

- **This is a genuine, differentiated technical asset:** we can pretrain on the
  billions of public mass-transit events we ingest and measurably improve a
  paratransit forecast, especially valuable for small agencies with little of
  their own history (the cold-start customer). It is the productive version of
  the "leverage our raw-data depth" thesis.
- **Honest caveats:** pretraining used a 3M-row subsample (VRAM limit); the gain
  (0.5 R2 pts / 15% MAE) is real but modest; and both A and B use generic
  features, so C (production, with borough identity) is a separate axis. The
  clean next step is to combine both: pretrained base + zone identity in the
  finetune, and re-run the control at full pretrain scale on Kaggle.
- **We do NOT overclaim.** The auto-verdict said "pretraining helped"; the
  control is what earns the right to say it. Without the control it would have
  been a capacity artifact hiding as a transfer result.
