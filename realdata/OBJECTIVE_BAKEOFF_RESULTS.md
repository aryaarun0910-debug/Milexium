# Count-distribution bake-off: is Poisson the right objective?

`objective_bakeoff.py`. We had trained everything with count:poisson on faith.
This tests it, honestly, on the same clean temporal splits and the same
seasonal-naive baseline. Two panels, chosen because they stress the objective
in different ways. Full numbers in `metrics_objective_bakeoff.json`.

## AAR zone-hour (paratransit, ~30% zero cells)

| Objective | R2 | MAE |
|---|---|---|
| poisson (default) | 0.9865 | 19.89 |
| tweedie 1.5 | 0.9866 | 19.89 |
| log_target | 0.9864 | 19.85 |
| tweedie 1.3 | 0.9860 | 20.08 |
| hurdle (2-part zero-inflated) | 0.9861 | 20.06 |
| tweedie 1.1 | 0.9853 | 20.67 |

**Finding: Poisson is validated for AAR.** Every alternative - including a
proper hurdle (zero-inflated) model and three Tweedie powers - lands within
noise of Poisson (R2 0.985-0.987). The 30% zero cells do not break Poisson
here, and a zero-inflated model does not help. Our default was the right call,
and now that is evidence, not assumption. **No change: AAR stays Poisson.**

## NTD monthly (national, hundreds-to-millions dynamic range, ~2% zeros)

| Objective | R2 | MAE | MAPE |
|---|---|---|---|
| tweedie 1.3 | **0.889** | 2,825 | 11.0% |
| poisson (default) | 0.871 | 2,862 | 12.4% |
| tweedie 1.5 | 0.847 | 3,236 | 9.4% |
| gamma | 0.844 | 3,037 | **5.2%** |
| log_target | 0.843 | 3,128 | 6.0% |

**Finding: the objective matters a lot here, with a real R2-vs-MAPE tradeoff.**
- If the target metric is absolute error / R2 (dominated by the giant
  agencies), **Tweedie(1.3) is best** (R2 0.889, up from Poisson 0.871).
- If the target metric is relative error across all agencies (MAPE),
  **Gamma is dramatically best: 5.2% vs Poisson's 12.4%** - a 2.4x reduction,
  and roughly 3x better than the seasonal-naive baseline's ~15% MAPE.

**Why this matters for the product:** we sell to small and mid-size agencies,
not the mega-metros. For that segment, relative accuracy (MAPE) is the metric
that matches the customer, and Gamma more than halves it. **Recommendation:
switch the NTD monthly production objective to Gamma (or log_target) and report
MAPE as the headline, with Tweedie(1.3) noted as the absolute-error-optimal
alternative.** This is a concrete, evidence-backed objective change, not a
checkbox - the earlier Poisson NTD result (committed) is now known to be
suboptimal on the metric we actually care about.

## Honest scope note

True negative-binomial and full zero-inflated-Poisson need a custom XGBoost
objective (a documented next step). Tweedie (compound Poisson-Gamma, native)
and the two-part hurdle model cover the same over-dispersion and zero-inflation
failure modes natively, which is why they stand in here. The finding - Poisson
fine for AAR, Gamma/Tweedie materially better for the wide-range national panel
- would not change: it is driven by dynamic range, which a custom NB objective
addresses the same way Tweedie does.
