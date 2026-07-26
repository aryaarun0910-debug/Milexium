"""Build the per-agency demand-response economics table from raw NTD pulls.

For every agency: latest reported year, annual trips, operating expense,
cost per trip, revenue hours, trips per revenue hour, cost per revenue hour,
deadhead share and deadhead cost.

`deadhead_cost` IS AN ACCOUNTING IDENTITY, NOT A SAVING
-------------------------------------------------------
NTD reports actual total hours and deadhead hours. Attributing operating
expense to hours uniformly gives

  deadhead_cost = opex * deadhead_hours / actual_total_hours

which is arithmetic on the agency's own filing: this is what those empty
vehicle-hours cost at the agency's own average cost per hour. HOW MUCH OF IT
IS RECOVERABLE IS UNKNOWN and this file does not model it. Fixed costs do not
fall with utilisation, and no operator fixed/variable split exists in this
repo.

A `value_10pct_deadhead_cut` column used to live here and has been REMOVED
(packet MX-CLAIMS-DOLLAR-SWEEP-013). It multiplied the identity above by a
hypothetical 10 percent cut and presented the product as an annual saving. It
is not one, and the diagnostic premise underneath it does not hold: deadhead
share does not identify an expensive agency. Pearson +0.017, OLS R2 0.0003 on
n=405 (research/h5b_structure_vs_cost.json); Spearman +0.024 over 406
operators against +0.738 for cost per HOUR, with cost-per-trip quartile
medians flat at $48.53 (lowest deadhead quartile) to $54.09 (highest) --
business/outreach/panel_findings.json, finding `dr_deadhead_predicts_cost_per_trip`,
which the panel gate REJECTED on effect size.

What replaces it is comparison, not valuation: an agency's position against
the national panel on cost per trip, on productivity (trips per revenue hour)
and on cost per revenue hour. Those are computable, checkable, and make no
claim about what any intervention would recover.

Output: business/ntd/agency_economics.csv, business/ntd/market_sizing.md
"""

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
RAW = HERE / "raw"

metrics = pd.read_csv(RAW / "metrics_dr.csv", low_memory=False)
service = pd.read_csv(RAW / "service_dr.csv", low_memory=False)

metrics["ntd_id"] = metrics.ntd_id.astype(str).str.zfill(5)
service["ntd_id"] = service._5_digit_ntd_id.astype(str).str.zfill(5)

NUM_M = ["total_operating_expenses", "unlinked_passenger_trips",
         "vehicle_revenue_hours", "vehicle_revenue_miles", "mode_voms",
         "fare_revenues_earned"]
NUM_S = ["actual_vehicles_passenger_car_miles",
         "actual_vehicles_passenger_deadhead_miles",
         "actual_vehicles_passenger_car_hours",
         "actual_vehicles_passenger_car_deadhead_hours",
         "ada_upt", "sponsored_service_upt", "days_of_service_operated"]
for c in NUM_M:
    metrics[c] = pd.to_numeric(metrics[c], errors="coerce")
for c in NUM_S:
    service[c] = pd.to_numeric(service[c], errors="coerce")

# Sum across mode (DR, DT) and type of service (DO, PT, TX) per agency-year
gm = (metrics.groupby(["ntd_id", "report_year"])
      .agg(agency=("agency", "first"), city=("city", "first"),
           state=("state", "first"), uza_name=("uza_name", "first"),
           uza_population=("primary_uza_population", "first"),
           reporter_type=("reporter_type", "first"),
           organization_type=("organization_type", "first"),
           vehicles=("mode_voms", "sum"),
           trips=("unlinked_passenger_trips", "sum"),
           opex=("total_operating_expenses", "sum"),
           fares=("fare_revenues_earned", "sum"),
           vrh=("vehicle_revenue_hours", "sum"),
           vrm=("vehicle_revenue_miles", "sum"))
      .reset_index())

gs = (service.groupby(["ntd_id", "report_year"])
      .agg(actual_miles=("actual_vehicles_passenger_car_miles", "sum"),
           deadhead_miles=("actual_vehicles_passenger_deadhead_miles", "sum"),
           actual_hours=("actual_vehicles_passenger_car_hours", "sum"),
           deadhead_hours=("actual_vehicles_passenger_car_deadhead_hours", "sum"),
           ada_trips=("ada_upt", "sum"),
           sponsored_trips=("sponsored_service_upt", "sum"),
           service_days=("days_of_service_operated", "max"))
      .reset_index())

