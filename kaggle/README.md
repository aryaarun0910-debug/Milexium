# kaggle/ : transformer-scale training on free GPUs

The laptop handles panels and gradient-boosted models; anything needing a
GPU trains on Kaggle (weekly free GPU quota, internet-enabled notebooks,
~55 GB working disk, fast CDN bandwidth to the TLC corpus).

## transitpulse_transformer.ipynb: pretrain, then finetune

Why not one flat model on everything: our product target is paratransit
demand (AAR, ~93k training rows). The real mass-transit corpora we've
pulled (NYC TLC ~1.7B trips, Chicago TNP ~300M, MTA bus/subway hundreds of
millions of rows) outweigh that by four orders of magnitude. A single
mixed loss would let the huge non-paratransit volume dominate every
gradient step and wash out the actual signal. So the notebook is two
stages:

- **Stage 1 (pretrain):** one shared temporal transformer learns general
  transit-demand structure (daily/weekly cycles, holidays, weather
  sensitivity, cross-city variation) from the large real corpora. A
  dataset-id embedding plus a per-(dataset, zone) entity embedding lets
  one backbone span cities and systems without a unified zone vocabulary.
- **Stage 2 (finetune):** the pretrained backbone adapts to AAR
  paratransit demand specifically: new embeddings for the 5 boroughs and
  the `aar` dataset id at full learning rate, backbone at 5% of that rate
  so it adapts without forgetting. This is a real transfer-learning claim
  ("pretrained on 2B+ real transit events, fine-tuned on real paratransit
  demand"), not a parameter-count flex.

Architecture: d_model 256, 8 heads, 6 layers, dual head (Poisson mean rate
for the point forecast, quantile/pinball head for native 10/50/90
percentile uncertainty, non-crossing quantiles enforced). Roughly
15-20M parameters depending on final vocabulary size — scaled up from an
earlier single-dataset ~1M-param version now that the pretraining corpus
justifies it.

## How to run

1. kaggle.com, New Notebook, File > Import Notebook, upload this file.
2. Settings: Accelerator GPU (T4 or P100), Internet ON, Persistence ON.
3. TEST_MODE = True first for a 6-month TLC-only smoke run (~20 min end to
   end), then False for the full pretrain run (2019-02 to 2026-05 TLC
   download ~30 min, pretraining a few hours on a T4).
4. **Optional but recommended:** before running, create a Kaggle Dataset
   named `transitpulse-real-panels` from the repo's `realdata/panels/`
   folder (at minimum `aar_hourly_borough.csv.gz` and `weather_daily.csv`
   for Stage 2; add `chicago_tnp_zone_hour.csv.gz`,
   `mta_bus_route_hour.csv.gz`, `mta_subway_station_hour.csv.gz` to widen
   Stage 1's pretraining corpus beyond TLC alone). Attach it to the
   notebook. Without it, Stage 1 still runs on TLC alone (still ~1.7B
   rows) and Stage 2 prints upload instructions and stops cleanly rather
   than silently skipping.
5. Download `pretrained_backbone.pt`, `finetuned_aar_model.pt` (if Stage 2
   ran), `pretrain_metrics.json`, `finetune_metrics.json` from the output
   pane; commit the metrics JSONs to `kaggle/results/`.

## Evaluation protocol (identical to the rest of the repo)

Last 90 days held out, seasonal-naive (same hour, 7 days earlier) reported
next to every model result. The finetuned AAR result must be compared
against realdata/metrics_real.json's XGBoost result on the same data and
the same holdout window (R2 0.987 vs 0.923 naive) before claiming the
transformer is better. Report both, always, whichever wins — the honest
comparison is the point, not the bigger model.
