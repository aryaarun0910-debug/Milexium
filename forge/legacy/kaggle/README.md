# forge/legacy/kaggle/ : transformer-scale training on free GPUs

The laptop handles panels and gradient-boosted models; anything needing a
GPU trains on Kaggle (weekly free GPU quota, internet-enabled notebooks,
~55 GB working disk, fast CDN bandwidth to the TLC corpus).

**Status:** the coverage-aware window logic was verified locally with plain
pandas/numpy against synthetic multi-dataset data, and the full
forge/knowledge/architecture/training loop (forward pass, backward pass, loss, the
train/tune/test split, non-crossing quantiles) was smoke-tested end to end
on CPU with tiny synthetic data — confirmed to run without error. That is
a different claim from "this has been run on the real data": the actual
Kaggle GPU run, which is what produces the metrics JSONs referenced below,
has not happened yet. Do not quote a number from this notebook until those
files exist on disk from a real run.

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
percentile uncertainty, non-crossing quantiles enforced), 9 input channels
per hour (log-count, 4 calendar, 4 weather). Parameter count, computed
analytically from PyTorch's documented layer shapes (not guessed): the
backbone is 4,852,320 params (789,760 per encoder layer x 6, plus
projection and heads); entity + dataset embeddings add 68,096 (TLC only,
265 zones) up to 294,912 (all four mass-transit datasets plus the AAR
finetune, 1,147 entities across 5 dataset ids). Total: 4.92M to 5.15M
depending on which datasets are attached — nowhere near the ~15-20M an
earlier version of this README stated without computing it. The notebook
also prints the exact runtime figure (`n_params` in both metrics JSONs);
trust that over any number in prose, here included.

**Two correctness fixes as of 2026-07-21** (see forge/knowledge/docs/JOURNAL.md for the
full review that found these):
- **Coverage masking:** an entity's training/tuning/test windows are now
  restricted to its own real observed date range. The earlier version
  built one shared clock across all attached datasets and zero-filled
  everything outside a dataset's actual coverage, which meant a dataset
  starting later than another (e.g. MTA bus from 2020 while TLC runs from
  2019) got FABRICATED zero-demand training examples for the gap.
- **Train/tune/test, not train/valid:** checkpoint selection during
  training now uses a `tune` split; final reported metrics use a separate
  `test` split that is never touched during training. The earlier version
  reused one holdout for both, which reports tuning-set performance
  dressed up as holdout performance.
- **Weather is now actually wired in.** An earlier version of this
  notebook claimed "weather sensitivity" as something the model learns
  without ever loading `weather_daily.csv` into a feature. It's now a real
  4-channel input (tmax/tmin/precip/snow, city-indexed by dataset,
  optional and zero-filled if the weather file isn't attached).

## How to run

1. kaggle.com, New Notebook, File > Import Notebook, upload this file.
2. Settings: Accelerator GPU (T4 or P100), Internet ON, Persistence ON.
3. TEST_MODE = True first for a 6-month TLC-only smoke run (~20 min end to
   end), then False for the full pretrain run (2019-02 to 2026-05 TLC
   download ~30 min, pretraining a few hours on a T4).
4. **Optional but recommended:** before running, create a Kaggle Dataset
   named `transitpulse-real-panels` from the repo's `data/curated/panels/`
   folder (at minimum `aar_hourly_borough.csv.gz` and `weather_daily.csv`
   for Stage 2; add `chicago_tnp_zone_hour.csv.gz`,
   `mta_bus_route_hour.csv.gz`, `mta_subway_station_hour.csv.gz` to widen
   Stage 1's pretraining corpus beyond TLC alone). Attach it to the
   notebook. Without it, Stage 1 still runs on TLC alone (still ~1.7B
   rows) and Stage 2 prints upload instructions and stops cleanly rather
   than silently skipping.
5. Download `pretrained_backbone.pt`, `finetuned_aar_model.pt` (if Stage 2
   ran), `pretrain_metrics.json`, `finetune_metrics.json` from the output
   pane; commit the metrics JSONs to `forge/legacy/kaggle/results/`.

## Evaluation protocol (identical to the rest of the repo)

Three-way split: train, tune (checkpoint selection only), test (final
holdout, touched exactly once). Seasonal-naive (same hour, 7 days earlier)
reported next to every model result. The finetuned AAR result must be
compared against data/curated/metrics_real.json's XGBoost result on the same
data and a comparable holdout window (R2 0.985 vs 0.923 naive, clean
train/tune/cal/valid split) before claiming the transformer is better.
Report both, always, whichever wins — the honest comparison is the point,
not the bigger model.
