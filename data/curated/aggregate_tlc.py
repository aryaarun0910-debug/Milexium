"""Aggregate the bulk NYC TLC FHVHV parquet corpus to a zone-hour panel.

DuckDB streams the roughly 40 GB of monthly parquet out-of-core, so this
runs on a laptop in minutes and never loads raw trips into memory. Result:
about 1.5 billion real door-to-door trips compressed to a 265-zone hourly
demand panel, the training corpus for the transformer.

Run after (or during) data/curated/fetch_tlc_parquet.py; it aggregates
whatever months are on disk.

Output: data/curated/panels/nyc_fhvhv_zone_hour.parquet
  columns: date, hour, zone (TLC taxi zone id), trips
"""

from pathlib import Path

import duckdb

HERE = Path(__file__).parent
RAW = HERE / "raw_tlc"
PANELS = HERE / "panels"
PANELS.mkdir(exist_ok=True)

files = sorted(RAW.glob("fhvhv_tripdata_*.parquet"))
if not files:
    raise SystemExit("no parquet files in data/curated/raw_tlc yet")
print(f"aggregating {len(files)} monthly files "
      f"({sum(f.stat().st_size for f in files) / 1e9:.1f} GB)")

con = duckdb.connect()
con.execute(f"SET threads TO 8; SET memory_limit='6GB'")
out = PANELS / "nyc_fhvhv_zone_hour.parquet"
con.execute(f"""
    COPY (
        SELECT CAST(pickup_datetime AS DATE) AS date,
               EXTRACT(hour FROM pickup_datetime) AS hour,
               PULocationID AS zone,
               COUNT(*) AS trips
        FROM read_parquet('{RAW.as_posix()}/fhvhv_tripdata_*.parquet',
                          union_by_name=true)
        GROUP BY ALL
        ORDER BY date, hour, zone
    ) TO '{out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
""")
n, total = con.execute(
    f"SELECT COUNT(*), SUM(trips) FROM read_parquet('{out.as_posix()}')"
).fetchone()
print(f"saved {out}: {n:,} panel rows, {total:,} trips")
