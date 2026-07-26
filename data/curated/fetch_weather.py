"""Fetch daily weather history for Chicago and NYC from Open-Meteo.

Open-Meteo's archive API is free, keyless, and serves ERA5-based daily
history. Used as exogenous features for the real demand models.

Output: data/curated/panels/weather_daily.csv
  columns: city, date, tmax_c, tmin_c, precip_mm, snow_cm
"""

from pathlib import Path

import pandas as pd
import requests

PANELS = Path(__file__).parent / "panels"
PANELS.mkdir(parents=True, exist_ok=True)

CITIES = {
    "chicago": (41.88, -87.63),
    "nyc": (40.71, -74.01),
}
START, END = "2018-11-01", str(pd.Timestamp.today().date())

frames = []
for city, (lat, lon) in CITIES.items():
    r = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": lat, "longitude": lon,
            "start_date": START, "end_date": END,
            "daily": ("temperature_2m_max,temperature_2m_min,"
                      "precipitation_sum,snowfall_sum"),
            "timezone": "America/New_York" if city == "nyc"
                        else "America/Chicago",
        }, timeout=120)
    r.raise_for_status()
    d = r.json()["daily"]
    df = pd.DataFrame({
        "city": city, "date": d["time"],
        "tmax_c": d["temperature_2m_max"],
        "tmin_c": d["temperature_2m_min"],
        "precip_mm": d["precipitation_sum"],
        "snow_cm": d["snowfall_sum"],
    })
    frames.append(df)
    print(f"{city}: {len(df)} days")

out = PANELS / "weather_daily.csv"
pd.concat(frames, ignore_index=True).to_csv(out, index=False)
print(f"saved {out}")
