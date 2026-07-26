"""H3b -- a weather test that needs no weather API: seasonal amplitude by climate.

Run:  python research/h3b_seasonality.py

The NOAA endpoints throttled hard enough to make the direct monthly-weather
panel unreliable to assemble inside this packet. This is a substitute test of
the same hypothesis using only bytes already on disk, and it is arguably a
cleaner one.

If weather suppresses demand-response demand, then metros with severe winters
must show a DEEPER WINTER TROUGH in monthly trips than metros without winters.
That prediction is sharp, it needs no weather data at all -- only the knowledge
of which cities have snow -- and it is falsifiable.

Controls that matter for demand response specifically:
  * Demand response is overwhelmingly a weekday service (dialysis, day
    programmes, standing orders), so raw monthly totals are dominated by how
    many weekdays a month contains. Every series here is trips PER WEEKDAY.
  * Each agency is normalised to its own annual mean, so agency size drops out.
  * COVID years 2020-2021 are excluded.

Snow-metro classification is made from geography before looking at any result.
"""

from __future__ import annotations

import calendar
import csv
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
import sys  # noqa: E402

sys.path.insert(0, str(HERE))
from lib import MONTHLY, mean, median, parse_month, say  # noqa: E402

# NTD ID -> (label, has_real_winter). Classified from geography, in advance.
METROS = {
    "50008": ("Minneapolis Metropolitan Council", True),
    "10003": ("Boston MBTA", True),
    "50015": ("Cleveland RTA", True),
    "50021": ("Milwaukee County", True),
    "30040": ("Pittsburgh PAAC", True),
    "50066": ("Chicago Pace", True),
    "30034": ("Baltimore Maryland MTA", True),
    "80006": ("Denver RTD", True),
    "80005": ("Utah Transit Authority", True),
    "30019": ("Philadelphia SEPTA", True),
    "20008": ("MTA New York City Transit", True),
    "30030": ("Washington WMATA", True),
    "40034": ("Miami-Dade", False),
    "90030": ("Phoenix Valley Metro", False),
    "60008": ("Houston METRO", False),
    "90154": ("LA Access Services", False),
    "60048": ("San Antonio VIA", False),
    "90019": ("Las Vegas RTC", False),
    "90003": ("Honolulu", False),
    "40022": ("Atlanta MARTA", False),
    "60056": ("Dallas DART", False),
    "00001": ("Seattle King County", False),
    "00008": ("Portland TriMet", False),
}
YEARS = set(range(2015, 2020)) | set(range(2022, 2026))
WINTER = (12, 1, 2)
SUMMER = (6, 7, 8)


def weekdays(y: int, m: int) -> int:
    return sum(
        1
        for d in range(1, calendar.monthrange(y, m)[1] + 1)
        if calendar.weekday(y, m, d) < 5
    )


def main() -> None:
    upt = defaultdict(float)
    with open(MONTHLY, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row["Mode"] != "DR" or row["NTD ID"] not in METROS:
                continue
            y, m = parse_month(row["Date"])
            if y not in YEARS:
                continue
            v = row["UPT"].strip().replace(",", "")
            if v:
                upt[(row["NTD ID"], y, m)] += float(v)
    say(f"agency-months loaded: {len(upt)}")

    # per-agency month-of-year index of trips PER WEEKDAY, normalised to own mean
    out = {}
    say(
        f"\n{'agency':<34}{'winter idx':>12}{'summer idx':>12}"
        f"{'W-S gap':>10}{'n mths':>8}"
    )
    say("  (index 1.000 = that agency's own average weekday demand)")
    rows_snow, rows_warm = [], []
    for nid, (label, snowy) in METROS.items():
        per = [
            ((y, m), v / weekdays(y, m))
            for (a, y, m), v in upt.items()
            if a == nid and v > 0
        ]
        if len(per) < 60:
            continue
        base = mean([v for _, v in per])
        if not base:
            continue
        bym = defaultdict(list)
        for (y, m), v in per:
            bym[m].append(v / base)
        idx = {m: mean(vs) for m, vs in bym.items()}
        if len(idx) < 12:
            continue
        w = mean([idx[m] for m in WINTER])
        s = mean([idx[m] for m in SUMMER])
        say(
            f"{label[:33]:<34}{w:>12.4f}{s:>12.4f}{w-s:>10.4f}{len(per):>8}"
            f"{'   [snow]' if snowy else ''}"
        )
        rec = {"label": label, "snowy": snowy, "winter": w, "summer": s, "gap": w - s,
               "index": idx, "n_months": len(per)}
        out[nid] = rec
        (rows_snow if snowy else rows_warm).append(rec)

    say("\n" + "=" * 70)
    say("THE TEST: do snow metros have a deeper winter trough than warm metros?")
    say("=" * 70)
    for name, grp in (("snow metros", rows_snow), ("warm metros", rows_warm)):
        say(
            f"  {name:<14} n={len(grp):<3} "
            f"median winter index {median([g['winter'] for g in grp]):.4f}   "
            f"median summer index {median([g['summer'] for g in grp]):.4f}   "
            f"median winter-summer gap {median([g['gap'] for g in grp]):+.4f}"
        )
    diff = median([g["gap"] for g in rows_snow]) - median([g["gap"] for g in rows_warm])
    say(f"\n  DIFFERENCE IN GAPS (snow minus warm): {diff:+.4f}")
    say(
        "  A weather effect predicts this is clearly NEGATIVE (snow metros lose "
        "more demand in winter)."
    )

    say("\n  Month-of-year index, group medians:")
    say(f"    {'month':<8}" + "".join(f"{m:>8}" for m in range(1, 13)))
    for name, grp in (("snow", rows_snow), ("warm", rows_warm)):
        say(
            f"    {name:<8}"
            + "".join(f"{median([g['index'][m] for g in grp]):>8.3f}" for m in range(1, 13))
        )

    # how big is seasonality at all, relative to agency-to-agency spread?
    amp = [max(g["index"].values()) - min(g["index"].values()) for g in out.values()]
    say(
        f"\n  Peak-to-trough seasonal amplitude across all {len(out)} metros: "
        f"median {median(amp):.3f} (i.e. {100*median(amp):.1f}% of mean demand)"
    )

    res = {
        "n_metros": len(out),
        "snow_median_gap": median([g["gap"] for g in rows_snow]),
        "warm_median_gap": median([g["gap"] for g in rows_warm]),
        "difference_in_gaps": diff,
        "median_peak_to_trough_amplitude": median(amp),
        "per_agency": out,
    }
    (HERE / "h3b_seasonality.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    say("\nwrote research/h3b_seasonality.json")


if __name__ == "__main__":
    main()
