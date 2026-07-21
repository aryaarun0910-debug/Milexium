"""Fetch HOURLY weather for NYC and Chicago from NOAA NCEI LCD.

Upgrades realdata/panels/weather_daily.csv (daily) to hourly resolution,
which matters because demand is modeled at zone-HOUR granularity while
weather was only a daily feature. Rain at 8am on a weekday moves paratransit
demand differently than the same daily total falling overnight; the daily
feature couldn't see that.

Source: NOAA NCEI Local Climatological Data bulk CSV access (direct HTTP,
no rate limit, no token needed for the bulk files - far faster than the
CDO API v2 for multi-year hourly pulls). A CDO token is saved in .env for
any future API use.

Stations (major airports, most complete hourly records):
  NYC:     LaGuardia 72503014732
  Chicago: O'Hare    72530094846

Output: realdata/panels/weather_hourly.csv.gz
  columns: city, date, hour, temp_c, dewpoint_c, precip_mm, wind_kph, humidity_pct
"""

import io
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import requests

PANELS = Path(__file__).parent / "panels"
PANELS.mkdir(parents=True, exist_ok=True)
BASE = "https://www.ncei.noaa.gov/data/local-climatological-data/access"

STATIONS = {"nyc": "72503014732", "chicago": "72530094846"}
YEARS = list(range(2018, date.today().year + 1))

USE = {
    "HourlyDryBulbTemperature": "temp_f",
    "HourlyDewPointTemperature": "dewpoint_f",
    "HourlyPrecipitation": "precip_in",
    "HourlyWindSpeed": "wind_mph",
    "HourlyRelativeHumidity": "humidity_pct",
}


def fetch_station_year(city, sid, year):
    url = f"{BASE}/{year}/{sid}.csv"
    r = requests.get(url, timeout=120)
    if r.status_code != 200:
        print(f"  {city} {year}: HTTP {r.status_code}, skipping", flush=True)
        return None
    df = pd.read_csv(io.StringIO(r.text), low_memory=False)
    keep = ["DATE"] + [c for c in USE if c in df.columns]
    df = df[keep].rename(columns=USE)
    df["ts"] = pd.to_datetime(df.DATE, errors="coerce")
    df = df.dropna(subset=["ts"])
    for c in USE.values():
        if c in df.columns:
            # LCD uses trace markers like 'T' and suffix flags; coerce
            df[c] = pd.to_numeric(
                df[c].astype(str).str.replace("s", "", regex=False)
                .str.replace("T", "0", regex=False), errors="coerce")
    df["city"] = city
    df["date"] = df.ts.dt.strftime("%Y-%m-%d")
    df["hour"] = df.ts.dt.hour
    return df


if __name__ == "__main__":
    frames = []
    for city, sid in STATIONS.items():
        for year in YEARS:
            d = fetch_station_year(city, sid, year)
            if d is not None and len(d):
                frames.append(d)
                print(f"{city} {year}: {len(d)} obs", flush=True)

    raw = pd.concat(frames, ignore_index=True)
    # collapse sub-hourly obs to one row per (city, date, hour): mean of
    # continuous vars, sum of precip
    agg = (raw.groupby(["city", "date", "hour"])
           .agg(temp_f=("temp_f", "mean"), dewpoint_f=("dewpoint_f", "mean"),
                precip_in=("precip_in", "max"), wind_mph=("wind_mph", "mean"),
                humidity_pct=("humidity_pct", "mean"))
           .reset_index())

    agg["temp_c"] = ((agg.temp_f - 32) * 5 / 9).round(2)
    agg["dewpoint_c"] = ((agg.dewpoint_f - 32) * 5 / 9).round(2)
    agg["precip_mm"] = (agg.precip_in * 25.4).round(2)
    agg["wind_kph"] = (agg.wind_mph * 1.60934).round(2)
    agg["humidity_pct"] = agg.humidity_pct.round(1)

    out_cols = ["city", "date", "hour", "temp_c", "dewpoint_c", "precip_mm",
                "wind_kph", "humidity_pct"]
    out = PANELS / "weather_hourly.csv.gz"
    agg[out_cols].sort_values(["city", "date", "hour"]).to_csv(
        out, index=False, compression="gzip")
    print(f"saved {out}: {len(agg):,} city-date-hour rows, "
          f"{agg.date.min()} to {agg.date.max()}", flush=True)
