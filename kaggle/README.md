# kaggle/ : transformer-scale training on free GPUs

The laptop handles panels and gradient-boosted models; anything needing a
GPU trains on Kaggle (30 free GPU hours/week, internet-enabled notebooks
with ~55 GB working disk and fast CDN bandwidth to the TLC corpus).

## transitpulse_transformer.ipynb

Temporal transformer for multi-zone day-ahead demand forecasting, trained
on the NYC TLC FHVHV corpus (every Uber/Lyft trip since 2019, about 20M
per month, downloaded inside Kaggle so nothing large crosses your home
connection).

Architecture: per-sample input is two weeks (336 h) of one zone's hourly
counts plus calendar encodings; learned zone embedding; 4-layer
transformer encoder (d_model 128, 8 heads); head outputs 24 hourly Poisson
rates; Poisson NLL on raw counts. About 1M parameters, deliberately small:
the point is a scalable recipe with honest evaluation, not a paper.

How to run:
1. kaggle.com, New Notebook, File > Import Notebook, upload this file.
2. Settings: Accelerator GPU (T4 or P100), Internet ON, Persistence ON.
3. Set TEST_MODE = True for a 6-month smoke run first (about 20 min end
   to end), then False for the full 2021-2026 run (download about 30 min,
   training a few hours; watch the epoch prints).
4. Download demand_transformer.pt and transformer_metrics.json from the
   output pane; commit metrics to kaggle/results/.

Evaluation protocol is identical to the rest of the repo: last 90 days
held out, seasonal-naive (same hour, 7 days earlier) reported next to the
model. If the transformer does not beat both the naive and the XGBoost
recipe at zone-hour granularity, we say so and ship the boosted trees.
