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
- Every number emitted here is COMPUTED from business/ntd/agency_economics.csv, never
  asserted. `evidence` records exactly how, so any claim can be re-derived.
- Peer group is stated explicitly in the output. A rank means nothing without
  the comparison set, and a vague peer group is how benchmarks become lies.
- Only report_year 2024 is used: 2022/2023 have 18/30 rows in this extract, far
  too sparse for a trend. So NO trend claims are generated. If we later hold a
  real multi-year panel, that becomes the better hook.
- A target with too few peers to rank honestly emits `insufficient_peers`
  and gets NO stat -- it must be approached a different way rather than
  given a weak number.
- NO DOLLAR FIGURE IS EMITTED. `modelled_gap_value_usd` used to be computed
  here as (own deadhead % - peer median deadhead %) * actual_hours * own cost
  per hour, and generate_v3_emails.py rendered it as "at your cost per hour the
  gap is roughly $X a year". It is REMOVED (packet
  MX-CLAIMS-DOLLAR-SWEEP-013), and the hedge that travelled with it is not a
  defence, because the problem was the premise rather than the precision. That
  figure is not an accounting identity on the operator's own filing; it is the
  value of a COUNTERFACTUAL in which the operator sits at the peer median, and
  it therefore asserts that the distance to the median is recoverable. Nothing
  measures that. Worse, the distance being priced is a deadhead distance, and
  deadhead share does not identify an expensive agency: Spearman +0.024 against
  cost per trip over 406 operators, versus +0.738 for cost per HOUR
  (business/outreach/panel_findings.json, `dr_deadhead_predicts_cost_per_trip`,
  REJECTED by the panel gate); Pearson +0.017, OLS R2 0.0003 at n=405
  (research/h5b_structure_vs_cost.json).

STILL OUTSTANDING IN THIS FILE (not fixed by that packet, which owned dollar
claims only): the RANK itself is still a deadhead rank. Being 9th of 151 on
empty vehicle-hours is a true fact about an operator, but it is not evidence
that the operator has a cost problem, and leading with it implies that it is.
business/outreach/README.md carries the standing instruction not to send another
deadhead-ranked agency email until this engine is rebuilt on occupancy
(research/h5e_ridesharing.json), scoped to the larger operators who file
passenger miles.

Peer group definition
---------------------
Same NTD reporter universe, demand-response service, report year 2024, within
a trip-volume band (0.5x-2x the target's annual demand-response trips). Volume
band rather than state, because operating scale drives deadhead economics far
more than geography does.

Usage:
  py -3 business/outreach/build_peer_insight.py                 # all worksheet rows with an email
  py -3 business/outreach/build_peer_insight.py --agency SamTrans
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
REPO = HERE.parents[1]
NTD = REPO / "business" / "ntd" / "agency_economics.csv"
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

    # Distance to the peer median, in percentage points. Deliberately NOT
    # priced: see the module docstring. A gap in points is a comparison; the
    # same gap in dollars is a claim that closing it is worth that much.
    gap_pts = dh - median_dh

    # Cost per revenue hour, and where it sits in the peer group. This is the
    # variable that actually ranks with cost per trip (+0.738 vs +0.024 for
    # deadhead), so it is the honest place a reader's eye should land.
    cph = float(row["cost_per_vrh"]) if pd.notna(row["cost_per_vrh"]) else None
    median_cph = float(peers["cost_per_vrh"].median())
    cph_rank = (int((peers["cost_per_vrh"] > cph).sum()) + 1
                if cph is not None else None)

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
        "cost_per_vrh": round(cph, 2) if cph is not None else None,
        "peer_median_cost_per_vrh": round(median_cph, 2),
        "cost_per_vrh_rank": cph_rank,
        "n_peers": n,
        "gap_points": round(gap_pts * 100, 1) if gap_pts > 0 else None,
        "no_dollar_value_is_emitted": (
            "the distance to the peer median is not known to be recoverable; "
            "pricing it would assert a causal claim nothing here measures"),
        "peer_group": (
            f"{n} US demand-response operators reporting {int(row['trips']*BAND_LO):,}-"
            f"{int(row['trips']*BAND_HI):,} annual trips in NTD {YEAR}"
        ),
        "evidence": (
            f"business/ntd/agency_economics.csv, report_year={YEAR}, ntd_id={ntd_id}; "
            f"peer band {BAND_LO}x-{BAND_HI}x trips (n={n}); ranks on "
            f"deadhead_pct_hours, trips_per_vrh and cost_per_vrh, each "
            f"descending; gap_points = own dh% - peer median dh%, in points, "
            f"unpriced"
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
    all_rows = list(csv.DictReader(open(WORKSHEET, encoding="utf-8-sig")))

    # OPT-OUTS ARE DROPPED HERE, BEFORE ANYTHING IS COMPUTED ABOUT THEM.
    # `do_not_contact` is permanent and structural (business/outreach/README.md), and
    # generate_expert_emails.py has always honoured it -- but this agency
    # pipeline did not, so Anne Arundel County, which asked in writing to be
    # removed from the list, still had a ready-to-send draft generated with
    # transportation@aacounty.org in the To: line. An opt-out that only one of
    # two pipelines enforces is not an opt-out.
    opted_out = sorted(
        r["short_name"] for r in all_rows if (r.get("do_not_contact") or "").strip()
    )
    rows = [
        r
        for r in all_rows
        if (r.get("contact_email") or "").strip()
        and not (r.get("do_not_contact") or "").strip()
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
    if opted_out:
        print(f"do_not_contact, no insight computed ({len(opted_out)}): "
              + ", ".join(opted_out))
    for name, ins in sorted(out.items()):
        if ins.get("headline"):
            print(f"\n[{name}] n_peers={ins['n_peers']}")
            print("  " + ins["headline"])


if __name__ == "__main__":
    main()
