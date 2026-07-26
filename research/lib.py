"""Shared loaders for MX-RND-HYPOTHESIS-MINING-011.

R&D scaffolding. Every function here reads one of the governed files named in
the packet brief and returns plain Python structures. No file under this module
writes anywhere except `research/` and the session scratchpad.

CPI-U anchors are fixed by the packet brief: 2015=237.017, 2024=313.689.
Intermediate years are the published CPI-U annual averages, used only to deflate
money and always reported alongside nominal.
"""

from __future__ import annotations

import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PUB = REPO / "data" / "raw" / "public"

MONTHLY = PUB / "ntd-monthly-ridership-all-modes.529952083544f257.csv"
OPEX = PUB / "ntd-service-opex-by-mode-timeseries.e6e821f63751d429.csv"
WEBLINKS = PUB / "ntd-gtfs-weblinks.9c73ba1b2ddf3bc5.csv"
ECON = REPO / "business" / "ntd" / "agency_economics.csv"
CENSUS = REPO / "business" / "ntd" / "census_latent_demand.csv"
DEADHEAD_SUMMARY = REPO / "data" / "catalog" / "calitp-scheduled-deadhead.summary.json"

# CPI-U annual averages (BLS, all urban consumers, 1982-84=100).
# 2015 and 2024 are the anchors mandated by the packet brief.
CPI = {
    2015: 237.017,
    2016: 240.007,
    2017: 245.120,
    2018: 251.107,
    2019: 255.657,
    2020: 258.811,
    2021: 270.970,
    2022: 292.655,
    2023: 304.702,
    2024: 313.689,
}
CPI_BASE = CPI[2024]


def to_2024_dollars(value: float, year: int) -> float:
    """Deflate a nominal dollar amount from `year` into 2024 dollars."""
    return value * (CPI_BASE / CPI[year])


def _f(x: str) -> float | None:
    x = (x or "").strip().replace(",", "")
    if not x:
        return None
    try:
        return float(x)
    except ValueError:
        return None


def load_opex_panel(modes: set[str] | None = None) -> dict:
    """agency-year-mode panel from the service+opex timeseries (2015-2024).

    Returns {(ntd_id, year, mode, tos): {field: value}} plus a metadata dict
    {ntd_id: {...agency attributes...}}.
    """
    panel: dict[tuple[str, int, str, str], dict[str, float]] = defaultdict(dict)
    meta: dict[str, dict[str, str]] = {}
    with open(OPEX, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            mode = row["Mode"]
            if modes and mode not in modes:
                continue
            nid = row["NTD ID"]
            year = int(row["Report Year"])
            key = (nid, year, mode, row["Type of Service"])
            val = _f(row["Value"])
            if val is not None:
                panel[key][row["Field"]] = val
            if nid not in meta:
                meta[nid] = {
                    "agency": row["Agency Name"],
                    "city": row["City"],
                    "state": row["State"],
                    "uza_name": row["Primary UZA Name"],
                    "uza_population": row["UZA Population"],
                    "uza_sq_miles": row["UZA Area SQ Miles"],
                    "reporter_type": row["Reporter Type"],
                    "uace": row["UACE Code"],
                }
    return {"panel": dict(panel), "meta": meta}


def load_monthly(modes: set[str] | None = None):
    """Yield dicts from the monthly ridership file, optionally mode-filtered."""
    with open(MONTHLY, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if modes and row["Mode"] not in modes:
                continue
            yield row


MONTH_NUM = {
    m: i + 1
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ]
    )
}


def parse_month(s: str) -> tuple[int, int]:
    name, year = s.split()
    return int(year), MONTH_NUM[name]


def load_econ() -> list[dict]:
    with open(ECON, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def env(key: str) -> str | None:
    """Read a secret from the environment or .env. NEVER print the result."""
    v = os.environ.get(key)
    if v:
        return v
    envfile = REPO / ".env"
    if envfile.exists():
        for line in envfile.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, val = line.partition("=")
            if k.strip() == key:
                return val.strip().strip('"').strip("'")
    return None


# ---- small stats helpers (no scipy dependency assumed) --------------------


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = mean(xs), mean(ys)
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(xs, ys):
    if len(xs) < 3:
        return None
    return pearson(rank(list(xs)), rank(list(ys)))


def ols(X, y):
    """Plain multivariate OLS with intercept. X is list of rows (list of floats).

    Returns (coefficients_including_intercept, r2). Solved by Gaussian
    elimination on the normal equations; fine at this problem size.
    """
    n = len(y)
    p = len(X[0]) + 1
    A = [[1.0] + list(row) for row in X]
    XtX = [[sum(A[i][a] * A[i][b] for i in range(n)) for b in range(p)] for a in range(p)]
    Xty = [sum(A[i][a] * y[i] for i in range(n)) for a in range(p)]
    # Gaussian elimination with partial pivoting
    M = [XtX[i][:] + [Xty[i]] for i in range(p)]
    for c in range(p):
        piv = max(range(c, p), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            return None, None
        M[c], M[piv] = M[piv], M[c]
        for r in range(p):
            if r == c:
                continue
            f = M[r][c] / M[c][c]
            for k in range(c, p + 1):
                M[r][k] -= f * M[c][k]
    beta = [M[i][p] / M[i][i] for i in range(p)]
    yhat = [sum(beta[j] * A[i][j] for j in range(p)) for i in range(n)]
    ybar = mean(y)
    ss_res = sum((y[i] - yhat[i]) ** 2 for i in range(n))
    ss_tot = sum((v - ybar) ** 2 for v in y)
    return beta, (1 - ss_res / ss_tot if ss_tot else None)


def say(*a):
    print(*a, flush=True, file=sys.stdout)
