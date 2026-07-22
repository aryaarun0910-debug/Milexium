"""Build the per-agency demand-response economics table from raw NTD pulls.

For every agency: latest reported year, annual trips, operating expense,
cost per trip, revenue hours, trips per revenue hour, deadhead share, and
the dollar value of a 10 percent deadhead reduction (the outreach hook).

Deadhead math: NTD reports actual total hours and deadhead hours. We
attribute operating expense to hours uniformly, so
  deadhead_cost = opex * deadhead_hours / actual_total_hours
  value_of_10pct_deadhead_cut = 0.10 * deadhead_cost
This is deliberately conservative and fully reproducible from public data.

Output: ntd/agency_economics.csv, ntd/market_sizing.md
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
df["deadhead_cost"] = df.opex * df.deadhead_pct_hours
df["value_10pct_deadhead_cut"] = 0.10 * df.deadhead_cost
df["ada_share"] = np.where(df.trips > 0, df.ada_trips / df.trips, np.nan)

for c in ["cost_per_trip", "trips_per_vrh", "cost_per_vrh"]:
    df[c] = df[c].round(2)
for c in ["deadhead_pct_hours", "deadhead_pct_miles", "ada_share"]:
    df[c] = df[c].round(4)
for c in ["deadhead_cost", "value_10pct_deadhead_cut"]:
    df[c] = df[c].round(0)

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

lines = [
    "# US demand-response market, bottom-up from NTD",
    "",
    f"Source: FTA National Transit Database annual data (datasets ekg5-frzt,"
    f" wwdp-t4re on data.transportation.gov), modes DR and DT, pulled"
    f" {pd.Timestamp.today().date()}. All figures below are report year 2024"
    f" reporters only; ntd/agency_economics.csv also carries agencies whose"
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
    "## Deadhead (agencies reporting hours detail)",
    "",
    f"- Agencies with deadhead detail: {len(dh):,}",
    f"- Their combined operating expense: ${dh.opex.sum():,.0f}",
    f"- Expense-weighted deadhead share of hours: "
    f"{(dh.deadhead_cost.sum() / dh.opex.sum()):.1%}",
    f"- Combined annual deadhead cost: ${dh.deadhead_cost.sum():,.0f}",
    f"- Value of a 10 percent deadhead reduction across them: "
    f"${dh.value_10pct_deadhead_cut.sum():,.0f} per year",
    "",
    "## Segmentation by annual trips (2024)",
    "",
    seg.to_markdown(index=False),
    "",
    "## How to use these numbers",
    "",
    "- Outreach: every row of agency_economics.csv gives a personalized"
    " opener: trips, cost per trip, deadhead share, and the dollar value of"
    " a 10 percent deadhead cut, all from the agency's own NTD filing.",
    "- YC market size: the operating expense total above is the annual spend"
    " Milexium optimizes against; software captures a fraction of the"
    " savings it creates, not the whole budget. State both numbers plainly.",
]
(HERE / "market_sizing.md").write_text("\n".join(lines), encoding="utf-8")

print(f"agencies in economics table: {len(df)}")
print(f"2024 reporters: {len(y24)}")
print(f"2024 trips: {y24.trips.sum():,.0f}  opex: ${y24.opex.sum():,.0f}")
print(f"median cost/trip 2024: ${y24.cost_per_trip.median():.2f}")
print(f"deadhead share (expense-weighted): "
      f"{dh.deadhead_cost.sum() / dh.opex.sum():.1%}")
print(f"value of 10pct deadhead cut: ${dh.value_10pct_deadhead_cut.sum():,.0f}")
