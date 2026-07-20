"""Fetch real NYC Access-A-Ride (paratransit) demand data.

Two sources on data.ny.gov:
- hasd-hdb7  MTA NYCT Paratransit Ridership, beginning 2024: trips by day,
  hour of promise time, pickup borough, provider type. This is actual
  paratransit demand at hourly granularity from the largest US paratransit
  operation (about 30k trips/day).
- vxuj-8kew  MTA Daily Ridership, beginning 2020: daily Access-A-Ride total
  scheduled trips (longer history, daily granularity).

Outputs:
- realdata/panels/aar_hourly_borough.csv.gz (day, hour, borough, provider_type, trips, riders)
- realdata/panels/aar_daily.csv (date, scheduled_trips)
"""

import io
from pathlib import Path

import pandas as pd
import requests

PANELS = Path(__file__).parent / "panels"
PANELS.mkdir(parents=True, exist_ok=True)
BASE = "https://data.ny.gov/resource"


def fetch_all(dataset: str, select: str, page: int = 200000) -> pd.DataFrame:
    frames, offset = [], 0
    while True:
        params = {"$select": select, "$limit": page, "$offset": offset,
                  "$order": ":id"}
        r = requests.get(f"{BASE}/{dataset}.csv", params=params, timeout=180)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        frames.append(df)
        print(f"{dataset}: page at offset {offset}: {len(df)} rows",
              flush=True)
        if len(df) < page:
            break
        offset += page
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    hourly = fetch_all(
        "hasd-hdb7",
        "day,hour_of_promise_time,provider_type,pickup_borough,trips,ridership")
    hourly["day"] = pd.to_datetime(hourly.day).dt.date
    hourly = hourly.rename(columns={
        "hour_of_promise_time": "hour", "pickup_borough": "borough",
        "ridership": "riders"})
    hourly = hourly.sort_values(["day", "hour", "borough"])
    out1 = PANELS / "aar_hourly_borough.csv.gz"
    hourly.to_csv(out1, index=False, compression="gzip")
    print(f"saved {out1}: {len(hourly):,} rows, {hourly.trips.sum():,} trips, "
          f"{hourly.day.min()} to {hourly.day.max()}")

    daily = fetch_all("vxuj-8kew", "date,access_a_ride_total_scheduled_trips")
    daily["date"] = pd.to_datetime(daily.date).dt.date
    daily = (daily.rename(
        columns={"access_a_ride_total_scheduled_trips": "scheduled_trips"})
        .dropna().sort_values("date"))
    out2 = PANELS / "aar_daily.csv"
    daily.to_csv(out2, index=False)
    print(f"saved {out2}: {len(daily):,} rows, "
          f"{daily.date.min()} to {daily.date.max()}")
