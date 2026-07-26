# ntd/ : FTA National Transit Database, demand-response universe

Real, government-reported economics for every US demand-response (paratransit
and NEMT) operator. This is the market we sell into, sized bottom-up, and the
raw material for personalized outreach.

Run order:

```
py -3 ntd/fetch_ntd.py               # pulls DR/DT rows from data.transportation.gov
py -3 ntd/build_economics.py         # per-agency table + market sizing
py -3 ntd/build_outreach_targets.py  # tiered 80-target outreach list with hooks
py -3 ntd/peer_position.py "<agency>"  # one agency's national position
```

Files:

- raw/metrics_dr.csv, raw/service_dr.csv: filtered NTD pulls, 2022-2024,
  modes DR and DT (datasets ekg5-frzt and wwdp-t4re)
- agency_economics.csv: one row per agency, latest report year: trips, opex,
  cost per trip, cost per revenue hour, trips per revenue hour, deadhead
  share, deadhead cost, ADA share
- market_sizing.md: national totals, the national reference distribution and
  segmentation, 2024 report year
- peer_position.py: the self-serve widget backend for the website — where one
  operator sits in the national panel

Headline numbers (2024 report year): 1,920 agencies, 139.7M annual trips,
$7.06B operating expense, median $37.97 per trip, expense-weighted deadhead
17.3 percent of vehicle hours.

## No dollar saving comes out of this directory

`deadhead_cost` is an **accounting identity**: operating expense attributed to
hours uniformly, so it is what an operator's empty vehicle-hours cost at its
own reported average cost per hour. **How much of it is recoverable is
unknown** — fixed costs do not fall with utilisation and no operator
fixed/variable split exists in this repo. It may never be presented as a
saving, an opportunity, or a benefit of adopting Milexium.

A `value_10pct_deadhead_cut` column and a `savings_calculator.py` module used
to live here. Both are **removed** (packet MX-CLAIMS-DOLLAR-SWEEP-013), not
softened, because deadhead share does not identify an expensive agency:
Pearson +0.017, OLS R² 0.0003 on n=405 (`research/h5b_structure_vs_cost.json`);
Spearman +0.024 over 406 operators against **+0.738 for cost per hour**, with
cost per trip flat at $48.53 in the lowest deadhead quartile against $54.09 in
the highest (`outreach/panel_findings.json`, finding
`dr_deadhead_predicts_cost_per_trip`, **rejected** by the panel gate).

What replaces it is **position**: where an operator sits nationally on cost per
trip, cost per revenue hour and trips per revenue hour. Computable, checkable
by the operator against its own books, invisible from inside its own data, and
it values nothing. Read cost per *hour* first — it is the variable that ranks
with cost per trip.

Method notes: agencies aggregated across DR and DT modes and all service
types (directly operated plus purchased). Only full reporters (406 agencies in
2024) file deadhead detail; reduced reporters get position hooks without it.
Status is **Demonstrated, never Validated** — this describes what agencies
filed, not what happened, and no operator has confirmed it against their books.
