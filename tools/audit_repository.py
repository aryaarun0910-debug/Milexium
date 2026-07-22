"""Audit TransitPulse repository structure and local data integrity.

The audit is read-only. It checks repository boundaries, panel schemas and
duplicate keys, raw Parquet containers, and monthly checkpoint continuity.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import date
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]
MONTH_RE = re.compile(r"^(\d{4}-\d{2})(?:\.partial)?\.csv$")
MARKDOWN_LINK_RE = re.compile(r"\[[^]]+\]\(([^)]+)\)")

PANELS = (
    ("realdata/panels/aar_hourly_borough.csv.gz",
     ("day", "hour", "provider_type", "borough"),
     ("day", "hour", "provider_type", "borough", "trips", "riders"),
     "trips", "day", True),
    ("realdata/panels/aar_daily.csv", ("date",),
     ("date", "scheduled_trips"), "scheduled_trips", "date", True),
    ("realdata/panels/ntd_monthly_dr.csv.gz",
     ("ntd_id", "mode", "tos", "date"),
     ("ntd_id", "agency", "mode", "tos", "date", "upt"),
     "upt", "date", True),
    ("realdata/panels/weather_daily.csv", ("city", "date"),
     ("city", "date", "tmax_c", "tmin_c", "precip_mm", "snow_cm"),
     "precip_mm", "date", True),
    ("realdata/panels/weather_hourly.csv.gz", ("city", "date", "hour"),
     ("city", "date", "hour", "temp_c", "precip_mm", "wind_kph"),
     "precip_mm", "date", True),
    ("realdata/panels/chicago_tnp_zone_hour.csv.gz",
     ("date", "hour", "area"), ("date", "hour", "area", "trips"),
     "trips", "date", False),
    ("realdata/panels/mta_bus_route_hour.csv.gz",
     ("date", "hour", "route"), ("date", "hour", "route", "riders"),
     "riders", "date", False),
    ("realdata/panels/mta_subway_station_hour.csv.gz",
     ("date", "hour", "station_id", "borough"),
     ("date", "hour", "station_id", "borough", "riders"),
     "riders", "date", False),
)

IGNORED_DATA_DIRS = (
    "realdata/raw_tlc", "realdata/raw_tlc_taxi", "realdata/output",
    "realdata/panels/mta_bus_monthly", "realdata/panels/mta_subway_monthly",
    "realdata/panels/chicago_monthly", "reference_agency/output",
    "outreach/drafts",
)

CHECKPOINT_DIRS = (
    "realdata/panels/mta_bus_monthly",
    "realdata/panels/mta_subway_monthly",
    "realdata/panels/chicago_monthly",
)


def month_range(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    y2, m2 = map(int, last.split("-"))
    months = []
    while (y, m) <= (y2, m2):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def parquet_container_ok(path: Path) -> bool:
    if path.stat().st_size < 12:
        return False
    with path.open("rb") as handle:
        head = handle.read(4)
        handle.seek(-4, 2)
        tail = handle.read(4)
    return head == b"PAR1" and tail == b"PAR1"


def audit_structure(errors: list[str]) -> dict:
    expected = ("realdata", "ntd", "reference_agency", "kaggle", "outreach",
                "web", "docs", "artifacts", "tools")
    stale = ("pipeline", "graphify-out", "YC_APPLICATION_NOTES.md",
             "cold_outreach_template.md", "outreach_target_list.md")
    missing = [name for name in expected if not (ROOT / name).exists()]
    present_stale = [name for name in stale if (ROOT / name).exists()]
    errors.extend(f"missing canonical path: {name}" for name in missing)
    errors.extend(f"stale top-level path remains: {name}" for name in present_stale)

    ignore_failures = []
    for relative in IGNORED_DATA_DIRS:
        directory = ROOT / relative
        if not directory.exists():
            continue
        sample = next((p for p in directory.rglob("*") if p.is_file()), directory)
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(sample)], cwd=ROOT,
            check=False, capture_output=True)
        if result.returncode:
            ignore_failures.append(relative)
    errors.extend(f"local data path is not ignored: {p}" for p in ignore_failures)
    return {"missing": missing, "stale": present_stale,
            "ignore_failures": ignore_failures}


def audit_markdown(errors: list[str]) -> dict:
    files = [ROOT / "README.md", ROOT / "realdata" / "README.md",
             ROOT / "ntd" / "README.md", ROOT / "reference_agency" / "README.md"]
    files.extend(p for p in (ROOT / "docs").rglob("*.md")
                 if "archive" not in p.parts)
    broken = []
    for path in sorted(set(files)):
        for target in MARKDOWN_LINK_RE.findall(path.read_text(encoding="utf-8")):
            target = target.split("#", 1)[0].strip("<>")
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            if not (path.parent / target).resolve().exists():
                broken.append(f"{path.relative_to(ROOT)} -> {target}")
    errors.extend(f"broken Markdown link: {item}" for item in broken)
    return {"files_checked": len(set(files)), "broken": broken}


def audit_panels(errors: list[str], warnings: list[str]) -> list[dict]:
    con = duckdb.connect()
    results = []
    for path_text, keys, required, value, date_column, tracked in PANELS:
        path = ROOT / path_text
        if not path.exists():
            (errors if tracked else warnings).append(f"panel missing: {path_text}")
            continue
        source = f"read_csv_auto('{sql_path(path)}', header=true)"
        columns = {row[0] for row in con.execute(
            f"DESCRIBE SELECT * FROM {source}").fetchall()}
        missing = sorted(set(required) - columns)
        if missing:
            errors.append(f"{path_text} missing columns: {', '.join(missing)}")
            continue
        count, first, last, total = con.execute(
            f'SELECT count(*), min("{date_column}"), max("{date_column}"), '
            f'sum("{value}") FROM {source}').fetchone()
        key_sql = ", ".join(f'"{key}"' for key in keys)
        duplicates = con.execute(
            f"SELECT coalesce(sum(n - 1), 0) FROM (SELECT count(*) AS n "
            f"FROM {source} GROUP BY {key_sql} HAVING count(*) > 1)").fetchone()[0]
        if duplicates:
            errors.append(f"{path_text} has {duplicates:,} duplicate-key rows")
        results.append({"path": path_text, "rows": count, "first": str(first),
                        "last": str(last), "total": float(total or 0),
                        "duplicates": int(duplicates), "tracked": tracked})
    con.close()
    return results


def audit_raw_parquet(errors: list[str], warnings: list[str]) -> list[dict]:
    configs = (
        ("realdata/raw_tlc", "fhvhv_tripdata_", "2019-02", "2026-05", True),
        ("realdata/raw_tlc_taxi", "yellow_tripdata_", None, None, False),
        ("realdata/raw_tlc_taxi", "green_tripdata_", None, None, False),
    )
    results = []
    for directory, prefix, first_expected, last_expected, complete in configs:
        root = ROOT / directory
        files = sorted(root.glob(f"{prefix}*.parquet")) if root.exists() else []
        bad = [str(p.relative_to(ROOT)) for p in files if not parquet_container_ok(p)]
        errors.extend(f"invalid Parquet container: {item}" for item in bad)
        months = [p.stem.removeprefix(prefix) for p in files]
        missing = []
        if complete:
            expected = set(month_range(first_expected, last_expected))
            missing = sorted(expected - set(months))
            errors.extend(f"{directory} missing expected month {m}" for m in missing)
        elif not files:
            warnings.append(f"unfinished source has no files: {directory}/{prefix}*")
        results.append({"directory": directory, "prefix": prefix,
                        "files": len(files),
                        "gb": round(sum(p.stat().st_size for p in files) / 2**30, 2),
                        "first": min(months) if months else None,
                        "last": max(months) if months else None,
                        "missing": missing, "bad_containers": bad})
    return results


def audit_checkpoints(errors: list[str]) -> list[dict]:
    results = []
    for relative in CHECKPOINT_DIRS:
        directory = ROOT / relative
        files = sorted(directory.glob("*.csv")) if directory.exists() else []
        final, partial, invalid = [], [], []
        for file in files:
            match = MONTH_RE.match(file.name)
            if not match:
                invalid.append(file.name)
            elif ".partial.csv" in file.name:
                partial.append(match.group(1))
            else:
                final.append(match.group(1))
            if file.stat().st_size <= 64:
                errors.append(f"empty checkpoint file: {relative}/{file.name}")
        errors.extend(f"invalid checkpoint filename: {relative}/{name}"
                      for name in invalid)
        all_months = sorted(set(final + partial))
        missing = []
        if all_months:
            missing = sorted(set(month_range(all_months[0], all_months[-1]))
                             - set(all_months))
            errors.extend(f"{relative} missing checkpoint month {m}" for m in missing)
        overlap = sorted(set(final) & set(partial))
        errors.extend(f"{relative} has final and partial checkpoint for {m}"
                      for m in overlap)
        results.append({"directory": relative, "files": len(files),
                        "first": all_months[0] if all_months else None,
                        "last": all_months[-1] if all_months else None,
                        "partial": partial, "missing": missing,
                        "invalid": invalid})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path,
                        help="optional path for a machine-readable report")
    args = parser.parse_args()
    errors: list[str] = []
    warnings: list[str] = []
    report = {
        "audit_date": date.today().isoformat(),
        "structure": audit_structure(errors),
        "markdown": audit_markdown(errors),
        "panels": audit_panels(errors, warnings),
        "raw_parquet": audit_raw_parquet(errors, warnings),
        "checkpoints": audit_checkpoints(errors),
    }
    report["errors"] = errors
    report["warnings"] = warnings

    print("TransitPulse repository audit")
    for item in report["panels"]:
        print(f"  {item['path']}: {item['rows']:,} rows, "
              f"{item['first']} to {item['last']}, duplicates={item['duplicates']}")
    for item in report["raw_parquet"]:
        print(f"  {item['directory']}/{item['prefix']}*: "
              f"{item['files']} files, {item['gb']:.2f} GB")
    for item in report["checkpoints"]:
        print(f"  {item['directory']}: {item['files']} files, "
              f"missing={len(item['missing'])}, partial={item['partial']}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    if args.json:
        destination = args.json if args.json.is_absolute() else ROOT / args.json
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"  report: {destination}")
    print(f"Audit {'FAILED' if errors else 'PASSED'}: "
          f"{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