df = gm.merge(gs, on=["ntd_id", "report_year"], how="left")

# Keep each agency's latest year with substantive reporting
df = df[(df.trips > 0) & (df.opex > 0)]
df = (df.sort_values("report_year")
      .groupby("ntd_id").tail(1)
      .reset_index(drop=True))

df["cost_per_trip"] = df.opex / df.trips
df["trips_per_vrh"] = np.where(df.vrh > 0, df.trips / df.vrh, np.nan)
df["cost_per_vrh"] = np.where(df.vrh > 0, df.opex / df.vrh, np.nan)
df["deadhead_pct_hours"] = np.where(
    df.actual_hours > 0, df.deadhead_hours / df.actual_hours, np.nan)
df["deadhead_pct_miles"] = np.where(
    df.actual_miles > 0, df.deadhead_miles / df.actual_miles, np.nan)
# Accounting identity only -- see the module docstring. Never a saving.
df["deadhead_cost"] = df.opex * df.deadhead_pct_hours
df["ada_share"] = np.where(df.trips > 0, df.ada_trips / df.trips, np.nan)

for c in ["cost_per_trip", "trips_per_vrh", "cost_per_vrh"]:
    df[c] = df[c].round(2)
for c in ["deadhead_pct_hours", "deadhead_pct_miles", "ada_share"]:
    df[c] = df[c].round(4)
df["deadhead_cost"] = df.deadhead_cost.round(0)

df = df.sort_values("trips", ascending=False)
df.to_csv(HERE / "agency_economics.csv", index=False)

# Market sizing (2024 reporters only, so totals are one clean year)
y24 = df[df.report_year == 2024]
bands = pd.cut(y24.trips, [0, 10_000, 50_000, 200_000, np.inf],
               labels=["under 10k", "10k to 50k", "50k to 200k",
                       "over 200k"]).rename("size_band")
seg = (y24.groupby(bands, observed=True)
       .agg(agencies=("ntd_id", "count"), trips=("trips", "sum"),
            opex=("opex", "sum"),
            median_cost_per_trip=("cost_per_trip", "median"))
       .reset_index())

dh = y24.dropna(subset=["deadhead_cost"])


def q(series, p):
    return series.dropna().quantile(p)


