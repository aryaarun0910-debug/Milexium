"""Compute ONE true, non-obvious, peer-relative fact per outreach target.

Why this exists
---------------
The previous cold-email hook led with the agency's own NTD deadhead figure.
That fails the only test that matters: an ops director ALREADY KNOWS their own
deadhead -- they filed it. Reciting their homework back earns "yes, and?", not
"how did they know that?".

What they cannot see is where they sit against their peers nationally. That
requires the full NTD demand-response panel, which they do not have loaded and
are not going to compute. A national rank is the stain on their own back: true,
specific, checkable, and invisible from the inside.

Honesty rules (non-negotiable, mirrors the repo's evidence discipline)
---------------------------------------------------------------------
- Every number emitted here is COMPUTED from ntd/agency_economics.csv, never
  asserted. `evidence` records exactly how, so any claim can be re-derived.
- Peer group is stated explicitly in the output. A rank means nothing without
  the comparison set, and a vague peer group is how benchmarks become lies.
- Only report_year 2024 is used: 2022/2023 have 18/30 rows in this extract, far
  too sparse for a trend. So NO trend claims are generated. If we later hold a
  real multi-year panel, that becomes the better hook.
- A target with too few peers to rank honestly emits `insufficient_peers`
  and gets NO stat -- it must be approached a different way rather than
  given a weak number.
- The dollar figure is a MODELLED gap (opex attributed to hours uniformly), so
  it is always emitted with hedged wording. Fixed costs do not fall
  proportionally; the free analysis is what pins the real number down.

Peer group definition
---------------------
Same NTD reporter universe, demand-response service, report year 2024, within
a trip-volume band (0.5x-2x the target's annual demand-response trips). Volume
band rather than state, because operating scale drives deadhead economics far
more than geography does.

Usage:
  py -3 outreach/build_peer_insight.py                 # all worksheet rows with an email
  py -3 outreach/build_peer_insight.py --agency SamTrans
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
REPO = HERE.parent
NTD = REPO / "ntd" / "agency_economics.csv"
WORKSHEET = HERE / "contact_research_worksheet.csv"
OUT = HERE / "peer_insights.json"

YEAR = 2024
BAND_LO, BAND_HI = 0.5, 2.0
MIN_PEERS = 12  # below this a percentile is noise, not a finding
MIN_GAP_POINTS = 2.5  # a smaller gap than this is not a finding worth leading with


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def peer_frame(df: pd.DataFrame, row: pd.Series) -> pd.DataFrame:
    """Agencies of comparable operating scale in the same report year."""
    trips = row["trips"]
    return df[
        (df["report_year"] == YEAR)
        & (df["trips"] >= trips * BAND_LO)
        & (df["trips"] <= trips * BAND_HI)
        & (df["trips"] > 0)
        & (df["deadhead_pct_hours"].notna())
    ]


def insight_for(df: pd.DataFrame, ntd_id: int) -> dict:
    """The single strongest true statement we can make about this agency."""
    match = df[(df["ntd_id"] == ntd_id) & (df["report_year"] == YEAR)]
    if match.empty:
        return {"status": "not_in_panel"}
    row = match.iloc[0]
    peers = peer_frame(df, row)
    n = len(peers)
    if n < MIN_PEERS:
        return {"status": "insufficient_peers", "n_peers": int(n)}

    dh = float(row["deadhead_pct_hours"])
    median_dh = float(peers["deadhead_pct_hours"].median())
    # rank 1 == highest empty-hour share (worst)
    rank = int((peers["deadhead_pct_hours"] > dh).sum()) + 1
    pct_above = float((peers["deadhead_pct_hours"] < dh).mean() * 100)

    # Productivity: trips completed per revenue vehicle-hour.
    tph = float(row["trips_per_vrh"])
    median_tph = float(peers["trips_per_vrh"].median())
    tph_rank = int((peers["trips_per_vrh"] > tph).sum()) + 1

    # Modelled value of closing the deadhead gap to the peer median. Uses the
    # agency's own opex-per-hour, and is only meaningful when they are ABOVE
    # median (i.e. there is a gap to close).
    gap_pts = dh - median_dh
    gap_value = None
    if gap_pts > 0 and row["actual_hours"] and row["opex"]:
        cost_per_hour = float(row["opex"]) / float(row["actual_hours"])
        gap_value = gap_pts * float(row["actual_hours"]) * cost_per_hour

    return {
        "status": "ok",
        "agency": str(row["agency"]),
        "state": str(row["state"]),
        "trips": int(row["trips"]),
        "deadhead_pct_hours": round(dh * 100, 1),
        "peer_median_deadhead_pct": round(median_dh * 100, 1),
        "deadhead_rank": rank,
        "deadhead_worse_than_pct_of_peers": round(pct_above, 0),
        "trips_per_vrh": round(tph, 2),
        "peer_median_trips_per_vrh": round(median_tph, 2),
        "trips_per_vrh_rank": tph_rank,
        "n_peers": n,
        "gap_points": round(gap_pts * 100, 1) if gap_pts > 0 else None,
        "modelled_gap_value_usd": round(gap_value) if gap_value else None,
        "peer_group": (
            f"{n} US demand-response operators reporting {int(row['trips']*BAND_LO):,}-"
            f"{int(row['trips']*BAND_HI):,} annual trips in NTD {YEAR}"
        ),
        "evidence": (
            f"ntd/agency_economics.csv, report_year={YEAR}, ntd_id={ntd_id}; "
            f"peer band {BAND_LO}x-{BAND_HI}x trips (n={n}); rank on deadhead_pct_hours "
            f"descending; gap value = (own dh% - peer median dh%) * actual_hours * "
            f"(opex/actual_hours)"
        ),
    }


def headline(ins: dict) -> str | None:
    """The first line of the email: the one fact they cannot see themselves.

    Picks whichever true statement is strongest for this agency, rather than
    forcing every agency into the same sentence."""
    if ins.get("status") != "ok":
        return None
    n, rank = ins["n_peers"], ins["deadhead_rank"]
    dh, med = ins["deadhead_pct_hours"], ins["peer_median_deadhead_pct"]
    # Strongest when they are a genuine outlier near the top of the pack.
    if rank <= max(3, n // 10):
        return (
            f"Of the {n} US transit operators running roughly your number of "
            f"demand-response trips, you have the {_ordinal(rank)}-highest share "
            f"of vehicle-hours running empty."
        )
    if dh - med >= MIN_GAP_POINTS:
        return (
            f"Against the {n} US operators closest to your size, your empty "
            f"vehicle-hours run {round(dh - med, 1)} points above the median "
            f"({dh}% vs {med}%)."
        )
    # HONESTY GATE: a sub-2.5-point gap at mid-rank is noise, not a finding.
    # Manufacturing a problem out of it is exactly the "slop" this file exists
    # to kill -- and an ops director who knows their numbers will see through
    # it instantly, costing us the one contact we get. Emit nothing; these
    # targets need a genuinely different angle (see needs_different_angle).
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", help="filter worksheet by short_name substring")
    args = ap.parse_args()

    df = pd.read_csv(NTD)
    rows = [
        r
        for r in csv.DictReader(open(WORKSHEET, encoding="utf-8-sig"))
        if (r.get("contact_email") or "").strip()
    ]
    if args.agency:
        rows = [r for r in rows if args.agency.lower() in r["short_name"].lower()]

    out = {}
    counts = {"ok": 0, "insufficient_peers": 0, "not_in_panel": 0, "no_ntd_id": 0}
    for r in rows:
        # match worksheet -> panel on the full agency string
        m = df[(df["agency"] == r["agency"]) & (df["report_year"] == YEAR)]
        if m.empty:
            counts["no_ntd_id"] += 1
            out[r["short_name"]] = {"status": "no_ntd_id"}
            continue
        ins = insight_for(df, int(m.iloc[0]["ntd_id"]))
        ins["headline"] = headline(ins)
        ins["contact_name"] = r.get("contact_name", "")
        ins["contact_email"] = r.get("contact_email", "")
        # Carried through so the generator can refuse to write a draft for a
        # contact nobody has actually laid eyes on (see generate_v3_emails.py).
        ins["contact_confidence"] = r.get("contact_confidence", "")
        out[r["short_name"]] = ins
        counts[ins["status"]] = counts.get(ins["status"], 0) + 1

    OUT.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")
    print("status counts:", counts)
    for name, ins in sorted(out.items()):
        if ins.get("headline"):
            print(f"\n[{name}] n_peers={ins['n_peers']}")
            print("  " + ins["headline"])


if __name__ == "__main__":
    main()
