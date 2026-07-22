"""Download FTA National Transit Database demand-response tables.

Sources (DOT Socrata open data portal, no API key needed):
- 2022-2024 NTD Annual Data - Metrics (ekg5-frzt): per agency-mode-year
  UPT, operating expenses, revenue hours/miles, cost per trip/hour, fares.
- 2022-2024 NTD Annual Data - Service by Mode and Time Period (wwdp-t4re):
  Annual Total rows carry actual vs revenue vs deadhead miles/hours,
  ADA UPT, sponsored UPT, days of service, average speed.

Modes: DR (demand response), DT (demand response - taxi). Both are the
paratransit/NEMT universe Milexium targets.

Output: ntd/raw/metrics_dr.csv, ntd/raw/service_dr.csv
"""

import io
from pathlib import Path

import pandas as pd
import requests

RAW = Path(__file__).parent / "raw"
RAW.mkdir(exist_ok=True)

BASE = "https://data.transportation.gov/resource"
DATASETS = {
    "metrics_dr.csv": {
        "id": "ekg5-frzt",
        "where": "mode in('DR','DT')",
    },
    "service_dr.csv": {
        "id": "wwdp-t4re",
        "where": "mode in('DR','DT') AND time_period='Annual Total'",
    },
}


def fetch(dataset_id: str, where: str) -> pd.DataFrame:
    url = f"{BASE}/{dataset_id}.csv"
    params = {"$where": where, "$limit": 200000}
    r = requests.get(url, params=params, timeout=120)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text), low_memory=False)


if __name__ == "__main__":
    for fname, spec in DATASETS.items():
        df = fetch(spec["id"], spec["where"])
        df.to_csv(RAW / fname, index=False)
        years = sorted(df.report_year.unique().tolist())
        print(f"{fname}: {len(df)} rows, years {years}, "
              f"{df.agency.nunique()} agencies")
