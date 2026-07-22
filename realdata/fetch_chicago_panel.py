"""Build a real zone-hour demand panel from Chicago TNP (rideshare) trips.

Chicago publishes every TNP trip (Uber/Lyft/Via) since Nov 2018 under a
reporting ordinance. We aggregate server-side with SoQL (count of trips per
pickup community area per hour) so the laptop never downloads raw trip rows.

Month-level group-bys time out on the 2018-2022 dataset (Socrata gives a
grouped query a fixed compute window and 200M rows do not fit), so we chunk
BY DAY: each day's group-by touches under a million rows and returns in
seconds. A month file is only written once every one of its days has
succeeded; if any day fails after retries, the whole month is left
unwritten so the next run retries it in full rather than marking it
complete with a silent gap. Progress persists as one CSV per month in
monthly/ and completed months are skipped, so the script is safe to kill
and re-run any time:

  py -3 realdata/fetch_chicago_panel.py

Datasets (data.cityofchicago.org):
- m6dm-c72p  Trips 2018-2022
- n26f-ihde  Trips 2023-2024
- 6dvr-xwnh  Trips 2025-

Complete calendar months use `YYYY-MM.csv`. The current in-progress month uses
`YYYY-MM.partial.csv` and is refreshed on every run, so a partial month is never
mistaken for a finalized checkpoint.

Final output (written/refreshed whenever all months present so far are done):
realdata/panels/chicago_tnp_zone_hour.csv.gz
  columns: date, hour, area (community area 1..77), trips
"""

import io
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

PANELS = Path(__file__).parent / "panels"
MONTHLY = PANELS / "chicago_monthly"
MONTHLY.mkdir(parents=True, exist_ok=True)

DATASETS = [
    ("m6dm-c72p", date(2018, 11, 1), date(2022, 12, 31)),
    ("n26f-ihde", date(2023, 1, 1), date(2024, 12, 31)),
    ("6dvr-xwnh", date(2025, 1, 1), date.today() - timedelta(days=14)),
]

SELECT = ("date_extract_hh(trip_start_timestamp) as hour,"
          "pickup_community_area as area,count(*) as trips")


def fetch_day(ds: str, day: date) -> pd.DataFrame | None:
    """Returns None (not an empty DataFrame) on failure, so a failed day is
    never indistinguishable from a legitimately empty response and can
    never silently pass as "fetched" to the caller."""
    url = f"https://data.cityofchicago.org/resource/{ds}.csv"
    params = {
        "$select": SELECT,
        "$where": (f"trip_start_timestamp >= '{day}T00:00:00' AND "
                   f"trip_start_timestamp < '{day + timedelta(days=1)}"
                   f"T00:00:00'"),
        "$group": "hour,area",
        "$limit": 10000,
    }
    for attempt in range(5):
        try:
            r = requests.get(url, params=params, timeout=90)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            if df.empty:
                raise ValueError("empty response for a high-volume service day")
            df.insert(0, "date", day)
            return df
        except Exception as e:
            print(f"  retry {attempt + 1} for {day} ({e})", flush=True)
            time.sleep(10 * (attempt + 1))
    print(f"  gave up on {day} after 5 attempts", flush=True)
    return None


def month_days(ds_end: date, m0: date):
    d = m0
    while d.month == m0.month and d <= ds_end:
        yield d
        d += timedelta(days=1)


def month_starts(start: date, end: date):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        yield cur
        cur = (date(cur.year + 1, 1, 1) if cur.month == 12
               else date(cur.year, cur.month + 1, 1))


def is_complete_month(m0: date, end: date) -> bool:
    next_month = (date(m0.year + 1, 1, 1) if m0.month == 12
                  else date(m0.year, m0.month + 1, 1))
    return end >= next_month - timedelta(days=1)


def combine():
    files = sorted(MONTHLY.glob("*.csv"))
    if not files:
        return
    panel = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)
    panel = panel.dropna(subset=["area"])
    panel["area"] = panel.area.astype(int)
    panel = panel.sort_values(["date", "hour", "area"])
    out = PANELS / "chicago_tnp_zone_hour.csv.gz"
    panel.to_csv(out, index=False, compression="gzip")
    print(f"combined {len(files)} months -> {out}: {len(panel):,} rows, "
          f"{panel.trips.sum():,} trips, {panel.date.min()} to "
          f"{panel.date.max()}", flush=True)


if __name__ == "__main__":
    for ds, start, end in DATASETS:
        for m0 in month_starts(start, end):
            complete = is_complete_month(m0, end)
            dest = MONTHLY / (f"{m0:%Y-%m}.csv" if complete
                              else f"{m0:%Y-%m}.partial.csv")
            if complete and dest.exists():
                continue
            t0 = time.time()
            day_list = list(month_days(min(end, date.today()), m0))
            with ThreadPoolExecutor(max_workers=4) as ex:
                results = list(ex.map(lambda d: fetch_day(ds, d), day_list))
            n_failed = sum(r is None for r in results)
            if n_failed:
                print(f"{ds} {m0:%Y-%m}: {n_failed}/{len(day_list)} days "
                      f"failed, NOT marking complete, will retry next run "
                      f"({time.time() - t0:.0f}s)", flush=True)
                continue
            month = pd.concat(results, ignore_index=True)
            temp = dest.with_suffix(dest.suffix + ".part")
            month.to_csv(temp, index=False)
            temp.replace(dest)
            print(f"{ds} {m0:%Y-%m}: {len(month)} rows, "
                  f"{month.trips.sum():,} trips "
                  f"({time.time() - t0:.0f}s)", flush=True)
    combine()
