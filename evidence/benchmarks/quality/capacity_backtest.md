# Capacity backtest -- does the forecast support the capacity decision?

_Generated 2026-07-26T10:49:33.912485+00:00 by `evidence/benchmarks/quality/capacity_backtest.py`. Every headline below is recomputable from the per-series records in `capacity_backtest.json`._

**Status: Demonstrated (public aggregate data). NOT Validated.** Scored on `realdata/panels/ntd_monthly_dr.csv.gz` (sha256 `72a97da33256f212...`), the only governed panel in this repo that records both realised demand and the capacity operated to meet it.

## What is being measured

The forecast leaderboard scores demand accuracy. This scores the DECISION: vehicle-revenue-hours committed, under an explicitly stated asymmetric cost. Under-provisioning denies a legally-entitled ADA trip; over-provisioning wastes money; a squared-error objective prices them identically and is therefore the wrong objective, not merely a rough one.

- **Stated cost asymmetry:** $75 per unserved trip, $60 per idle vehicle-revenue-hour. **This is an illustrative placeholder, not an operator's number**, and every figure below moves with it.
- **Implied newsvendor critical ratio** `Cu/(Cu+Co)`, per series via that series' own productivity: median **0.734** (range 0.237-0.942). A squared-error model targets the conditional mean, i.e. a critical ratio of 0.5. The gap between those two numbers is the entire argument.
- **Series:** 640 agency-service series ((ntd_id, tos)), 30-month forward validation window never touched by the 36-month conformal calibration window.
- **Median measured productivity:** 2.21 trips per vehicle-revenue-hour.

## Capacity decision: asymmetric cost per series-month

Lower is better. `naive_mean` is the squared-error-optimal plan (seasonal-naive point forecast, no asymmetry) and is the reference column.

| comparison | series where the first is cheaper | median cost reduction |
|---|---|---|
| model_cost_aware vs naive_mean (headline) | 561 / 640 (87.7%) | +40.3% |
| model_cost_aware vs naive_cost_aware **(control: is it the model?)** | 584 / 640 (91.2%) | +40.5% |
| model_cost_aware vs model_mean **(control: is it the asymmetry?)** | 469 / 640 (73.3%) | +7.3% |
| naive_cost_aware vs naive_mean | 339 / 640 (53.0%) | +2.5% |
| model_mean vs naive_mean | 536 / 640 (83.8%) | +37.1% |

**Read the two control rows before the headline.** They decompose the headline into its two causes, and the decomposition is not flattering to the packet's own mechanism:

- Against `naive_cost_aware` (same critical-ratio inflation, worse point forecast) the win is 91.2% of series at +40.5% median -- essentially the whole headline. **The point forecast is doing most of the work.**
- Against `model_mean` (same point forecast, no asymmetry) the win is 73.3% of series at +7.3% median. **That, and only that, is what the cost asymmetry itself contributes.** It is a real gain and a modest one, and it is reported as such.
- Applying the asymmetry to a poor point forecast (`naive_cost_aware` vs `naive_mean`) helps in only 53.0% of series. Quantile inflation on top of a biased baseline buys over-provisioning, not service.

### Achieved service level (median across series)

| plan | median share of months whose realised demand fitted inside the plan |
|---|---|
| naive_mean | 42.1% |
| model_mean | 53.3% |
| naive_cost_aware | 93.3% |
| model_cost_aware | 80.0% |

Target for the cost-aware plans is that series' own critical ratio (median 0.734).

**The stated level is MISSED in about a third of series.** Only 67.5% of series actually achieved their target level with `model_cost_aware` (69.5% with `naive_cost_aware`), even though the median achieved level (80.0%) sits above the median target. The distribution is what matters, not the median: conformal coverage is MARGINAL, and a marginal guarantee says nothing about any individual series. This is the empirical reason the recommendation withdraws the service-level claim rather than printing it.

## Demand accuracy, against seasonal naive (reported whether or not it flatters us)

| metric | model | seasonal naive | series where model wins |
|---|---|---|---|
| median MAE (trips/month) | 532.9 | 753.3 | 569 / 640 (88.9%) |
| median MAPE | 8.73% | 13.04% | 574 / 640 (89.7%) |

## Where we LOSE to seasonal naive

The repo's discipline is that a loss is kept, not quietly dropped. `evidence/benchmarks/quality/forecast_leaderboard.md` already records the NTD temporal split losing to naive on R2 (0.8854 vs 0.9715) and that row stands: **nothing here overturns it.** That row scores a different method (XGBoost), a different target (trips) and a different metric (R2). This backtest scores a simple YoY-adjusted naive on a capacity target under an asymmetric cost. The two results are not in competition and neither supersedes the other.

- **Demand MAPE: the model loses on 66 of 640 series (10.3%).** When it loses it is a median 8.6% worse (worst case 55.9% worse); when it wins it is a median 32.8% better. The losses are real but shallow and the wins are deep -- which is the honest shape of this result, not 'we win 90%'.
- **Capacity cost: `model_cost_aware` loses to the plain `naive_mean` plan on 79 of 640 series (12.3%).** Median 11.9% worse when it loses, worst case 415.5% worse. On those series a planner following this recommendation would spend more than one following last year's numbers.

Largest MAPE losses (agency, service type):

| agency | state | tos | model MAPE | naive MAPE |
|---|---|---|---|---|
| Topeka Metropolitan Transit Authority | KS | PT | 35.49% | 22.76% |
| City of El Paso | TX | DO | 122.71% | 116.31% |
| Maryland Transit Administration | MD | DO | 18.96% | 13.19% |
| Tri-County Community Council, Inc. | FL | DO | 17.45% | 13.06% |
| City of Santa Clarita | CA | PT | 18.11% | 13.87% |

