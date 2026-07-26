"""H1 -- the definitional gap between SCHEDULED and OPERATED deadhead.

The packet brief asks: for California agencies present in both the Cal-ITP
GTFS-derived scheduled deadhead (ADR-0062) and NTD operated deadhead, how far
apart are the two, and is the gap stable?

Before measuring a gap you must establish that the two numbers describe the
same vehicles. This script tests that precondition first, because if it fails
the gap is not a calibration, it is a category error.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict

from lib import DEADHEAD_SUMMARY, ECON, WEBLINKS, median, pct, pearson, say, spearman


def norm(name: str) -> str:
    s = (name or "").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(
        r"\b(the|inc|authority|agency|district|transit|transportation|of|for|and|"
        r"regional|county|city|public|services|service|system|systems|department|"
        r"dept|corporation|corp|company|co|llc)\b",
        " ",
        s,
    )
    return re.sub(r"\s+", " ", s).strip()


def main() -> None:
    say("=" * 78)
    say("H1  SCHEDULED (GTFS) vs OPERATED (NTD) deadhead")
    say("=" * 78)

    # ---- Step 0: what mode does each side actually describe? --------------
    # The NTD GTFS weblinks file declares, per agency AND PER MODE, whether a
    # GTFS feed is on file. If demand-response modes essentially never carry a
    # feed, then no GTFS-derived number can describe demand-response service.
    mode_has_link = Counter()
    mode_rows = Counter()
    dr_linked_agencies = set()
    ca_feed_urls = {}
    with open(WEBLINKS, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            m = row["Mode"]
            mode_rows[m] += 1
            link = (row["Weblink"] or "").strip()
            if link:
                mode_has_link[m] += 1
                if m == "DR":
                    dr_linked_agencies.add(row["NTD ID"])
                if row["State"] == "CA":
                    ca_feed_urls.setdefault(link.lower(), set()).add(
                        (row["NTD ID"], row["Agency Name"], m)
                    )

    say("\n[0] Does a GTFS feed exist for demand-response service at all?")
    say("    NTD GTFS weblinks file, rows by mode (feed present / total rows):")
    for m, tot in mode_rows.most_common(10):
        say(f"      {m:>3}  {mode_has_link[m]:>5} / {tot:>5}  ({100*mode_has_link[m]/tot:5.1f}%)")

    # ---- Step 1: load the two measurements --------------------------------
    summary = json.loads(DEADHEAD_SUMMARY.read_text(encoding="utf-8"))
    sched = {}
    for r in summary["per_agency"]:
        if r["scheduled_deadhead_hours"] <= 0:
            continue
        sched[norm(r["agency_name"])] = r

    econ = list(csv.DictReader(open(ECON, newline="", encoding="utf-8-sig")))
    oper = {}
    for r in econ:
        if r["report_year"] != "2024" or r["state"] != "CA":
            continue
        try:
            dh_h = float(r["deadhead_hours"] or 0)
            vrh = float(r["vrh"] or 0)
            act_h = float(r["actual_hours"] or 0)
        except ValueError:
            continue
        if dh_h <= 0 or act_h <= 0:
            continue
        oper[norm(r["agency"])] = {
            "agency": r["agency"],
            "ntd_id": r["ntd_id"],
            "deadhead_hours": dh_h,
            "vrh": vrh,
            "actual_hours": act_h,
            # NTD operated share, on the SAME denominator convention the GTFS
            # tool uses: deadhead / (deadhead + revenue).
            "operated_share": dh_h / act_h,
            "trips": float(r["trips"] or 0),
            "opex": float(r["opex"] or 0),
        }

    say(f"\n[1] CA agencies with a GTFS-derived SCHEDULED deadhead: {len(sched)}")
    say(f"    CA agencies with an NTD OPERATED deadhead (2024, DR-only): {len(oper)}")

    both = sorted(set(sched) & set(oper))
    say(f"    Name-matched intersection: {len(both)}")

    # ---- Step 2: the naive comparison, run so its size is on record -------
    rows = []
    for k in both:
        s, o = sched[k], oper[k]
        rows.append(
            {
                "agency": o["agency"],
                "ntd_id": o["ntd_id"],
                "sched_share": s["scheduled_deadhead_share_of_in_block_time"],
                "oper_share": o["operated_share"],
                "ratio": o["operated_share"] / s["scheduled_deadhead_share_of_in_block_time"]
                if s["scheduled_deadhead_share_of_in_block_time"]
                else None,
                "sched_dh_hours": s["scheduled_deadhead_hours"],
                "sched_rev_hours": s["scheduled_revenue_hours"],
                "oper_dh_hours": o["deadhead_hours"],
                "oper_rev_hours": o["vrh"],
            }
        )
    rows.sort(key=lambda r: -r["oper_share"])

    if rows:
        ss = [r["sched_share"] for r in rows]
        os_ = [r["oper_share"] for r in rows]
        ratios = [r["ratio"] for r in rows if r["ratio"]]
        say("\n[2] NAIVE comparison (fixed-route SCHEDULED vs DR OPERATED):")
        say(f"    n = {len(rows)} agencies")
        say(
            f"    scheduled share : median {median(ss):.4f}  "
            f"p10 {pct(ss,10):.4f}  p90 {pct(ss,90):.4f}"
        )
        say(
            f"    operated  share : median {median(os_):.4f}  "
            f"p10 {pct(os_,10):.4f}  p90 {pct(os_,90):.4f}"
        )
        say(
            f"    operated/scheduled ratio: median {median(ratios):.2f}x  "
            f"min {min(ratios):.2f}x  max {max(ratios):.2f}x  "
            f"p10 {pct(ratios,10):.2f}x  p90 {pct(ratios,90):.2f}x"
        )
        say(f"    Pearson r  (shares) = {pearson(ss, os_)}")
        say(f"    Spearman r (shares) = {spearman(ss, os_)}")
        say("\n    per-agency detail (sorted by operated share):")
        say(
            f"      {'agency':<44}{'sched':>8}{'oper':>8}{'ratio':>8}"
            f"{'schedH':>10}{'operH':>12}"
        )
        for r in rows:
            say(
                f"      {r['agency'][:43]:<44}{r['sched_share']:>8.4f}"
                f"{r['oper_share']:>8.4f}{r['ratio']:>8.2f}"
                f"{r['sched_dh_hours']:>10.0f}{r['oper_dh_hours']:>12.0f}"
            )

        # scale sanity: do the two even describe comparable amounts of service?
        say("\n[3] Scale check -- are these the same vehicles?")
        say(
            "    GTFS scheduled revenue hours are ONE service day; NTD hours are a "
            "full year. Implied days-of-service if the two covered the same fleet:"
        )
        impl = []
        for r in rows:
            if r["sched_rev_hours"] > 0:
                impl.append(r["oper_rev_hours"] / r["sched_rev_hours"])
        say(
            f"    implied service days: median {median(impl):.0f}  "
            f"min {min(impl):.0f}  max {max(impl):.0f}  "
            f"(a real agency operates 250-366 days/yr)"
        )
        n_plausible = sum(1 for v in impl if 200 <= v <= 400)
        say(
            f"    agencies whose implied days land in [200,400]: "
            f"{n_plausible}/{len(impl)} = {100*n_plausible/len(impl):.0f}%"
        )

    out = {
        "weblinks_feed_presence_by_mode": {
            m: {"rows": mode_rows[m], "with_feed": mode_has_link[m]} for m in mode_rows
        },
        "n_scheduled_ca": len(sched),
        "n_operated_ca_dr_2024": len(oper),
        "n_matched": len(both),
        "pairs": rows,
    }
    (DEADHEAD_SUMMARY.parent.parent.parent / "research" / "h1_deadhead_gap.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    say("\nwrote research/h1_deadhead_gap.json")


if __name__ == "__main__":
    main()
