"""Fetch the NTD Complete Monthly Ridership time series, nationwide.

Every US transit agency reports monthly unlinked passenger trips (UPT),
vehicle revenue hours (VRH), vehicle revenue miles (VRM), and peak vehicles
(VOMS) by mode back to 2002. Filtered here to demand-response modes (DR,
DT), this is a nationwide monthly PARATRANSIT DEMAND panel: ~1,900 agencies
x 20+ years x monthly, the actual product target variable at national
breadth (vs our hourly single-agency AAR panel, which is depth). Nobody in
this market assembles paratransit demand this way.

Distinct from forge/business/ntd/ (annual economics: cost, deadhead, revenue). This is the
monthly demand time series - complementary, and the right source for
per-agency seasonality, trend, and COVID-shock recovery curves.

Source: data.transportation.gov dataset 8bui-9xvu (Complete Monthly
Ridership with Adjustments and Estimates). No API key needed.

Output: data/curated/panels/ntd_monthly_dr.csv.gz
  columns: ntd_id, agency, state, uza_name, mode, tos, date, upt, vrh, vrm, voms
"""

import io
from pathlib import Path

import pandas as pd
import requests

PANELS = Path(__file__).parent / "panels"
PANELS.mkdir(parents=True, exist_ok=True)
URL = "https://data.transportation.gov/resource/8bui-9xvu.csv"

COLS = ["ntd_id", "agency", "state", "uza_name", "mode", "tos",
        "date", "upt", "vrh", "vrm", "voms"]


def fetch_all():
    frames, offset, page = [], 0, 100000
    while True:
        params = {
            "$select": ",".join(COLS),
            "$where": "mode in('DR','DT')",
            "$order": "agency_mode_tos_date",
            "$limit": page, "$offset": offset,
        }
        r = requests.get(URL, params=params, timeout=180)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        if df.empty:
            break
        frames.append(df)
        print(f"offset {offset}: {len(df)} rows", flush=True)
        if len(df) < page:
            break
        offset += page
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    df = fetch_all()
    df["date"] = pd.to_datetime(df.date).dt.strftime("%Y-%m-%d")
    for c in ["upt", "vrh", "vrm", "voms"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.sort_values(["ntd_id", "mode", "tos", "date"])
    out = PANELS / "ntd_monthly_dr.csv.gz"
    df.to_csv(out, index=False, compression="gzip")
    print(f"saved {out}: {len(df):,} rows, {df.ntd_id.nunique()} agencies, "
          f"{df.date.min()} to {df.date.max()}, "
          f"{df.upt.sum():,.0f} total demand-response trips", flush=True)