lines = [
    "# US demand-response market, bottom-up from NTD",
    "",
    f"Source: FTA National Transit Database annual data (datasets ekg5-frzt,"
    f" wwdp-t4re on data.transportation.gov), modes DR and DT. Raw extracts"
    f" live in business/ntd/raw/ and are pulled by business/ntd/fetch_ntd.py; this table was"
    f" rebuilt {pd.Timestamp.today().date()} from those extracts, which is not"
    f" the same date as the pull. All figures below are report year 2024"
    f" reporters only; business/ntd/agency_economics.csv also carries agencies whose"
    f" latest filing is 2022 or 2023.",
    "",
    "## Totals (2024 report year)",
    "",
    f"- Agencies reporting demand-response service: {len(y24):,}",
    f"- Annual demand-response trips: {y24.trips.sum():,.0f}",
    f"- Annual operating expense: ${y24.opex.sum():,.0f}",
    f"- Annual vehicle revenue hours: {y24.vrh.sum():,.0f}",
    f"- Median cost per trip: ${y24.cost_per_trip.median():.2f}",
    f"- Mean cost per trip (expense-weighted): "
    f"${y24.opex.sum() / y24.trips.sum():.2f}",
    "",
    "## National reference distribution (2024)",
    "",
    "The comparison baselines. An operator's position in these distributions"
    " is computable from its own filing and checkable by the operator; it"
    " asserts nothing about what any change would recover.",
    "",
    f"| metric | p10 | median | p90 | p90/p10 |",
    f"|:--|--:|--:|--:|--:|",
    f"| Cost per trip | ${q(y24.cost_per_trip, .10):,.2f} | "
    f"${y24.cost_per_trip.median():,.2f} | ${q(y24.cost_per_trip, .90):,.2f} |"
    f" {q(y24.cost_per_trip, .90) / q(y24.cost_per_trip, .10):.2f}x |",
    f"| Cost per revenue hour | ${q(y24.cost_per_vrh, .10):,.2f} | "
    f"${y24.cost_per_vrh.median():,.2f} | ${q(y24.cost_per_vrh, .90):,.2f} |"
    f" {q(y24.cost_per_vrh, .90) / q(y24.cost_per_vrh, .10):.2f}x |",
    f"| Trips per revenue hour | {q(y24.trips_per_vrh, .10):,.2f} | "
    f"{y24.trips_per_vrh.median():,.2f} | {q(y24.trips_per_vrh, .90):,.2f} |"
    f" {q(y24.trips_per_vrh, .90) / q(y24.trips_per_vrh, .10):.2f}x |",
    "",
    "Roughly half the variation in cost per trip is productivity and roughly"
    " half is input price (50.1% price / 49.9% productivity, finding"
    " `dr_cost_per_trip_dispersion_2024` in business/outreach/panel_findings.json). Cost"
    " per HOUR is the variable that actually ranks with cost per trip:"
    " Spearman +0.738 across 406 operators.",
    "",
    "## Deadhead (agencies reporting hours detail)",
    "",
    "**These are accounting identities, not an opportunity.** `deadhead_cost`"
    " is what an operator's empty vehicle-hours cost at its own reported"
    " average cost per hour. How much of it is recoverable is unknown: fixed"
    " costs do not fall with utilisation and no operator fixed/variable split"
    " exists in this repo. No figure in this section may be presented as a"
    " saving, an opportunity, or a benefit of adopting Milexium.",
    "",
    f"- Agencies with deadhead detail: {len(dh):,}",
    f"- Their combined operating expense: ${dh.opex.sum():,.0f}",
    f"- Expense-weighted deadhead share of hours: "
    f"{(dh.deadhead_cost.sum() / dh.opex.sum()):.1%}",
    f"- Combined annual cost of those empty hours (accounting identity): "
    f"${dh.deadhead_cost.sum():,.0f}",
    f"- Per-agency deadhead share: median "
    f"{dh.deadhead_pct_hours.median():.1%}, p90 "
    f"{q(dh.deadhead_pct_hours, .90):.1%}",
    "",
    "**Deadhead share does not identify an expensive agency.** Pearson +0.017,"
    " OLS R2 0.0003 on n=405 (research/h5b_structure_vs_cost.json). Spearman"
    " +0.024 over 406 operators, against +0.738 for cost per hour, with cost"
    " per trip essentially flat across deadhead quartiles ($48.53 lowest to"
    " $54.09 highest) -- business/outreach/panel_findings.json, finding"
    " `dr_deadhead_predicts_cost_per_trip`, REJECTED by the panel gate on"
    " effect size. A high deadhead figure is a description of an operator's"
    " hours, not a diagnosis of its costs.",
    "",
    "## Segmentation by annual trips (2024)",
    "",
    seg.to_markdown(index=False),
    "",
    "## How to use these numbers",
    "",
    "- **Outreach: position, not valuation.** Every row of"
    " agency_economics.csv gives an operator its own trips, cost per trip,"
    " cost per revenue hour and trips per revenue hour, and the reference"
    " distribution above turns those into a national position the operator"
    " cannot see from inside its own data. Do not attach a dollar saving to"
    " that position -- the gap to the median is not known to be recoverable,"
    " and asserting that it is would be the same causal claim the platform"
    " refuses to make everywhere else.",
    "- **YC market size: state the spend, not a capture.** The operating"
    " expense total above is the annual spend US demand-response runs on. It"
    " is a market size. It is not a saving Milexium has created, and no"
    " fraction of it may be quoted as one until an operator's own"
    " fixed/variable split says what is recoverable.",
    "- **Status: Demonstrated, never Validated.** These are well-measured"
    " descriptions of what agencies FILED. No operator has confirmed any of"
    " it against their own books.",
]
(HERE / "market_sizing.md").write_text("\n".join(lines), encoding="utf-8")

print(f"agencies in economics table: {len(df)}")
print(f"2024 reporters: {len(y24)}")
print(f"2024 trips: {y24.trips.sum():,.0f}  opex: ${y24.opex.sum():,.0f}")
print(f"median cost/trip 2024: ${y24.cost_per_trip.median():.2f}")
print(f"deadhead share (expense-weighted): "
      f"{dh.deadhead_cost.sum() / dh.opex.sum():.1%}")
print(f"cost of those empty hours (accounting identity, NOT a saving): "
      f"${dh.deadhead_cost.sum():,.0f}")