## How the interval guarantee propagates into the recommendation

ADR-0049 established that a conformal interval's coverage guarantee is WITHDRAWN when detected drift contradicts exchangeability. A capacity recommendation derived from that interval inherits the status: `CapacityRecommendation.evidenced_service_level` becomes `None` and a caveat is mandatory (a model validator refuses to construct the object otherwise). The hours figure is still returned -- report, do not decide.

| drift status on the validation window | series |
|---|---|
| insufficient_data | 640 / 640 |

| inherited interval guarantee | series |
|---|---|
| not_assessed | 640 / 640 |

**Measured, not asserted:** 640 real `CapacityRecommendation` objects were constructed on this panel (one per series, for the final validation month). **0** of them may claim an evidenced service level; **640** carry a mandatory caveat instead. The hours figure is present on all of them -- what the withdrawal removes is the coverage CLAIM, not the number.

## The control found a defect, and it is reported rather than deleted

ADR-0049's exchangeability control -- a random seeded 50/50 split of ONE window, where drift is impossible by construction -- was run per series at the monthly sample size with the module's default `MIN_ROWS_FOR_STABLE_STATISTIC = 30`. It reported **640 drift / 0 no_drift / 0 insufficient_data**. Every one of those drift flags is false by construction.

The cause, measured on i.i.d. samples from a single distribution (pure noise, `_psi_null_calibration`):

| rows per sample | median PSI | p90 PSI | PSI >= 0.2 false-positive rate | KS false-positive rate (alpha 0.01) |
|---|---|---|---|---|
| 30 | 1.494 | 2.773 | 97.5% | 0.5% |
| 50 | 0.383 | 1.533 | 88.0% | 0.8% |
| 80 | 0.231 | 0.418 | 61.3% | 0.0% |
| 120 | 0.143 | 0.244 | 22.2% | 1.0% |
| 200 | 0.088 | 0.157 | 3.0% | 0.8% |
| 400 | 0.043 | 0.078 | 0.0% | 1.0% |
| 1000 | 0.018 | 0.029 | 0.0% | 2.2% |

The PSI 0.1/0.2 interpretation bands are large-sample folklore. At 30 rows the statistic's null distribution sits an order of magnitude above the 'significant' band, so the band fires on almost all pure noise. **The Bonferroni-corrected KS test in the same monitor is correctly calibrated at every sample size** -- this is PSI specifically, not the monitor's design, and `MIN_ROWS_FOR_STABLE_STATISTIC = 30` is the value that lets it through.

This backtest therefore requires **400** rows before accepting a per-series verdict. No monthly agency series can ever supply that (400 months is 33 years), so **exchangeability is not testable at monthly agency grain** and every per-series verdict is honestly `insufficient_data`. The guarantee is still withdrawn -- but for the true reason (we could not tell) rather than on a false drift flag. `serve_drift.py`'s constant is deliberately **not** edited here: it is shared serving-path behaviour ADR-0049 records, and changing it belongs to a packet that can write the ADR. The measurement is committed so that packet starts with evidence.

### A real verdict, at the grain where the statistic is supported

Pooling every qualifying series (each normalised by its own calibration-window median, so the comparison is scale-free) gives 23,004 calibration rows against 19,170 validation rows -- far above the measured threshold.

- **Panel verdict: `drift`**, interval guarantee `unsupported`, drifted features: lag12, lag1, roll3, yoy_ratio, month.
- **Control at the same pooled size: `no_drift`** -- zero features flagged. This is what makes the verdict above evidence rather than an artefact.

| feature | PSI | PSI band |
|---|---|---|
| roll3 | 0.5819 | significant |
| lag1 | 0.4907 | significant |
| lag12 | 0.4899 | significant |
| yoy_ratio | 0.2244 | significant |
| month | 0.0099 | none |

**Significance is not effect size, and the table says which is which.** The demand lags carry a genuinely large shift (PSI ~0.5, well into the significant band) -- post-pandemic demand-response recovery, running at agency-specific rates. `month` is flagged too, but its PSI is ~0.01, the module's own 'none' band: at 23,000 vs 19,170 rows a KS test rejects on a difference of no practical size (a 36-month window and a 30-month window have different calendar composition by construction). Reporting the flag without the effect size would overstate the finding.

**Finite-sample ceiling (a second, independent withdrawal reason):** 0 / 640 series requested a service level their calibration sample cannot express (`level > n/(n+1)`). This is independent of drift and is not fixed by monitoring -- it is fixed by more calibration history. The recommendation suppresses the evidenced level for this reason too, and says which reason applies.

## Limitations

- Public panels record DELIVERED service (trips carried, vehicle-hours operated), never DENIED trips. Realised ridership is demand censored from above by the capacity actually run, so under-provisioning -- the failure this cost asymmetry exists to price -- is unobservable in it. Any accuracy figure computed against such a panel is a claim about reproducing an operator's past commitment, not about meeting rider need. Closing this gap requires consented operator denial / unmet-trip records; until then no capacity result here can reach Validated.
- The cost asymmetry is an illustrative placeholder, not an operator statement. The critical ratio, and therefore every capacity number here, moves directly with it.
- Productivity is a per-series point estimate (median historical trips/VRH); its own variation is measured and reported but not propagated into the service level.
- The forecasters are deliberately simple and fit-free (seasonal naive, YoY-adjusted seasonal naive). This is a test of the CAPACITY DECISION LAYER, not a claim that these are the best available demand models.
- Monthly agency grain. Nothing here demonstrates capacity planning at the hour-of-day grain a dispatcher works at.

## Reproduce / verify

```
py -3 evidence/benchmarks/quality/capacity_backtest.py
py -3 -m pytest evidence/conformance/property-tests/test_capacity_backtest.py -q
```
