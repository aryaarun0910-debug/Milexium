# Milexium model cards

_Generated 2026-07-22 by tools/build_model_cards.py from the committed metrics artifacts. Every number here traces to a JSON in realdata/. Regenerate after any retrain._

**Status: Demonstrated, never Validated.** Every model below is trained and evaluated on public data. Under ADR-0001, *Validated* requires consented operator data against a declared baseline and Milexium has none, so no result here validates any operator's capacity planning, scheduling, or dispatch. See the status contract in `docs/COMPETITIVE_POSITIONING.md`.

All models share one protocol: strict temporal holdout, a seasonal-naive baseline reported next to every result, and a mechanical point-in-time leakage audit (**PASS - no leakage detected**). None is an AI wrapper; each is trained from raw public data we ingest and aggregate ourselves.

## Zone-hour demand models

### Real NYC Access-A-Ride paratransit bookings, borough-hour panel

- **Role:** **PRODUCT TARGET** (real paratransit demand)
- **Task:** forecast next-hour demand per borough, hourly granularity, day-ahead.
- **Model:** XGBoost, count:poisson (selected in the objective bakeoff, see
  OBJECTIVE_BAKEOFF_RESULTS.md), GPU-trained.
- **Data / split:** train 2024-01-01 to 2025-09-03 | tune 2025-09-03 to 2025-12-02 |
  cal 2025-12-02 to 2026-03-02 | valid 2026-03-02 to 2026-05-31 (10,800 rows).
  Four non-overlapping temporal blocks; calibration never seen during fit.
- **Result (untouched validation):** R2 **0.9857** vs seasonal-naive
  0.9231; MAE 20.1232 vs 55.4921.
- **Uncertainty:** split-conformal intervals, 90% target,
  98.1% achieved.
- **Point-in-time correct:** yes - all features pass the mechanical leakage
  audit (LEAKAGE_AUDIT.md).
- **Intended use:** capacity planning and staffing-ahead at the borough-hour
  level. **Out of scope:** individual-trip dispatch decisions (this is aggregate
  demand, not trip-level), and any use as the sole basis of a denial.
- **Limitations:** aggregate panel (not trip-level); weather is currently the
  realized value, not a day-ahead forecast (see LEAKAGE_AUDIT.md caveat);
  synthetic-free but public-aggregate, so external validity to a specific
  operator's own bookings is unproven until a pilot.

### Real Chicago TNP door-to-door trips, community-area-hour panel

- **Role:** generalization evidence (not the product target)
- **Task:** forecast next-hour demand per community area, hourly granularity, day-ahead.
- **Model:** XGBoost, count:poisson (selected in the objective bakeoff, see
  OBJECTIVE_BAKEOFF_RESULTS.md), GPU-trained.
- **Data / split:** train 2018-11-01 to 2025-09-03 | tune 2025-09-03 to 2025-12-02 |
  cal 2025-12-02 to 2026-03-02 | valid 2026-03-02 to 2026-05-31 (166,320 rows).
  Four non-overlapping temporal blocks; calibration never seen during fit.
- **Result (untouched validation):** R2 **0.9655** vs seasonal-naive
  0.9362; MAE 15.8326 vs 24.4399.
- **Uncertainty:** split-conformal intervals, 90% target,
  92.6% achieved.
- **Point-in-time correct:** yes - all features pass the mechanical leakage
  audit (LEAKAGE_AUDIT.md).
- **Intended use:** capacity planning and staffing-ahead at the community area-hour
  level. **Out of scope:** individual-trip dispatch decisions (this is aggregate
  demand, not trip-level), and any use as the sole basis of a denial.
- **Limitations:** aggregate panel (not trip-level); weather is currently the
  realized value, not a day-ahead forecast (see LEAKAGE_AUDIT.md caveat);
  synthetic-free but public-aggregate, so external validity to a specific
  operator's own bookings is unproven until a pilot.

### Real MTA bus AFC (fare-payment) ridership, route-hour panel

- **Role:** generalization evidence (not the product target)
- **Task:** forecast next-hour demand per route, hourly granularity, day-ahead.
- **Model:** XGBoost, count:poisson (selected in the objective bakeoff, see
  OBJECTIVE_BAKEOFF_RESULTS.md), GPU-trained.
