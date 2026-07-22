"""Fetch real AFC-sourced transit ridership: MTA subway and bus, hourly.

Both datasets are fare-payment (OMNY/MetroCard tap) derived ridership, i.e.
AFC (automated fare collection), NOT onboard-sensor APC data. It is a
legitimate real ridership proxy, hourly by route/station, NYC MTA, 2020 to
present, but should not be marketed as APC-scale proof without this
qualification: a rider entering on a transfer, a fare evasion, or a
multi-rider tap can all diverge from actual physical boardings. This is
the phase-2 (fixed-route/campus/hub) evidence base: the same
explainable-demand engine generalizes past paratransit, and this is real
fare-payment-scale data to prove it on.

Datasets (data.ny.gov):
- kv7t-n8in  MTA Bus Hourly Ridership: 2020-2024   (447M raw rows)
- gxb3-akrn  MTA Bus Hourly Ridership: Beginning 2025
- wujg-7c2s  MTA Subway Hourly Ridership: 2020-2024 (121M raw rows)
- 5wq4-mkjj  MTA Subway Hourly Ridership: Beginning 2025

Month-level group-bys are too heavy for Socrata on tables this size (same
failure mode as Chicago's 2018-2022 TNP table), so this chunks by DAY,
summing ridership across payment methods server-side. A month file is
only written once every one of its days has succeeded; if any day fails
after retries, the whole month is left unwritten so the next run retries
it in full (not marked complete with a silent gap). Completed calendar months
use `YYYY-MM.csv`; the current month uses `YYYY-MM.partial.csv` and is refreshed
on every run. Checkpoints are written through `.part` files and atomically
renamed, so an interrupted write cannot look complete.

  py -3 realdata/fetch_mta_apc.py

Output:
  realdata/panels/mta_bus_route_hour.csv.gz    (date, hour, route, riders)
  realdata/panels/mta_subway_station_hour.csv.gz (date, hour, station_id, borough, riders)
"""

import io
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

PANELS = Path(__file__).parent / "panels"
BASE = "https://data.ny.gov/resource"

FEEDS = {
    "bus": {
        "monthly_dir": PANELS / "mta_bus_monthly",
        "out": PANELS / "mta_bus_route_hour.csv.gz",
        "zone_col": "bus_route",
        "zone_out": "route",
        "extra_group": "",
        "datasets": [("kv7t-n8in", date(2020, 1, 1), date(2024, 12, 31)),
                     ("gxb3-akrn", date(2025, 1, 1), date.today())],
    },
    "subway": {
        "monthly_dir": PANELS / "mta_subway_monthly",
        "out": PANELS / "mta_subway_station_hour.csv.gz",
        "zone_col": "station_complex_id",
        "zone_out": "station_id",
        "extra_group": ",borough",
        "datasets": [("wujg-7c2s", date(2020, 1, 1), date(2024, 12, 31)),
                     ("5wq4-mkjj", date(2025, 1, 1), date.today())],
    },
}


def fetch_day(ds: str, day: date, zone_col: str, extra_group: str) -> pd.DataFrame | None:
    """Returns None (not an empty DataFrame) on failure, so a failed day is
    never indistinguishable from a legitimately empty response and can
    never silently pass as "fetched" to the caller."""
    url = f"{BASE}/{ds}.csv"
    select = (f"date_extract_hh(transit_timestamp) as hour,"
              f"{zone_col} as zone,sum(ridership) as riders"
              + (",borough" if "borough" in extra_group else ""))
    params = {
        "$select": select,
        "$where": (f"transit_timestamp >= '{day}T00:00:00' AND "
                   f"transit_timestamp < '{day + timedelta(days=1)}T00:00:00'"),
        "$group": "hour,zone" + extra_group,
        "$limit": 50000,
    }
    for attempt in range(5):
        try:
            r = requests.get(url, params=params, timeout=180)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            if df.empty:
                raise ValueError("empty response for a high-volume service day")
            df.insert(0, "date", day)
            return df
        except Exception as e:
            time.sleep(10 * (attempt + 1))
            if attempt == 4:
                print(f"  gave up on {day}: {e}", flush=True)
                return None
    return None


def month_starts(start: date, end: date):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        yield cur
        cur = (date(cur.year + 1, 1, 1) if cur.month == 12
               else date(cur.year, cur.month + 1, 1))


def month_days(m0: date, end: date):
    d = m0
    while d.month == m0.month and d <= end:
        yield d
        d += timedelta(days=1)


def is_complete_month(m0: date, end: date) -> bool:
    next_month = (date(m0.year + 1, 1, 1) if m0.month == 12
                  else date(m0.year, m0.month + 1, 1))
    return end >= next_month - timedelta(days=1)


def run_feed(name: str, spec: dict):
    spec["monthly_dir"].mkdir(parents=True, exist_ok=True)
    for ds, start, end in spec["datasets"]:
        end = min(end, date.today() - timedelta(days=3))
        for m0 in month_starts(start, end):
            complete = is_complete_month(m0, end)
            dest = spec["monthly_dir"] / (f"{m0:%Y-%m}.csv" if complete
                                           else f"{m0:%Y-%m}.partial.csv")
            if complete and dest.exists():
                continue
            t0 = time.time()
            days = list(month_days(m0, end))
            with ThreadPoolExecutor(max_workers=4) as ex:
                futs = [ex.submit(fetch_day, ds, d, spec["zone_col"],
                                  spec["extra_group"]) for d in days]
                parts = [f.result() for f in futs]
            n_failed = sum(p is None for p in parts)
            if n_failed:
                print(f"{name} {ds} {m0:%Y-%m}: {n_failed}/{len(days)} days "
                      f"failed, NOT marking complete, will retry next run "
                      f"({time.time() - t0:.0f}s)", flush=True)
                continue
            month = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
            temp = dest.with_suffix(dest.suffix + ".part")
            month.to_csv(temp, index=False)
            temp.replace(dest)
            print(f"{name} {ds} {m0:%Y-%m}: {len(month)} rows, "
                  f"{month.riders.sum() if len(month) else 0:,.0f} riders "
                  f"({time.time() - t0:.0f}s)", flush=True)

    files = sorted(spec["monthly_dir"].glob("*.csv"))
    if not files:
        return
    panel = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)
    panel = panel.rename(columns={"zone": spec["zone_out"]})
    panel = panel.dropna(subset=[spec["zone_out"]])
    panel = panel.sort_values(["date", "hour", spec["zone_out"]])
    panel.to_csv(spec["out"], index=False, compression="gzip")
    print(f"{name}: combined {len(files)} months -> {spec['out']}: "
          f"{len(panel):,} rows, {panel.riders.sum():,.0f} total riders, "
          f"{panel.date.min()} to {panel.date.max()}", flush=True)


if __name__ == "__main__":
    for name, spec in FEEDS.items():
        run_feed(name, spec)
