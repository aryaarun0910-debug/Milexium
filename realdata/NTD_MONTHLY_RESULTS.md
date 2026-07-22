# NTD monthly nationwide model: results and honest reading

Model: `model_ntd_monthly.py`. Panel: 637 US agencies, monthly demand-response
UPT, 2002-2026, 151,991 rows. GPU XGBoost (count:poisson), all features
strictly lagged (target month t uses only data through t-1). Baseline:
seasonal-naive = same month one year earlier. Full numbers in
`metrics_ntd_monthly.json`.

## The two tests and what they found

| Test | Model R2 | Naive R2 | Model MAPE | Naive MAPE |
|---|---|---|---|---|
| **Temporal** (last 12mo, all agencies) | 0.885 | **0.971** | **9.9%** | 15.3% |
| **Cold-start** (127 agencies never seen, no identity) | **0.976** | 0.967 | **4.8%** | 11.7% |

## Honest reading (this nuance is the point, not a single trophy number)

1. **On the temporal test, absolute R2/MAE LOSE to the naive baseline, and we
   say so.** Monthly agency-level paratransit demand is extraordinarily stable
   year over year, so "same month last year" is a very hard baseline. The model
   itself confirms this: lag12 (same month last year) is 79% of its feature
   importance. Absolute error is dominated by the handful of giant agencies
   (millions of trips/month) where year-over-year is nearly perfect and where
   the Poisson objective struggles with the enormous dynamic range (UPT spans
   hundreds to millions). This is a real, reported negative result.

2. **On RELATIVE error (MAPE) the model beats naive in BOTH tests** (9.9 vs
   15.3, 4.8 vs 11.7). It is more accurate across the many small and mid-size
   agencies - which is exactly the segment we sell to (the mega-agencies are
   deliberately not our first targets). MAPE, not MAE, is the metric that
   matches the customer.

3. **The cold-start result is the standout and the product-relevant one.**
   Forecasting 127 agencies held out ENTIRELY from training, using no agency
   identity - only their public NTD filing history - the model beats naive on
   both R2 (0.976 vs 0.967) and MAPE (4.8% vs 11.7%). That is the real
   onboarding scenario: a brand-new agency hands us its public numbers and we
   forecast its demand better than year-over-year, before we have any of its
   operational data. Most forecasting demos never run a held-out-agency test;
   this one does, and passes.

## What this motivates next (count-distribution bake-off)

The temporal underperformance on absolute error points straight at the
objective: count:poisson assumes variance = mean, but monthly agency UPT is
massively over-dispersed across a hundreds-to-millions range. Negative-binomial,
Tweedie, or a log-target regression should handle that dynamic range better and
likely close the temporal gap. That is the next modeling-rigor item
(`compare Poisson, negative-binomial, Tweedie, zero-inflated`), and this result
is the concrete reason to run it - not a checkbox, an actual open question the
data raised.