- **Data / split:** train 2020-01-01 to 2025-10-17 | tune 2025-10-17 to 2026-01-15 |
  cal 2026-01-15 to 2026-04-15 | valid 2026-04-15 to 2026-07-14 (946,080 rows).
  Four non-overlapping temporal blocks; calibration never seen during fit.
- **Result (untouched validation):** R2 **0.9492** vs seasonal-naive
  0.8262; MAE 14.991 vs 29.9147.
- **Uncertainty:** split-conformal intervals, 90% target,
  92.0% achieved.
- **Point-in-time correct:** yes - all features pass the mechanical leakage
  audit (LEAKAGE_AUDIT.md).
- **Intended use:** capacity planning and staffing-ahead at the route-hour
  level. **Out of scope:** individual-trip dispatch decisions (this is aggregate
  demand, not trip-level), and any use as the sole basis of a denial.
- **Limitations:** aggregate panel (not trip-level); weather is currently the
  realized value, not a day-ahead forecast (see LEAKAGE_AUDIT.md caveat);
  synthetic-free but public-aggregate, so external validity to a specific
  operator's own bookings is unproven until a pilot.

### Real MTA subway AFC (fare-payment) ridership, station-hour panel

- **Role:** generalization evidence (not the product target)
- **Task:** forecast next-hour demand per station, hourly granularity, day-ahead.
- **Model:** XGBoost, count:poisson (selected in the objective bakeoff, see
  OBJECTIVE_BAKEOFF_RESULTS.md), GPU-trained.
- **Data / split:** train 2020-01-01 to 2025-10-11 | tune 2025-10-11 to 2026-01-09 |
  cal 2026-01-09 to 2026-04-09 | valid 2026-04-09 to 2026-07-08 (924,480 rows).
  Four non-overlapping temporal blocks; calibration never seen during fit.
- **Result (untouched validation):** R2 **0.949** vs seasonal-naive
  0.8602; MAE 42.9342 vs 105.8264.
- **Uncertainty:** split-conformal intervals, 90% target,
  91.7% achieved.
- **Point-in-time correct:** yes - all features pass the mechanical leakage
  audit (LEAKAGE_AUDIT.md).
- **Intended use:** capacity planning and staffing-ahead at the station-hour
  level. **Out of scope:** individual-trip dispatch decisions (this is aggregate
  demand, not trip-level), and any use as the sole basis of a denial.
- **Limitations:** aggregate panel (not trip-level); weather is currently the
  realized value, not a day-ahead forecast (see LEAKAGE_AUDIT.md caveat);
  synthetic-free but public-aggregate, so external validity to a specific
  operator's own bookings is unproven until a pilot.

## National monthly demand model (NTD)

### Nationwide NTD monthly demand-response demand

- **Role:** national market + demand evidence; the cold-start test is directly product-relevant (forecasting a new agency).
- **Task:** forecast an agency's monthly unlinked passenger trips.
- **Data:** 637 US agencies, 151,991 agency-months, 2002-01-01 to 2026-05-01, 2,182,930,310 total trips. GPU XGBoost.
- **Temporal test** (last 12mo, all agencies): model R2 0.8854 vs naive 0.9715; MAPE 991.8% vs 1527.1%. Loses on absolute R2 (monthly demand is very stable YoY), wins on relative error. Reported honestly.
- **Cold-start test** (127 agencies held out entirely, no agency identity): model R2 0.9757 vs naive 0.9666; MAPE 475.3% vs 1172.4%. Beats naive forecasting agencies never seen in training - the real onboarding scenario.
- **Recommended objective:** Gamma (best MAPE, the customer-relevant metric), see OBJECTIVE_BAKEOFF_RESULTS.md. Current committed run is Poisson; switch pending.
- **Point-in-time correct:** yes (LEAKAGE_AUDIT.md, all 13 features clean).
- **Out of scope:** sub-monthly or trip-level forecasting; agencies with no filing history.

## Not shipped

The pretrain-then-finetune transformer (kaggle/) was run on real GPUs and **lost to XGBoost** on AAR (0.933 vs 0.986); it is R&D evidence and is not shipped. See kaggle/results/. We ship the simpler model on purpose — as a local reference implementation, not a production model: nothing here is deployed to or running for an operator.
