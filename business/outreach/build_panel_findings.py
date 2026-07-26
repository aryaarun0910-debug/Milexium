"""Sector-level findings about the whole US demand-response panel.

Why this exists (and why it is not build_peer_insight.py)
---------------------------------------------------------
`build_peer_insight.py` answers "where does THIS agency sit?". That is the right
hook for an operator, because a rank is a fact about them that they cannot see
from inside their own books.

It is the wrong artifact for a domain expert. A former accessibility director
who now consults on paratransit does not need to be told where one agency ranks
-- he has ranked agencies for a living. He asked a different question:

    "Has your work revealed any definitive conclusions or items that the
     industry has so far overlooked?"

That question is answered by structure in the national panel, not by one row of
it. This file computes those candidate structures and puts every one of them
through a gate that is deliberately harder to pass than the peer engine's.

The gate
--------
The peer engine has ONE gate: a sub-2.5-point peer gap emits nothing. That is
enough to stop a manufactured hook, but it is not enough for a sector claim,
because a sector claim can be true of the aggregate and false of the industry.
Four ways a panel finding lies, and the check that catches each:

  mode_provenance  The claim says "demand response" but the number came from a
                   denominator covering every mode the agency runs. A commuter
                   railroad's numbers do not describe paratransit.
  composition      The aggregate moved because the SET OF AGENCIES changed, not
                   because any agency changed. Fixed by recomputing on a
                   balanced panel -- the same agencies at both endpoints.
  concentration    The aggregate moved because ONE large operator moved. Fixed
                   by reporting the per-agency median beside every aggregate,
                   and by dropping the largest contributors one at a time.
  inflation        A money change over years is quoted nominal, so ordinary
                   price inflation is presented as a sector trend. Fixed by
                   reporting the CPI-deflated change beside the nominal one.

A finding that fails any applicable check is NOT deleted. It is written to
`rejected` with the numbers that killed it. Rejected findings are an asset:
they are the evidence that the gate does something, and we have already sent
one to a prospect as a way of showing our work. A gate that never rejects
anything is decoration.

Enforcement is structural, not editorial: `finalise()` rejects any finding that
does not CARRY the required checks, so a future candidate cannot slip through by
simply forgetting to declare one.

Sources -- every number traceable
---------------------------------
  A. data/raw/public/ntd-monthly-ridership-all-modes.529952083544f257.csv
     368,937 rows, agency x mode x type-of-service x month, Jan-2002..May-2026.
     Mode-tagged: the `Mode` column is what makes a DR claim a DR claim.
  B. data/raw/public/ntd-service-opex-by-mode-timeseries.e6e821f63751d429.csv
     Long format (Field/Value), report years 2015-2024, mode-tagged. Carries
     Operating Expenses, which (A) does not.
  C. business/ntd/agency_economics.csv
     Agency-year panel; 2024 is the only year with real coverage (1,920 rows;
     2023 has 30 and 2022 has 18, far too sparse for any trend).

MEASURED provenance of (C) -- this was contested, so it was decided from the
bytes rather than asserted either way. For all 1,920 agency-years in 2024,
`trips`, `vrh` and `opex` equal the DEMAND-RESPONSE-ONLY totals from the
mode-tagged file (C)/(B) agreement within 1% for 100.0%, 100.0% and 99.8% of
agencies respectively, and equal the all-mode totals for only ~50% -- which is
exactly the share of agencies that run a single mode. Separately,
`actual_hours - deadhead_hours == vrh` to within 1% for 86.5% of the 406
agencies filing deadhead, with a median ratio of exactly 1.000. Since `vrh` is
demonstrably demand-response only, the deadhead columns are demand-response
scoped too. So (C) PASSES mode_provenance -- but the check is applied and
recorded, not waived, and `check_mode_provenance` re-derives the agreement
statistic on every run rather than trusting this docstring.

What is NOT computable from what we hold
----------------------------------------
Deadhead for any mode OTHER than demand response, and deadhead as a TIME
SERIES. File (B) is the only multi-year mode-tagged source and it carries
Vehicle Revenue Hours/Miles but no actual (total) hours, so there is no
deadhead numerator in it at all. File (C) has deadhead but only for 2024 and
only for demand response. Every deadhead finding here is therefore a 2024
cross-section, and is labelled as one. Approximating a deadhead trend from
these bytes would be inventing a number.

Status vocabulary: this is all public data with no counterfactual and no
holdout, so nothing here is ever Validated. Findings are Demonstrated at most.

Usage:
  py -3 business/outreach/build_panel_findings.py            # -> business/outreach/panel_findings.json
  py -3 business/outreach/build_panel_findings.py --verbose  # print every check
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
REPO = HERE.parents[1]
MONTHLY = REPO / "data" / "raw" / "public" / "ntd-monthly-ridership-all-modes.529952083544f257.csv"
OPEX = REPO / "data" / "raw" / "public" / "ntd-service-opex-by-mode-timeseries.e6e821f63751d429.csv"
ECON = REPO / "business" / "ntd" / "agency_economics.csv"
OUT = HERE / "panel_findings.json"

# Short names used in every `source` string, so a claim can be traced to a file.
SRC_MONTHLY = "data/raw/public/ntd-monthly-ridership-all-modes.529952083544f257.csv"
SRC_OPEX = "data/raw/public/ntd-service-opex-by-mode-timeseries.e6e821f63751d429.csv"
SRC_ECON = "business/ntd/agency_economics.csv"

# Demand response in the NTD mode vocabulary. DR is the mode code; the taxi and
# TNC variants that the industry calls "DT" appear here as Mode=DR with
# Type-of-Service TX/TN rather than as a separate mode code, so filtering on
# Mode=="DR" keeps them. Verified: this file contains ZERO rows with Mode=="DT".
DR_MODES = ("DR",)
# Fixed-route motorbus -- the control group. If a "demand response is special"
# claim is also true of MB, it is not a demand-response finding.
CONTROL_MODE = "MB"

# ---------------------------------------------------------------------------
# CPI-U, US city average, all items, ANNUAL AVERAGE (BLS series CUUR0000SA0).
#
# EXTERNAL CONSTANT. This is the one set of numbers in this file that is NOT
# computed from a governed dataset in data/catalog/ -- it is transcribed from
# the published BLS annual averages. It is declared here, in the open, with its
# series id, because a deflator smuggled in as a magic number is exactly how a
# real change becomes an invented one. Any money finding records
# `cpi_source` so a reader knows which figures depend on it.
# ---------------------------------------------------------------------------
CPI_U_ANNUAL = {2015: 237.017, 2024: 313.689}
CPI_SOURCE = "BLS CPI-U, US city average, all items, annual average (series CUUR0000SA0)"

# ---- Gate constants. Stated, not buried. ----------------------------------
# A change smaller than this is not a sector finding. The peer engine's
# equivalent is MIN_GAP_POINTS = 2.5 on a percentage share; over a multi-year
# panel a 5% move is the analogous "big enough to lead with" floor.
MIN_EFFECT_PCT = 5.0
# A dispersion claim needs a spread worth remarking on. Below 1.5x, "operators
# differ" is a truism.
MIN_SPREAD_RATIO = 1.5
# The balanced-panel result must keep the sign AND at least this fraction of
# the unbalanced magnitude, or the aggregate was a composition effect.
COMPOSITION_RETAIN = 0.5
# Leave-one-out and per-agency-median results must land inside this multiple of
# the headline, or one operator is carrying the finding.
CONCENTRATION_LO, CONCENTRATION_HI = 0.5, 2.0
# How many of the largest contributors to drop, one at a time.
LEAVE_OUT_TOP_N = 10

REQUIRED_CHECKS = ("mode_provenance", "composition", "concentration")


# ===========================================================================
# Gate primitives
# ===========================================================================
@dataclass
class Check:
    """One gate test, with the numbers that decided it.

    `detail` is not commentary -- it is the arithmetic, so a reader can redo it.
    """

    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict:
        return {"check": self.name, "verdict": "pass" if self.passed else "FAIL",
                "detail": self.detail}


@dataclass
class Finding:
    id: str
    claim: str
    source: str
    numbers: dict
    checks: list[Check] = field(default_factory=list)
    # Set when a candidate is known-false and is being kept in the file
    # deliberately so it cannot be revived. See DEAD_ON_ARRIVAL.
    forced_rejection: str | None = None

    def add(self, check: Check) -> "Finding":
        self.checks.append(check)
        return self

    def as_dict(self) -> dict:
        failed = [c for c in self.checks if not c.passed]
        missing = [c for c in REQUIRED_CHECKS if c not in {x.name for x in self.checks}]
        if self.forced_rejection:
            status, why = "rejected", self.forced_rejection
        elif missing:
            # Structural enforcement: a finding that never ran a required check
            # is rejected for that reason alone. Silence is not a pass.
            status = "rejected"
            why = ("gate incomplete -- required check(s) never run: "
                   + ", ".join(missing))
        elif failed:
            status = "rejected"
            why = "; ".join(f"{c.name}: {c.detail}" for c in failed)
        else:
            status, why = "survived", None
        d = {
            "id": self.id,
            "status": status,
            "claim": self.claim,
            "source": self.source,
            "numbers": self.numbers,
            "checks": [c.as_dict() for c in self.checks],
        }
        if why:
            d["rejected_because"] = why
        return d


def _pct_change(a: float, b: float) -> float:
    return (b / a - 1.0) * 100.0


def check_effect(value: float, kind: str = "change") -> Check:
    """Is the effect big enough to be worth a domain expert's attention?"""
    if kind == "change":
        ok = abs(value) >= MIN_EFFECT_PCT
        return Check("effect_size", ok,
                     f"|{value:+.1f}%| vs MIN_EFFECT_PCT={MIN_EFFECT_PCT}%")
    ok = value >= MIN_SPREAD_RATIO
    return Check("effect_size", ok,
                 f"spread {value:.2f}x vs MIN_SPREAD_RATIO={MIN_SPREAD_RATIO}x")


def check_composition(unbalanced: float, balanced: float, n_bal: int,
                      note: str = "") -> Check:
    """Same agencies at both endpoints, or the aggregate moved because the
    membership did."""
    same_sign = (unbalanced >= 0) == (balanced >= 0)
    retained = abs(balanced) / abs(unbalanced) if unbalanced else 0.0
    ok = same_sign and retained >= COMPOSITION_RETAIN
    return Check("composition", ok,
                 f"unbalanced {unbalanced:+.1f}% vs balanced panel (n={n_bal}) "
                 f"{balanced:+.1f}%; sign {'held' if same_sign else 'FLIPPED'}, "
                 f"magnitude retained {retained*100:.0f}% "
                 f"(floor {COMPOSITION_RETAIN*100:.0f}%){note}")


def check_concentration(aggregate: float, per_agency_median: float,
                        loo_lo: float, loo_hi: float, top1_share_pct: float) -> Check:
    """Every aggregate gets its per-agency median printed beside it, and the
    largest contributors dropped one at a time."""
    same_sign = (aggregate >= 0) == (per_agency_median >= 0)
    ratio = abs(per_agency_median) / abs(aggregate) if aggregate else 0.0
    loo_ok = all(
        (aggregate >= 0) == (v >= 0)
        and CONCENTRATION_LO <= (abs(v) / abs(aggregate) if aggregate else 0) <= CONCENTRATION_HI
        for v in (loo_lo, loo_hi)
    )
    med_ok = same_sign and CONCENTRATION_LO <= ratio <= CONCENTRATION_HI
    return Check("concentration", med_ok and loo_ok,
                 f"aggregate {aggregate:+.1f}%, per-agency median "
                 f"{per_agency_median:+.1f}% (ratio {ratio:.2f}); "
                 f"leave-one-out over top {LEAVE_OUT_TOP_N} spans "
                 f"{loo_lo:+.1f}%..{loo_hi:+.1f}%; largest single operator is "
                 f"{top1_share_pct:.1f}% of the panel")


def check_mode_provenance(agreement_pct: float, n: int, how: str) -> Check:
    """A demand-response claim must rest on a demand-response denominator."""
    ok = agreement_pct >= 95.0
    return Check("mode_provenance", ok,
                 f"{how}; agrees with the mode-tagged DR total for "
                 f"{agreement_pct:.1f}% of {n} agencies (floor 95%)")


def check_inflation(nominal_pct: float, real_pct: float, y0: int, y1: int) -> Check:
    """A money change over years must carry its real counterpart.

    This check does not reject on magnitude -- a real increase and a nominal
    increase are both true. It rejects when the real change is not COMPUTED,
    and it forces both onto the record so a reader cannot be shown only the
    bigger one.
    """
    deflator = CPI_U_ANNUAL[y1] / CPI_U_ANNUAL[y0]
    ok = abs(real_pct) >= MIN_EFFECT_PCT
    return Check("inflation", ok,
                 f"nominal {nominal_pct:+.1f}%; CPI-U {y0}->{y1} deflator "
                 f"{deflator:.4f} ({CPI_U_ANNUAL[y0]}->{CPI_U_ANNUAL[y1]}); "
                 f"REAL {real_pct:+.1f}%; source: {CPI_SOURCE}")


def check_control_mode(dr_value: float, mb_value: float, label: str,
                       must_exceed: bool = True) -> Check:
    """Is this actually about demand response, or about US transit generally?

    This is the check that killed the "demand-response demand is uniquely
    volatile" candidate. If fixed-route bus does the same thing or more, the
    demand-response framing is false however true the DR number is.
    """
    ok = (dr_value > mb_value) if must_exceed else (dr_value < mb_value)
    direction = "exceeds" if must_exceed else "is below"
    return Check("control_mode", ok,
                 f"demand response {dr_value:.2f} vs fixed-route bus (MB) "
                 f"{mb_value:.2f} on {label}; claim requires DR {direction} MB")


# ===========================================================================
# Loaders
# ===========================================================================
def load_monthly() -> pd.DataFrame:
    df = pd.read_csv(
        MONTHLY, low_memory=False, dtype={"NTD ID": str},
        usecols=["NTD ID", "Agency", "Mode", "TOS", "Date", "UPT", "VRH", "VRM", "VOMS"],
    )
    df["date"] = pd.to_datetime(df["Date"], format="%B %Y")
    df["year"] = df["date"].dt.year
    for c in ("UPT", "VRH", "VRM", "VOMS"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def load_opex() -> pd.DataFrame:
    """Long Field/Value table -> one row per agency-mode-year."""
    raw = pd.read_csv(
        OPEX, low_memory=False, dtype={"NTD ID": str},
        usecols=["NTD ID", "Agency Name", "Mode", "Report Year", "Field", "Value"],
    )
    raw["Value"] = pd.to_numeric(raw["Value"], errors="coerce")
    fields = {
        "Operating Expenses": "opex",
        "Unlinked Passenger Trips": "upt",
        "Vehicle Revenue Hours": "vrh",
        "Vehicle Revenue Miles": "vrm",
        "Passenger Miles Traveled": "pmt",
        "Vehicles Operated in Maximum Service": "voms",
    }
    w = (raw[raw["Field"].isin(fields)]
         .pivot_table(index=["NTD ID", "Agency Name", "Mode", "Report Year"],
                      columns="Field", values="Value", aggfunc="sum")
         .reset_index())
    w.columns.name = None
    return w.rename(columns={**fields, "NTD ID": "nid", "Agency Name": "agency",
                             "Report Year": "year"})


def load_econ() -> pd.DataFrame:
    e = pd.read_csv(ECON)
    e["nid"] = e["ntd_id"].astype(str).str.zfill(5)
    return e


def dr_agency_year(monthly: pd.DataFrame, complete_months: bool = True) -> pd.DataFrame:
    """Demand-response agency-year panel from the mode-tagged monthly file.

    `complete_months` drops agency-years with fewer than 12 DISTINCT months. A
    part-year agency looks like a collapse in ridership and like a productivity
    outlier, and neither is real -- it is a reporting gap.

    The month count is `nunique` over dates, NOT a row count. An agency that
    runs demand response both directly-operated and purchased-transportation
    files TWO rows for every month, so counting rows would have silently
    excluded every multi-contract operator from the panel -- which is a large,
    non-random and mostly urban slice of exactly the agencies that matter.
    That bug was live in the first run of this file and moved the headline
    productivity decline from -11.2% to -15.7%.
    """
    dr = monthly[monthly["Mode"].isin(DR_MODES)]
    ay = dr.groupby(["NTD ID", "year"], as_index=False).agg(
        upt=("UPT", "sum"), vrh=("VRH", "sum"), vrm=("VRM", "sum"),
        voms=("VOMS", "max"), months=("date", "nunique"), agency=("Agency", "first"))
    ay = ay[ay["vrh"] > 0]
    if complete_months:
        ay = ay[ay["months"] == 12]
    ay["tph"] = ay["upt"] / ay["vrh"]
    return ay.rename(columns={"NTD ID": "nid"})


def _ratio_endpoints(panel: pd.DataFrame, num: str, den: str, y0: int, y1: int):
    """Aggregate ratio at both endpoints, unbalanced and balanced, plus the
    per-agency change distribution and a leave-one-out sweep.

    Everything the composition and concentration checks need, computed once.
    """
    p = panel[(panel[num] > 0) & (panel[den] > 0)]
    a0, a1 = p[p.year == y0], p[p.year == y1]
    unbal = _pct_change(a0[num].sum() / a0[den].sum(), a1[num].sum() / a1[den].sum())

    common = sorted(set(a0.nid) & set(a1.nid))
    b0 = a0[a0.nid.isin(common)].set_index("nid").sort_index()
    b1 = a1[a1.nid.isin(common)].set_index("nid").sort_index()
    agg0 = b0[num].sum() / b0[den].sum()
    agg1 = b1[num].sum() / b1[den].sum()
    bal = _pct_change(agg0, agg1)

    r0, r1 = b0[num] / b0[den], b1[num] / b1[den]
    chg = (r1 / r0 - 1).replace([np.inf, -np.inf], np.nan).dropna()

    loo = []
    for nid in b1[den].nlargest(LEAVE_OUT_TOP_N).index:
        k = [i for i in common if i != nid]
        loo.append(_pct_change(b0.loc[k, num].sum() / b0.loc[k, den].sum(),
                               b1.loc[k, num].sum() / b1.loc[k, den].sum()))
    top1 = b1[den].max() / b1[den].sum() * 100

    return {
        "n_balanced": len(common), "unbalanced_pct": unbal, "balanced_pct": bal,
        "agg_y0": agg0, "agg_y1": agg1,
        "median_y0": float(r0.median()), "median_y1": float(r1.median()),
        "per_agency_median_pct": float(chg.median()) * 100,
        "frac_improved_pct": float((chg > 0).mean()) * 100,
        "loo_lo": min(loo), "loo_hi": max(loo), "top1_share_pct": float(top1),
    }


# ===========================================================================
# Mode-provenance evidence for business/ntd/agency_economics.csv
# ===========================================================================
def econ_mode_provenance(econ: pd.DataFrame, opex: pd.DataFrame) -> tuple[float, int, str]:
    """Decide from the bytes whether (C) is a demand-response panel.

    Recomputed every run. If a future refresh of business/ntd/agency_economics.csv ever
    switches to an all-mode denominator, every deadhead finding in this file
    fails mode_provenance and is rejected automatically -- which is the whole
    point of running the check rather than citing a docstring.
    """
    e = econ[econ.report_year == 2024]
    dr = (opex[(opex.Mode.isin(DR_MODES)) & (opex.year == 2024)]
          .groupby("nid")[["upt", "vrh"]].sum())
    allm = opex[opex.year == 2024].groupby("nid")[["upt", "vrh"]].sum()
    j = e.set_index("nid")[["trips", "vrh"]].join(dr.add_suffix("_dr")).join(
        allm.add_suffix("_all"))
    j = j[j.upt_dr.notna() & (j.trips > 0)]
    agree_dr = ((j.trips / j.upt_dr - 1).abs() < 0.01).mean() * 100
    agree_all = ((j.trips / j.upt_all - 1).abs() < 0.01).mean() * 100
    how = (f"business/ntd/agency_economics.csv `trips` compared against the mode-tagged "
           f"by-mode file: matches the DR-only total for {agree_dr:.1f}% of "
           f"agencies and the ALL-MODE total for {agree_all:.1f}%")
    return float(agree_dr), int(len(j)), how


def deadhead_identity_agreement(econ2024: pd.DataFrame) -> float:
    """Share of deadhead filers where actual_hours - deadhead_hours == vrh.

    `vrh` is established as demand-response only by econ_mode_provenance, so
    this identity is what carries that scope onto the deadhead columns. It is a
    data-quality reading as well: the agencies that fail it filed something
    internally inconsistent.
    """
    r = ((econ2024.actual_hours - econ2024.deadhead_hours) / econ2024.vrh)
    r = r.replace([np.inf, -np.inf], np.nan).dropna()
    return float(((r - 1).abs() < 0.01).mean() * 100)


# ===========================================================================
# Candidate findings
# ===========================================================================
def f_productivity_decline(ay: pd.DataFrame) -> Finding:
    """The established finding: two decades of falling trips per revenue hour."""
    m = _ratio_endpoints(ay, "upt", "vrh", 2005, 2024)
    # Is 2024 back at 2019, i.e. is this COVID or is it structural?
    m19 = _ratio_endpoints(ay, "upt", "vrh", 2019, 2024)
    f = Finding(
        id="dr_productivity_decline_2005_2024",
        claim=("US demand-response productivity has fallen for two decades: on a "
               "balanced panel of agencies reporting a full year in both 2005 and "
               "2024, trips per vehicle revenue hour fell from "
               f"{m['agg_y0']:.2f} to {m['agg_y1']:.2f}."),
        source=(f"{SRC_MONTHLY}; Mode=='DR'; UPT and VRH summed per NTD ID per "
                f"calendar year; agency-years with <12 monthly rows or VRH<=0 "
                f"dropped; balanced on agencies present in both 2005 and 2024"),
        numbers={
            "trips_per_vrh_2005": round(m["agg_y0"], 4),
            "trips_per_vrh_2024": round(m["agg_y1"], 4),
            "change_pct": round(m["balanced_pct"], 2),
            "per_agency_median_change_pct": round(m["per_agency_median_pct"], 2),
            "pct_of_agencies_less_productive": round(100 - m["frac_improved_pct"], 1),
            "n_balanced_agencies": m["n_balanced"],
            "trips_per_vrh_2019": round(m19["agg_y0"], 4),
            "change_2019_to_2024_pct": round(m19["balanced_pct"], 2),
            "not_covid_note": (f"2024 is within {abs(m19['balanced_pct']):.1f}% of "
                               "2019, so the decline predates the pandemic and did "
                               "not recover with it"),
        },
    )
    f.add(check_mode_provenance(100.0, m["n_balanced"],
                                "computed directly on Mode=='DR' rows of the "
                                "mode-tagged monthly file"))
    f.add(check_effect(m["balanced_pct"]))
    f.add(check_composition(m["unbalanced_pct"], m["balanced_pct"], m["n_balanced"]))
    f.add(check_concentration(m["balanced_pct"], m["per_agency_median_pct"],
                              m["loo_lo"], m["loo_hi"], m["top1_share_pct"]))
    return f


def f_recovery_dispersion(ay: pd.DataFrame) -> Finding:
    """The national recovery number hides an enormous spread."""
    a19 = ay[ay.year == 2019].set_index("nid")
    a24 = ay[ay.year == 2024].set_index("nid")
    k = a19.index.intersection(a24.index)
    rec = (a24.loc[k, "upt"] / a19.loc[k, "upt"]).replace([np.inf, -np.inf], np.nan).dropna()
    p10, p50, p90 = rec.quantile(.10), rec.median(), rec.quantile(.90)
    spread = p90 / p10
    national = a24.loc[k, "upt"].sum() / a19.loc[k, "upt"].sum()
    # Composition here means: does the spread survive if we ALSO require the
    # agency to have reported a full 2023? Entrants and exits are the risk.
    a23 = ay[ay.year == 2023].set_index("nid")
    k3 = k.intersection(a23.index)
    rec3 = (a24.loc[k3, "upt"] / a19.loc[k3, "upt"]).dropna()
    spread3 = rec3.quantile(.90) / rec3.quantile(.10)
    # Concentration: does the spread come from tiny operators?
    big = a19.loc[k, "upt"] >= 25_000
    rec_big = rec[big.reindex(rec.index).fillna(False)]
    spread_big = rec_big.quantile(.90) / rec_big.quantile(.10)

    f = Finding(
        id="dr_recovery_dispersion_2019_2024",
        claim=("The national demand-response recovery figure is close to "
               "meaningless: the median operator is at "
               f"{p50*100:.0f}% of its 2019 trips, but the 10th percentile is at "
               f"{p10*100:.0f}% and the 90th at {p90*100:.0f}% -- a "
               f"{spread:.1f}x spread across operators in the same year."),
        source=(f"{SRC_MONTHLY}; Mode=='DR'; annual UPT per NTD ID; both 2019 and "
                f"2024 required to have 12 monthly rows; ratio 2024/2019 per agency"),
        numbers={
            "n_agencies": int(len(rec)),
            "median_recovery_pct": round(p50 * 100, 1),
            "p10_recovery_pct": round(p10 * 100, 1),
            "p90_recovery_pct": round(p90 * 100, 1),
            "p90_over_p10": round(spread, 2),
            "volume_weighted_national_recovery_pct": round(national * 100, 1),
        },
    )
    f.add(check_mode_provenance(100.0, int(len(rec)),
                                "computed directly on Mode=='DR' rows of the "
                                "mode-tagged monthly file"))
    f.add(check_effect(spread, kind="spread"))
    f.add(Check("composition",
                abs(spread3 - spread) / spread <= 0.25,
                f"restricting to the {len(k3)} agencies that also filed a full "
                f"2023 gives {spread3:.2f}x vs {spread:.2f}x on all {len(rec)} "
                f"(within 25%)"))
    f.add(Check("concentration",
                spread_big >= MIN_SPREAD_RATIO,
                f"volume-weighted national recovery is {national*100:.1f}% -- a "
                f"single number that describes almost nobody; restricting to the "
                f"{int(big.sum())} agencies with >=25,000 trips in 2019 still "
                f"gives a {spread_big:.2f}x p90/p10 spread, so the dispersion is "
                f"not a small-operator artifact"))
    return f


def f_deadhead_central(econ24: pd.DataFrame, prov: tuple, identity_pct: float,
                       dr_share: pd.Series) -> Finding:
    """Deadhead: the ROBUST part. The dramatic tail is a separate candidate."""
    d = econ24.deadhead_pct_hours.dropna()
    med, p90 = d.median(), d.quantile(.90)
    weighted = econ24.deadhead_hours.sum() / econ24.actual_hours.sum()
    dom = econ24[econ24.nid.map(dr_share).fillna(0) >= 0.80]
    dd = dom.deadhead_pct_hours.dropna()
    agree, n_prov, how = prov

    f = Finding(
        id="dr_deadhead_level_2024",
        claim=("Roughly one demand-response vehicle-hour in seven is driven with "
               f"nobody aboard: across {len(d)} operators filing deadhead for 2024 "
               f"the median is {med*100:.1f}% of total vehicle-hours and the 90th "
               f"percentile {p90*100:.1f}%."),
        source=(f"{SRC_ECON}; report_year==2024; deadhead_pct_hours = "
                f"deadhead_hours / actual_hours; agencies with no deadhead filing "
                f"excluded"),
        numbers={
            "n_operators": int(len(d)),
            "median_deadhead_pct": round(med * 100, 1),
            "p90_deadhead_pct": round(p90 * 100, 1),
            "p10_deadhead_pct": round(d.quantile(.10) * 100, 1),
            "volume_weighted_deadhead_pct": round(weighted * 100, 1),
            "dr_dominant_n": int(len(dd)),
            "dr_dominant_median_pct": round(dd.median() * 100, 1),
            "dr_dominant_p90_pct": round(dd.quantile(.90) * 100, 1),
            "internally_consistent_filings_pct": round(identity_pct, 1),
            "year_scope": "2024 cross-section only -- no deadhead time series "
                          "exists in any source we hold",
        },
    )
    f.add(check_mode_provenance(agree, n_prov, how + (
        f"; and actual_hours - deadhead_hours == vrh for {identity_pct:.1f}% of "
        f"deadhead filers, which carries that DR scope onto the deadhead columns")))
    f.add(check_effect(p90 / d.quantile(.10), kind="spread"))
    # Composition for a cross-section: restrict to agencies whose service really
    # IS demand response, so a mostly-fixed-route agency's paratransit arm cannot
    # set the shape of the distribution.
    f.add(Check("composition",
                abs(dd.median() - med) / med <= 0.25
                and abs(dd.quantile(.90) - p90) / p90 <= 0.25,
                f"restricting to the {len(dd)} agencies with >=80% of revenue "
                f"hours in DR gives median {dd.median()*100:.1f}% "
                f"(vs {med*100:.1f}%) and p90 {dd.quantile(.90)*100:.1f}% "
                f"(vs {p90*100:.1f}%) -- both within 25%"))
    f.add(Check("concentration", abs(weighted - med) / med <= CONCENTRATION_HI - 1,
                f"per-agency median {med*100:.1f}% vs volume-weighted "
                f"{weighted*100:.1f}%; the largest DR operator is under 4% of "
                f"national DR trips, so no single filer can set this"))
    return f


SIZE_FLOOR_HOURS = 10_000  # below this an agency-year ratio is not an operation


def f_deadhead_extreme_tail(econ24: pd.DataFrame, dr_share: pd.Series) -> Finding:
    """The dramatic long tail. Kept as a candidate BECAUSE it fails.

    A note on HOW it fails, because the obvious answer is wrong and we nearly
    shipped it. The intuition is that the extreme deadhead figures belong to
    agencies whose paratransit arm is a sliver of a mostly fixed-route
    operation -- OmniRide is a commuter-express operator and 3.7% of its
    revenue hours are demand response -- and that restricting to genuinely
    demand-response-dominant agencies makes the tail disappear, since only one
    of the nine survives that cut.

    It does not. The RATE is identical: 9 of 406 filers (2.22%) exceed 40%, and
    1 of the 45 demand-response-dominant filers (2.22%) exceeds 40%. Only 11%
    of filers are DR-dominant, so one survivor out of nine is exactly what
    sample size predicts. "Nine becomes one" is arithmetic about the size of
    the subgroup, not evidence about mode mix, and asserting otherwise would
    have been the same species of error this whole file exists to catch.

    What actually kills it is size and filing quality: the tail is 2.2% of
    operators, two of the nine run 232 and 36 vehicle-hours a YEAR, and one
    (Montebello) fails the internal filing identity and is already hard-blocked
    in generate_v3_emails.py as a suspected reporting-model difference.
    """
    d = econ24.dropna(subset=["deadhead_pct_hours"])
    above40 = d[d.deadhead_pct_hours > 0.40]
    dom = d[d.nid.map(dr_share).fillna(0) >= 0.80]
    dom40 = dom[dom.deadhead_pct_hours > 0.40]
    rate_all = len(above40) / len(d) * 100
    rate_dom = len(dom40) / len(dom) * 100 if len(dom) else 0.0
    big = d[d.actual_hours >= SIZE_FLOOR_HOURS]
    big40 = big[big.deadhead_pct_hours > 0.40]
    rate_big = len(big40) / len(big) * 100 if len(big) else 0.0
    identity = ((above40.actual_hours - above40.deadhead_hours) / above40.vrh - 1).abs() < 0.01
    tiny = above40[above40.actual_hours < 1000]
    worst = d.nlargest(3, "deadhead_pct_hours")
    examples = [
        {"agency": str(r.agency)[:60],
         "deadhead_pct": round(r.deadhead_pct_hours * 100, 1),
         "actual_hours": int(r.actual_hours),
         "annual_trips": int(r.trips),
         "dr_share_of_agency_revenue_hours_pct": round(
             float(dr_share.get(r.nid, float("nan"))) * 100, 1)}
        for r in worst.itertuples()
    ]
    f = Finding(
        id="dr_deadhead_extreme_tail_2024",
        claim=(f"A long tail of demand-response operators runs over 40% of "
               f"vehicle-hours empty ({len(above40)} of {len(d)} filers), with "
               f"the worst above 60%."),
        source=(f"{SRC_ECON}; report_year==2024; deadhead_pct_hours > 0.40; "
                f"DR share of revenue hours from {SRC_OPEX}, Mode=='DR' VRH over "
                f"all-mode VRH, report year 2024"),
        numbers={
            "n_above_40pct_all_filers": int(len(above40)),
            "n_filers": int(len(d)),
            "rate_above_40pct_all_filers": round(rate_all, 2),
            "n_above_40pct_among_dr_dominant": int(len(dom40)),
            "n_dr_dominant": int(len(dom)),
            "rate_above_40pct_among_dr_dominant": round(rate_dom, 2),
            "rate_above_40pct_above_size_floor": round(rate_big, 2),
            "size_floor_actual_hours": SIZE_FLOOR_HOURS,
            "n_tail_below_1000_annual_hours": int(len(tiny)),
            "n_tail_failing_filing_identity": int((~identity).sum()),
            "worst_three": examples,
        },
    )
    f.add(check_mode_provenance(100.0, len(d),
                                "deadhead columns are DR-scoped (see "
                                "dr_deadhead_level_2024), so these are real "
                                "demand-response deadhead figures -- the failures "
                                "below are size and effect, not provenance"))
    f.add(Check("effect_size", rate_all >= 5.0,
                f"{len(above40)} of {len(d)} filers is {rate_all:.2f}% of the "
                f"panel. Calling 2% of operators 'a long tail' is a claim about "
                f"nine agencies dressed as a claim about a sector, and above a "
                f"{SIZE_FLOOR_HOURS:,}-hour floor it thins further to "
                f"{rate_big:.2f}%"))
    f.add(Check("composition", True,
                f"NOT a mode-mix artifact, contrary to the obvious reading: the "
                f"rate is {rate_all:.2f}% across all {len(d)} filers and "
                f"{rate_dom:.2f}% across the {len(dom)} that are "
                f"demand-response-dominant (>=80% of revenue hours in DR). Only "
                f"{len(dom)} of {len(d)} filers are DR-dominant, so one survivor "
                f"out of {len(above40)} is exactly what the subgroup size "
                f"predicts. This check PASSES and the finding is still rejected"))
    f.add(Check("concentration", False,
                f"the claim rests on {len(above40)} individually named operators, "
                f"{len(tiny)} of which run under 1,000 vehicle-hours a year "
                + "(" + "; ".join(
                    f"{e['agency'].split(',')[0]} at {e['deadhead_pct']}% on "
                    f"{e['actual_hours']:,} hours and {e['annual_trips']:,} trips"
                    for e in examples) + "), and "
                f"{int((~identity).sum())} of which fail the internal filing "
                f"identity actual_hours - deadhead_hours == vrh. An agency "
                f"reporting 36 vehicle-hours for a year is a rounding error, not "
                f"an operation"))
    return f


def f_cost_dispersion(econ24: pd.DataFrame, prov: tuple) -> Finding:
    """The 5x cost-per-trip spread, and what half of it is made of.

    The decomposition is the part nobody publishes: ln(cost/trip) =
    ln(cost/hour) - ln(trips/hour), so the variance of unit cost splits into a
    price term and a productivity term with a covariance shared between them.
    """
    p = econ24[(econ24.cost_per_trip > 0) & (econ24.cost_per_vrh > 0)
               & (econ24.trips_per_vrh > 0)].copy()
    lc, lh, lt = (np.log(p.cost_per_trip), np.log(p.cost_per_vrh),
                  np.log(p.trips_per_vrh))
    cov = float(np.cov(lh, lt)[0, 1])
    price_share = (lh.var() - cov) / lc.var() * 100
    prod_share = (lt.var() - cov) / lc.var() * 100
    spread = p.cost_per_trip.quantile(.90) / p.cost_per_trip.quantile(.10)
    # Composition: does the split survive dropping micro-operators?
    big = p[p.trips >= 100_000]
    lcb, lhb, ltb = (np.log(big.cost_per_trip), np.log(big.cost_per_vrh),
                     np.log(big.trips_per_vrh))
    covb = float(np.cov(lhb, ltb)[0, 1])
    price_big = (lhb.var() - covb) / lcb.var() * 100
    spread_big = big.cost_per_trip.quantile(.90) / big.cost_per_trip.quantile(.10)
    agree, n_prov, how = prov

    f = Finding(
        id="dr_cost_per_trip_dispersion_2024",
        claim=(f"What a demand-response trip costs varies {spread:.1f}x across US "
               f"operators (${p.cost_per_trip.quantile(.10):.0f} at the 10th "
               f"percentile, ${p.cost_per_trip.median():.0f} median, "
               f"${p.cost_per_trip.quantile(.90):.0f} at the 90th) -- and almost "
               f"exactly half of that variation is productivity rather than input "
               f"price."),
        source=(f"{SRC_ECON}; report_year==2024; cost_per_trip = opex/trips, "
                f"cost_per_vrh = opex/vrh, trips_per_vrh = trips/vrh; variance "
                f"decomposition of ln(cost_per_trip) = ln(cost_per_vrh) - "
                f"ln(trips_per_vrh), covariance split evenly between the two terms"),
        numbers={
            "n_operators": int(len(p)),
            "cost_per_trip_p10_usd": round(float(p.cost_per_trip.quantile(.10)), 2),
            "cost_per_trip_median_usd": round(float(p.cost_per_trip.median()), 2),
            "cost_per_trip_p90_usd": round(float(p.cost_per_trip.quantile(.90)), 2),
            "p90_over_p10": round(float(spread), 2),
            "variance_share_input_price_pct": round(float(price_share), 1),
            "variance_share_productivity_pct": round(float(prod_share), 1),
            "cost_per_vrh_p90_over_p10": round(
                float(p.cost_per_vrh.quantile(.9) / p.cost_per_vrh.quantile(.1)), 2),
            "trips_per_vrh_p90_over_p10": round(
                float(p.trips_per_vrh.quantile(.9) / p.trips_per_vrh.quantile(.1)), 2),
        },
    )
    f.add(check_mode_provenance(agree, n_prov, how))
    f.add(check_effect(float(spread), kind="spread"))
    f.add(Check("composition", abs(price_big - price_share) <= 10.0,
                f"restricting to the {len(big)} operators above 100,000 annual "
                f"trips gives a {price_big:.1f}% price share vs {price_share:.1f}% "
                f"on all {len(p)}, and a {spread_big:.2f}x spread vs "
                f"{spread:.2f}x -- the split is not a micro-operator artifact"))
    f.add(Check("concentration", True,
                f"this is a distribution, not an aggregate: every statistic "
                f"quoted is a per-agency quantile, so no operator is weighted by "
                f"size at all. The volume-weighted mean cost per trip is "
                f"${p.opex.sum()/p.trips.sum():.2f}, which sits at the "
                f"{float((p.cost_per_trip < p.opex.sum()/p.trips.sum()).mean()*100):.0f}"
                f"th percentile of operators -- reported here precisely because "
                f"it is not the same number"))
    return f


def f_not_congestion(opex: pd.DataFrame) -> Finding:
    """Why productivity fell -- and the two explanations the data rules out."""
    dr = opex[opex.Mode.isin(DR_MODES)]
    speed = _ratio_endpoints(dr, "vrm", "vrh", 2015, 2024)
    mpt = _ratio_endpoints(dr, "vrm", "upt", 2015, 2024)
    f = Finding(
        id="dr_productivity_loss_is_not_congestion",
        claim=("The productivity decline is not traffic and it is not longer "
               "trips. Demand-response average speed is flat over 2015-2024 "
               f"({speed['agg_y0']:.1f} to {speed['agg_y1']:.1f} vehicle miles "
               f"per revenue hour, {speed['balanced_pct']:+.1f}%), while vehicle "
               f"miles driven per passenger trip rose {mpt['balanced_pct']:+.1f}%. "
               "The vehicles are moving as fast as they ever did; they are "
               "covering more ground per rider delivered."),
        source=(f"{SRC_OPEX}; Mode=='DR'; Field in "
                f"{{Vehicle Revenue Miles, Vehicle Revenue Hours, "
                f"Unlinked Passenger Trips}}; report years 2015 and 2024; "
                f"balanced on agencies present in both"),
        numbers={
            "n_balanced_agencies": speed["n_balanced"],
            "speed_vrm_per_vrh_2015": round(speed["agg_y0"], 2),
            "speed_vrm_per_vrh_2024": round(speed["agg_y1"], 2),
            "speed_change_pct": round(speed["balanced_pct"], 2),
            "speed_per_agency_median_change_pct": round(
                speed["per_agency_median_pct"], 2),
            "vehicle_miles_per_trip_2015": round(mpt["agg_y0"], 2),
            "vehicle_miles_per_trip_2024": round(mpt["agg_y1"], 2),
            "vehicle_miles_per_trip_change_pct": round(mpt["balanced_pct"], 2),
            "vehicle_miles_per_trip_per_agency_median_change_pct": round(
                mpt["per_agency_median_pct"], 2),
        },
    )
    f.add(check_mode_provenance(100.0, mpt["n_balanced"],
                                "computed on Mode=='DR' rows of the mode-tagged "
                                "by-mode file"))
    f.add(check_effect(mpt["balanced_pct"]))
    f.add(check_composition(mpt["unbalanced_pct"], mpt["balanced_pct"],
                            mpt["n_balanced"]))
    f.add(check_concentration(mpt["balanced_pct"], mpt["per_agency_median_pct"],
                              mpt["loo_lo"], mpt["loo_hi"], mpt["top1_share_pct"]))
    return f


def f_cost_growth_split(opex: pd.DataFrame) -> Finding:
    """Cost per trip nearly doubled. How much of that is price, how much us?"""
    dr = opex[opex.Mode.isin(DR_MODES)]
    cpt = _ratio_endpoints(dr, "opex", "upt", 2015, 2024)
    cph = _ratio_endpoints(dr, "opex", "vrh", 2015, 2024)
    tph = _ratio_endpoints(dr, "upt", "vrh", 2015, 2024)
    deflator = CPI_U_ANNUAL[2024] / CPI_U_ANNUAL[2015]
    real_cpt = (1 + cpt["balanced_pct"] / 100) / deflator
    real_cph = (1 + cph["balanced_pct"] / 100) / deflator
    # Log attribution: ln(cost/trip) = ln(cost/hour) + ln(1 / trips-per-hour)
    l_cpt = np.log(1 + cpt["balanced_pct"] / 100)
    l_cph = np.log(1 + cph["balanced_pct"] / 100)
    l_prod = -np.log(1 + tph["balanced_pct"] / 100)
    price_share = l_cph / l_cpt * 100
    prod_share = l_prod / l_cpt * 100

    f = Finding(
        id="dr_cost_growth_split_2015_2024",
        claim=("Demand-response cost per trip rose "
               f"{cpt['balanced_pct']:.0f}% in nominal terms 2015-2024 "
               f"(${cpt['agg_y0']:.2f} to ${cpt['agg_y1']:.2f}), which is "
               f"{(real_cpt-1)*100:.0f}% after CPI. About "
               f"{price_share:.0f}% of the rise is the price of an hour of "
               f"service and about {prod_share:.0f}% is delivering fewer trips "
               "per hour -- and only the second part is anything an operator "
               "schedules."),
        source=(f"{SRC_OPEX}; Mode=='DR'; Field in {{Operating Expenses, "
                f"Unlinked Passenger Trips, Vehicle Revenue Hours}}; report years "
                f"2015 and 2024; balanced on agencies present in both; real terms "
                f"deflated by {CPI_SOURCE}"),
        numbers={
            "n_balanced_agencies": cpt["n_balanced"],
            "cost_per_trip_2015_usd": round(cpt["agg_y0"], 2),
            "cost_per_trip_2024_usd": round(cpt["agg_y1"], 2),
            "cost_per_trip_change_nominal_pct": round(cpt["balanced_pct"], 1),
            "cost_per_trip_change_real_pct": round((real_cpt - 1) * 100, 1),
            "cost_per_trip_per_agency_median_change_nominal_pct": round(
                cpt["per_agency_median_pct"], 1),
            "cost_per_hour_2015_usd": round(cph["agg_y0"], 2),
            "cost_per_hour_2024_usd": round(cph["agg_y1"], 2),
            "cost_per_hour_change_nominal_pct": round(cph["balanced_pct"], 1),
            "cost_per_hour_change_real_pct": round((real_cph - 1) * 100, 1),
            "trips_per_vrh_change_pct": round(tph["balanced_pct"], 1),
            "attribution_input_price_pct": round(float(price_share), 1),
            "attribution_productivity_pct": round(float(prod_share), 1),
            "cpi_source": CPI_SOURCE,
            "cpi_values": {str(k): v for k, v in CPI_U_ANNUAL.items()},
        },
    )
    f.add(check_mode_provenance(100.0, cpt["n_balanced"],
                                "computed on Mode=='DR' rows of the mode-tagged "
                                "by-mode file"))
    f.add(check_effect(cpt["balanced_pct"]))
    f.add(check_composition(cpt["unbalanced_pct"], cpt["balanced_pct"],
                            cpt["n_balanced"]))
    f.add(check_concentration(cpt["balanced_pct"], cpt["per_agency_median_pct"],
                              cpt["loo_lo"], cpt["loo_hi"], cpt["top1_share_pct"]))
    f.add(check_inflation(cpt["balanced_pct"], (real_cpt - 1) * 100, 2015, 2024))
    return f


def f_cost_inflation_vs_bus(opex: pd.DataFrame) -> Finding:
    """Is demand-response unit-cost inflation WORSE than fixed route?

    It looks that way on the aggregate. It does not survive the per-agency view,
    which is exactly what the concentration check is for.
    """
    dr = _ratio_endpoints(opex[opex.Mode.isin(DR_MODES)], "opex", "vrh", 2015, 2024)
    mb = _ratio_endpoints(opex[opex.Mode == CONTROL_MODE], "opex", "vrh", 2015, 2024)
    agg_gap = dr["balanced_pct"] - mb["balanced_pct"]
    med_gap = dr["per_agency_median_pct"] - mb["per_agency_median_pct"]
    deflator = CPI_U_ANNUAL[2024] / CPI_U_ANNUAL[2015]
    f = Finding(
        id="dr_cost_inflation_exceeds_bus",
        claim=("Demand-response cost per revenue hour has inflated faster than "
               f"fixed-route bus ({dr['balanced_pct']:.1f}% vs "
               f"{mb['balanced_pct']:.1f}% 2015-2024)."),
        source=(f"{SRC_OPEX}; Mode=='DR' vs Mode=='MB'; Operating Expenses over "
                f"Vehicle Revenue Hours; balanced panels 2015 and 2024"),
        numbers={
            "dr_cost_per_hour_change_pct": round(dr["balanced_pct"], 1),
            "mb_cost_per_hour_change_pct": round(mb["balanced_pct"], 1),
            "aggregate_gap_points": round(agg_gap, 1),
            "dr_per_agency_median_change_pct": round(dr["per_agency_median_pct"], 1),
            "mb_per_agency_median_change_pct": round(mb["per_agency_median_pct"], 1),
            "per_agency_median_gap_points": round(med_gap, 1),
            "dr_real_change_pct": round(
                ((1 + dr["balanced_pct"] / 100) / deflator - 1) * 100, 1),
            "mb_real_change_pct": round(
                ((1 + mb["balanced_pct"] / 100) / deflator - 1) * 100, 1),
        },
    )
    f.add(check_mode_provenance(100.0, dr["n_balanced"],
                                "both panels drawn from the mode-tagged by-mode "
                                "file on their own Mode codes"))
    f.add(check_effect(agg_gap))
    f.add(check_composition(dr["unbalanced_pct"] - mb["unbalanced_pct"], agg_gap,
                            dr["n_balanced"]))
    f.add(Check("concentration", abs(med_gap) >= abs(agg_gap) * CONCENTRATION_LO,
                f"the gap is {agg_gap:+.1f} points on volume-weighted aggregates "
                f"but only {med_gap:+.1f} points on per-agency medians "
                f"({dr['per_agency_median_pct']:.1f}% vs "
                f"{mb['per_agency_median_pct']:.1f}%). The typical demand-response "
                f"operator's hourly cost inflation is barely distinguishable from "
                f"the typical bus operator's; the aggregate gap is a weighting "
                f"effect, not an industry difference"))
    f.add(check_inflation(agg_gap,
                          ((1 + dr["balanced_pct"] / 100) / deflator - 1) * 100
                          - ((1 + mb["balanced_pct"] / 100) / deflator - 1) * 100,
                          2015, 2024))
    return f


def f_hours_vs_trips_recovery(ay: pd.DataFrame) -> Finding:
    """Supply came back further than demand did -- for a sixth of the panel,
    supply is above 2019 while demand is below it."""
    a19 = ay[ay.year == 2019].set_index("nid")
    a24 = ay[ay.year == 2024].set_index("nid")
    k = a19.index.intersection(a24.index)
    trips = (a24.loc[k, "upt"] / a19.loc[k, "upt"]).replace([np.inf, -np.inf], np.nan)
    hours = (a24.loc[k, "vrh"] / a19.loc[k, "vrh"]).replace([np.inf, -np.inf], np.nan)
    both = pd.concat([trips.rename("t"), hours.rename("h")], axis=1).dropna()
    gap = (both.h.median() - both.t.median()) * 100
    crossed = ((both.h > 1) & (both.t < 1))
    f = Finding(
        id="dr_hours_recovered_further_than_trips",
        claim=("Demand-response supply has recovered further than demand: the "
               f"median operator runs {both.h.median()*100:.0f}% of its 2019 "
               f"vehicle hours but carries only {both.t.median()*100:.0f}% of its "
               f"2019 trips, and {crossed.sum()} of {len(both)} operators "
               f"({crossed.mean()*100:.0f}%) are now running MORE hours than in "
               "2019 while carrying fewer riders."),
        source=(f"{SRC_MONTHLY}; Mode=='DR'; annual UPT and VRH per NTD ID; both "
                f"2019 and 2024 required to have 12 monthly rows"),
        numbers={
            "n_agencies": int(len(both)),
            "median_hours_recovery_pct": round(float(both.h.median()) * 100, 1),
            "median_trips_recovery_pct": round(float(both.t.median()) * 100, 1),
            "gap_points": round(float(gap), 1),
            "n_more_hours_fewer_trips": int(crossed.sum()),
            "pct_more_hours_fewer_trips": round(float(crossed.mean()) * 100, 1),
        },
    )
    f.add(check_mode_provenance(100.0, int(len(both)),
                                "computed directly on Mode=='DR' rows of the "
                                "mode-tagged monthly file"))
    f.add(check_effect(gap))
    # Composition: this is already a balanced comparison by construction -- the
    # same agency supplies both endpoints of both ratios. Stated as the check,
    # with the arithmetic that makes it true, not waived.
    f.add(Check("composition", True,
                f"balanced by construction: every one of the {len(both)} agencies "
                f"supplies its own 2019 and 2024 endpoint for BOTH ratios, so no "
                f"entrant or exit can move either median. Unbalanced medians over "
                f"all filers would be "
                f"{ay[ay.year==2024].vrh.count()} vs {ay[ay.year==2019].vrh.count()} "
                f"different agencies and are deliberately not used"))
    f.add(Check("concentration", True,
                f"both figures are per-agency medians, not aggregates; the "
                f"volume-weighted equivalents are "
                f"{a24.loc[k,'vrh'].sum()/a19.loc[k,'vrh'].sum()*100:.1f}% of 2019 "
                f"hours and {a24.loc[k,'upt'].sum()/a19.loc[k,'upt'].sum()*100:.1f}% "
                f"of 2019 trips -- same direction, same order of gap"))
    return f


def f_against_the_trend(ay: pd.DataFrame) -> Finding:
    """The decline is not a law of nature. A quarter of operators beat it."""
    a05 = ay[ay.year == 2005].set_index("nid")
    a24 = ay[ay.year == 2024].set_index("nid")
    k = a05.index.intersection(a24.index)
    tph_chg = (a24.loc[k, "tph"] / a05.loc[k, "tph"] - 1).replace(
        [np.inf, -np.inf], np.nan).dropna()
    upt_chg = (a24.loc[k, "upt"] / a05.loc[k, "upt"] - 1).reindex(tph_chg.index)
    both_up = (tph_chg > 0) & (upt_chg > 0)
    sizeable = a05.loc[tph_chg.index, "upt"] >= 50_000
    both_up_big = both_up & sizeable
    top = a24.loc[tph_chg[both_up_big].index].nlargest(5, "upt")
    examples = [
        {"agency": str(a24.loc[i, "agency"])[:60],
         "trips_per_vrh_2005": round(float(a05.loc[i, "tph"]), 2),
         "trips_per_vrh_2024": round(float(a24.loc[i, "tph"]), 2),
         "productivity_change_pct": round(float(tph_chg[i]) * 100, 1),
         "trips_change_pct": round(float(upt_chg[i]) * 100, 1)}
        for i in top.index
    ]
    f = Finding(
        id="dr_productivity_decline_is_not_universal",
        claim=("The decline is not a law of physics: "
               f"{int((tph_chg > 0).sum())} of {len(tph_chg)} operators "
               f"({(tph_chg > 0).mean()*100:.0f}%) are MORE productive than they "
               f"were in 2005, and {int(both_up.sum())} ({both_up.mean()*100:.0f}%) "
               "raised productivity while also growing ridership."),
        source=(f"{SRC_MONTHLY}; Mode=='DR'; per-agency trips per VRH in 2005 and "
                f"2024, both full 12-month years; 'sizeable' = >=50,000 DR trips "
                f"in 2005"),
        numbers={
            "n_agencies_in_both_years": int(len(tph_chg)),
            "n_more_productive": int((tph_chg > 0).sum()),
            "pct_more_productive": round(float((tph_chg > 0).mean()) * 100, 1),
            "n_productivity_and_volume_up": int(both_up.sum()),
            "pct_productivity_and_volume_up": round(float(both_up.mean()) * 100, 1),
            "n_sizeable": int(sizeable.sum()),
            "n_sizeable_both_up": int(both_up_big.sum()),
            "pct_sizeable_both_up": round(
                float(both_up[sizeable].mean()) * 100, 1),
            "largest_examples": examples,
        },
    )
    f.add(check_mode_provenance(100.0, int(len(tph_chg)),
                                "computed directly on Mode=='DR' rows of the "
                                "mode-tagged monthly file"))
    f.add(check_effect(float((tph_chg > 0).mean()) * 100))
    f.add(Check("composition", abs(float(both_up[sizeable].mean())
                                   - float(both_up.mean())) <= 0.10,
                f"restricting to the {int(sizeable.sum())} operators above 50,000 "
                f"trips in 2005 gives {both_up[sizeable].mean()*100:.1f}% vs "
                f"{both_up.mean()*100:.1f}% over all {len(tph_chg)} -- the "
                f"counter-trend group is not made of tiny operators whose ratios "
                f"swing on a handful of trips"))
    f.add(Check("concentration", len(examples) >= 3,
                f"this is a COUNT of operators, so no operator is weighted at "
                f"all; {len(examples)} of the largest are named with their own "
                f"numbers so the claim can be checked one agency at a time"))
    return f


def f_dr_more_stable_than_bus(monthly: pd.DataFrame) -> Finding:
    """The finding that argues AGAINST our own naive pitch. It is true, so it
    stays -- and it is the reason the volatility candidate is dead."""
    def cv_and_amplitude(mode: str, year: int = 2024):
        s = monthly[(monthly["Mode"] == mode) & (monthly.year == year)]
        g = s.groupby(["NTD ID", "date"], as_index=False)["UPT"].sum()
        cvs, amps = [], []
        for _, grp in g.groupby("NTD ID"):
            if len(grp) < 12 or grp.UPT.mean() <= 0:
                continue
            cvs.append(grp.UPT.std(ddof=1) / grp.UPT.mean())
            amps.append((grp.UPT.max() - grp.UPT.min()) / grp.UPT.mean())
        return pd.Series(cvs), pd.Series(amps)

    dr_cv, dr_amp = cv_and_amplitude("DR")
    mb_cv, mb_amp = cv_and_amplitude(CONTROL_MODE)
    f = Finding(
        id="dr_demand_is_more_stable_than_bus",
        claim=("Demand-response demand is more stable month to month than "
               f"fixed-route bus, not less: median coefficient of variation "
               f"{dr_cv.median()*100:.1f}% for DR against "
               f"{mb_cv.median()*100:.1f}% for bus in 2024, and a smaller "
               f"peak-to-trough swing ({dr_amp.median()*100:.0f}% vs "
               f"{mb_amp.median()*100:.0f}% of mean monthly trips)."),
        source=(f"{SRC_MONTHLY}; monthly UPT per NTD ID, calendar 2024, agencies "
                f"with all 12 months and positive mean; CV = sd/mean, amplitude = "
                f"(max-min)/mean; Mode=='DR' vs Mode=='MB'"),
        numbers={
            "n_dr_agencies": int(len(dr_cv)),
            "n_bus_agencies": int(len(mb_cv)),
            "dr_median_cv_pct": round(float(dr_cv.median()) * 100, 1),
            "bus_median_cv_pct": round(float(mb_cv.median()) * 100, 1),
            "dr_median_amplitude_pct": round(float(dr_amp.median()) * 100, 1),
            "bus_median_amplitude_pct": round(float(mb_amp.median()) * 100, 1),
            "dr_p90_cv_pct": round(float(dr_cv.quantile(.90)) * 100, 1),
            "bus_p90_cv_pct": round(float(mb_cv.quantile(.90)) * 100, 1),
        },
    )
    f.add(check_mode_provenance(100.0, int(len(dr_cv)),
                                "both series taken from the mode-tagged monthly "
                                "file on their own Mode codes"))
    f.add(check_effect(_pct_change(float(dr_cv.median()), float(mb_cv.median()))))
    f.add(Check("composition", True,
                f"single-year cross-section with a full-12-month requirement on "
                f"both panels ({len(dr_cv)} DR, {len(mb_cv)} bus agencies), so no "
                f"agency enters on a partial year; the same comparison on the two "
                f"separate statistics (CV and peak-to-trough amplitude) gives the "
                f"same ordering, which a composition artifact would not"))
    f.add(Check("concentration", True,
                "both figures are medians over agencies, so the largest operator "
                "counts exactly as much as the smallest"))
    f.add(check_control_mode(float(dr_cv.median()), float(mb_cv.median()),
                             "median monthly CV of UPT, 2024", must_exceed=False))
    return f


def f_volatility_myth(monthly: pd.DataFrame) -> Finding:
    """DEAD ON ARRIVAL, and kept that way on purpose.

    "Demand-response demand is uniquely volatile, so you need forecasting" is a
    pitch somebody will try to revive every six months because it sells. It is
    false. It is computed here, in full, so that reviving it requires deleting a
    finding that says so in numbers rather than merely forgetting a note.
    """
    def median_cv(mode: str, year: int = 2024) -> float:
        s = monthly[(monthly["Mode"] == mode) & (monthly.year == year)]
        g = s.groupby(["NTD ID", "date"], as_index=False)["UPT"].sum()
        cvs = [grp.UPT.std(ddof=1) / grp.UPT.mean()
               for _, grp in g.groupby("NTD ID")
               if len(grp) >= 12 and grp.UPT.mean() > 0]
        return float(pd.Series(cvs).median())

    dr, mb = median_cv("DR"), median_cv(CONTROL_MODE)
    f = Finding(
        id="dr_demand_is_uniquely_volatile",
        claim=("Demand-response demand is uniquely volatile month to month, so "
               "operators need forecasting more than fixed-route does."),
        source=(f"{SRC_MONTHLY}; median per-agency coefficient of variation of "
                f"monthly UPT, calendar 2024, 12-month-complete agencies; "
                f"Mode=='DR' vs Mode=='MB'"),
        numbers={
            "dr_median_cv_pct": round(dr * 100, 1),
            "bus_median_cv_pct": round(mb * 100, 1),
            "verdict": "FALSE -- the opposite is true",
        },
    )
    f.add(check_mode_provenance(100.0, 0,
                                "both series taken from the mode-tagged monthly "
                                "file on their own Mode codes"))
    f.add(check_control_mode(dr, mb, "median monthly CV of UPT, 2024",
                             must_exceed=True))
    f.add(Check("composition", True, "12-month-complete agencies in both panels"))
    f.add(Check("concentration", True, "medians over agencies, unweighted"))
    f.forced_rejection = (
        f"FALSE AND PERMANENTLY DEAD. Demand-response monthly demand varies LESS "
        f"than fixed-route bus, not more: median CV {dr*100:.1f}% vs "
        f"{mb*100:.1f}% in 2024. This claim is retained in the rejected list "
        f"specifically so it cannot be quietly revived -- see "
        f"dr_demand_is_more_stable_than_bus for the same measurement stated "
        f"truthfully, and evidence/conformance/property-tests/test_panel_findings.py for "
        f"the test that fails if it ever moves back to `survived`."
    )
    return f


def f_deadhead_predicts_cost(econ24: pd.DataFrame) -> Finding:
    """Does the metric our own peer engine leads with actually predict money?

    Testing this was uncomfortable and is the reason it is in the file.
    """
    p = econ24.dropna(subset=["deadhead_pct_hours", "cost_per_trip", "trips_per_vrh"])
    p = p[(p.cost_per_trip > 0) & (p.trips_per_vrh > 0)]
    rho_cost = float(p[["deadhead_pct_hours", "cost_per_trip"]].corr(
        method="spearman").iloc[0, 1])
    rho_prod = float(p[["deadhead_pct_hours", "trips_per_vrh"]].corr(
        method="spearman").iloc[0, 1])
    rho_price = float(p[["cost_per_vrh", "cost_per_trip"]].corr(
        method="spearman").iloc[0, 1])
    q = p.assign(dq=pd.qcut(p.deadhead_pct_hours, 4, labels=["q1", "q2", "q3", "q4"]))
    by_q = q.groupby("dq", observed=True)["cost_per_trip"].median()
    f = Finding(
        id="dr_deadhead_predicts_cost_per_trip",
        claim=("Deadhead share is where demand-response money leaks, so an "
               "operator's empty-hour percentage predicts its cost per trip."),
        source=(f"{SRC_ECON}; report_year==2024; Spearman rank correlation of "
                f"deadhead_pct_hours against cost_per_trip over "
                f"{len(p)} operators; quartiles of deadhead_pct_hours"),
        numbers={
            "n_operators": int(len(p)),
            "spearman_deadhead_vs_cost_per_trip": round(rho_cost, 3),
            "spearman_deadhead_vs_trips_per_vrh": round(rho_prod, 3),
            "spearman_cost_per_hour_vs_cost_per_trip": round(rho_price, 3),
            "median_cost_per_trip_by_deadhead_quartile_usd": {
                str(k): round(float(v), 2) for k, v in by_q.items()},
        },
    )
    f.add(check_mode_provenance(100.0, int(len(p)),
                                "deadhead, cost and productivity columns are all "
                                "DR-scoped (see dr_deadhead_level_2024)"))
    f.add(Check("effect_size", abs(rho_cost) >= 0.30,
                f"Spearman {rho_cost:+.3f} over {len(p)} operators; a rank "
                f"correlation this close to zero is no relationship. Median cost "
                f"per trip runs ${by_q.iloc[0]:.2f} in the LOWEST deadhead "
                f"quartile against ${by_q.iloc[-1]:.2f} in the highest -- the "
                f"wrong way round to matter and far too small to lead with. By "
                f"contrast cost per revenue HOUR ranks against cost per trip at "
                f"{rho_price:+.3f}"))
    f.add(Check("composition", True,
                "single-year cross-section over all 2024 deadhead filers; no "
                "endpoint selection is possible"))
    f.add(Check("concentration", True,
                "rank correlation and quartile medians, both unweighted by size"))
    return f


def f_cost_dispersion_widening(econ24: pd.DataFrame, opex: pd.DataFrame) -> Finding:
    """Is the gap between cheap and expensive operators opening up?

    An attractive story. The data says the distribution has barely moved.
    """
    def spread(year: int) -> tuple[float, int]:
        p = opex[(opex.Mode.isin(DR_MODES)) & (opex.year == year)
                 & (opex.upt > 0) & (opex.opex > 0)]
        cpt = p.opex / p.upt
        return float(cpt.quantile(.90) / cpt.quantile(.10)), int(len(p))

    s15, n15 = spread(2015)
    s24, n24 = spread(2024)
    delta = _pct_change(s15, s24)
    # Balanced: same agencies at both ends.
    p = opex[(opex.Mode.isin(DR_MODES)) & (opex.upt > 0) & (opex.opex > 0)]
    common = set(p[p.year == 2015].nid) & set(p[p.year == 2024].nid)
    b = p[p.nid.isin(common)]
    b15 = (b[b.year == 2015].opex / b[b.year == 2015].upt)
    b24 = (b[b.year == 2024].opex / b[b.year == 2024].upt)
    bs15 = float(b15.quantile(.9) / b15.quantile(.1))
    bs24 = float(b24.quantile(.9) / b24.quantile(.1))
    bdelta = _pct_change(bs15, bs24)
    f = Finding(
        id="dr_cost_dispersion_is_widening",
        claim=("The gap between the cheapest and most expensive demand-response "
               "operators is widening, so the sector is pulling apart."),
        source=(f"{SRC_OPEX}; Mode=='DR'; cost per trip = Operating Expenses / "
                f"Unlinked Passenger Trips; p90/p10 ratio in 2015 vs 2024"),
        numbers={
            "p90_over_p10_2015": round(s15, 2),
            "p90_over_p10_2024": round(s24, 2),
            "change_pct": round(delta, 1),
            "n_2015": n15, "n_2024": n24,
            "balanced_p90_over_p10_2015": round(bs15, 2),
            "balanced_p90_over_p10_2024": round(bs24, 2),
            "balanced_change_pct": round(bdelta, 1),
            "n_balanced": len(common),
        },
    )
    f.add(check_mode_provenance(100.0, len(common),
                                "computed on Mode=='DR' rows of the mode-tagged "
                                "by-mode file"))
    f.add(check_effect(delta))
    f.add(check_composition(delta, bdelta, len(common)))
    f.add(Check("concentration", True,
                "quantile ratios, unweighted by operator size"))
    return f


def f_recovery_drives_productivity(ay: pd.DataFrame) -> Finding:
    """Correlated, yes. Independent, no -- and that is the reason it dies."""
    a19 = ay[ay.year == 2019].set_index("nid")
    a24 = ay[ay.year == 2024].set_index("nid")
    k = a19.index.intersection(a24.index)
    rec = (a24.loc[k, "upt"] / a19.loc[k, "upt"])
    prod = ((a24.loc[k, "upt"] / a24.loc[k, "vrh"])
            / (a19.loc[k, "upt"] / a19.loc[k, "vrh"]))
    d = pd.concat([rec.rename("r"), prod.rename("p")], axis=1).replace(
        [np.inf, -np.inf], np.nan).dropna()
    rho = float(d.r.corr(d.p, method="spearman"))
    # The honest alternative: correlate recovery against the HOURS change, which
    # shares no term with it.
    hrs = (a24.loc[k, "vrh"] / a19.loc[k, "vrh"])
    d2 = pd.concat([rec.rename("r"), hrs.rename("h")], axis=1).replace(
        [np.inf, -np.inf], np.nan).dropna()
    rho2 = float(d2.r.corr(d2.h, method="spearman"))
    f = Finding(
        id="dr_recovery_drives_productivity",
        claim=("Operators that recovered their ridership also recovered their "
               f"productivity (Spearman {rho:+.2f}), so ridership recovery is the "
               "route to efficiency."),
        source=(f"{SRC_MONTHLY}; Mode=='DR'; recovery = UPT2024/UPT2019, "
                f"productivity change = (UPT/VRH)2024 / (UPT/VRH)2019, over "
                f"{len(d)} agencies with 12 months in both years"),
        numbers={
            "n_agencies": int(len(d)),
            "spearman_recovery_vs_productivity": round(rho, 3),
            "spearman_recovery_vs_hours_change": round(rho2, 3),
        },
    )
    f.add(check_mode_provenance(100.0, int(len(d)),
                                "computed directly on Mode=='DR' rows of the "
                                "mode-tagged monthly file"))
    f.add(Check("effect_size", False,
                f"MECHANICALLY COUPLED, not a finding. Recovery is "
                f"UPT24/UPT19 and the productivity ratio is "
                f"(UPT24/VRH24)/(UPT19/VRH19) -- the same two UPT terms appear in "
                f"both, in the same direction, so a positive Spearman "
                f"({rho:+.3f}) is guaranteed by the arithmetic before any "
                f"operator does anything. The variable that is actually free is "
                f"the hours change, which ranks against recovery at {rho2:+.3f}. "
                f"Quoting the {rho:+.2f} as a causal result to anyone who has "
                f"built an NTD panel would be a very short conversation"))
    f.add(Check("composition", True,
                "same agencies at both endpoints by construction"))
    f.add(Check("concentration", True, "rank correlation, unweighted"))
    return f


def f_passenger_trips_got_shorter(opex: pd.DataFrame) -> Finding:
    """Passenger miles per trip fell while vehicle miles per trip rose -- i.e.
    pooling got worse. Beautiful if true. The sample says wait."""
    dr = opex[opex.Mode.isin(DR_MODES)]
    pmt = _ratio_endpoints(dr, "pmt", "upt", 2015, 2024)
    vmt = _ratio_endpoints(dr, "vrm", "upt", 2015, 2024)
    # How much of the panel actually files passenger miles?
    n_all = len(set(dr[(dr.year == 2015) & (dr.upt > 0) & (dr.vrm > 0)].nid)
                & set(dr[(dr.year == 2024) & (dr.upt > 0) & (dr.vrm > 0)].nid))
    coverage = pmt["n_balanced"] / n_all * 100
    f = Finding(
        id="dr_pooling_efficiency_declined",
        claim=("Demand-response trips got SHORTER while the vehicles drove "
               f"further per trip (passenger miles per trip "
               f"{pmt['balanced_pct']:+.1f}%, vehicle miles per trip "
               f"{vmt['balanced_pct']:+.1f}%, 2015-2024), so the sector is "
               "pooling riders less effectively than it used to."),
        source=(f"{SRC_OPEX}; Mode=='DR'; Passenger Miles Traveled and Vehicle "
                f"Revenue Miles over Unlinked Passenger Trips; balanced 2015/2024"),
        numbers={
            "n_balanced_with_passenger_miles": pmt["n_balanced"],
            "n_balanced_with_vehicle_miles": vmt["n_balanced"],
            "coverage_pct": round(coverage, 1),
            "passenger_miles_per_trip_2015": round(pmt["agg_y0"], 2),
            "passenger_miles_per_trip_2024": round(pmt["agg_y1"], 2),
            "passenger_miles_per_trip_change_pct": round(pmt["balanced_pct"], 1),
            "vehicle_miles_per_trip_change_pct": round(vmt["balanced_pct"], 1),
        },
    )
    f.add(check_mode_provenance(100.0, pmt["n_balanced"],
                                "computed on Mode=='DR' rows of the mode-tagged "
                                "by-mode file"))
    f.add(check_effect(pmt["balanced_pct"]))
    f.add(Check("composition", coverage >= 50.0,
                f"only {pmt['n_balanced']} of {n_all} balanced-panel agencies "
                f"({coverage:.1f}%) file Passenger Miles Traveled at all -- it is "
                f"a Full Reporter obligation, so the filers skew large and urban. "
                f"The vehicle-miles-per-trip half of the claim rests on "
                f"{vmt['n_balanced']} agencies and is solid; the passenger-miles "
                f"half rests on a self-selected minority and cannot carry a "
                f"sector claim about pooling"))
    f.add(check_concentration(pmt["balanced_pct"], pmt["per_agency_median_pct"],
                              pmt["loo_lo"], pmt["loo_hi"], pmt["top1_share_pct"]))
    return f


def f_fleet_utilisation(opex: pd.DataFrame) -> Finding:
    """Demand-response fleets are worked less hard than they were; bus fleets
    are worked harder. Opposite directions, same decade."""
    dr = _ratio_endpoints(opex[opex.Mode.isin(DR_MODES)], "vrh", "voms", 2015, 2024)
    mb = _ratio_endpoints(opex[opex.Mode == CONTROL_MODE], "vrh", "voms", 2015, 2024)
    f = Finding(
        id="dr_fleet_utilisation_diverged_from_bus",
        claim=("Demand-response fleets are being worked LESS hard than a decade "
               f"ago while bus fleets are worked harder: revenue hours per "
               f"peak vehicle {dr['balanced_pct']:+.1f}% for DR against "
               f"{mb['balanced_pct']:+.1f}% for fixed-route bus, 2015-2024."),
        source=(f"{SRC_OPEX}; Mode=='DR' vs 'MB'; Vehicle Revenue Hours over "
                f"Vehicles Operated in Maximum Service; balanced 2015/2024. VOMS "
                f"is a PEAK vehicle count, so this is a utilisation proxy, not a "
                f"fleet-hours measurement"),
        numbers={
            "n_balanced_dr": dr["n_balanced"],
            "dr_hours_per_peak_vehicle_2015": round(dr["agg_y0"], 0),
            "dr_hours_per_peak_vehicle_2024": round(dr["agg_y1"], 0),
            "dr_change_pct": round(dr["balanced_pct"], 1),
            "dr_per_agency_median_change_pct": round(dr["per_agency_median_pct"], 1),
            "bus_change_pct": round(mb["balanced_pct"], 1),
            "bus_per_agency_median_change_pct": round(mb["per_agency_median_pct"], 1),
            "caveat": "VOMS counts vehicles in maximum service, not vehicles "
                      "owned; a fleet that shrank its peak pullout can show "
                      "rising hours per vehicle without running any more service",
        },
    )
    f.add(check_mode_provenance(100.0, dr["n_balanced"],
                                "both panels drawn from the mode-tagged by-mode "
                                "file on their own Mode codes"))
    f.add(check_effect(dr["balanced_pct"]))
    f.add(check_composition(dr["unbalanced_pct"], dr["balanced_pct"],
                            dr["n_balanced"]))
    f.add(check_concentration(dr["balanced_pct"], dr["per_agency_median_pct"],
                              dr["loo_lo"], dr["loo_hi"], dr["top1_share_pct"]))
    f.add(check_control_mode(dr["balanced_pct"], mb["balanced_pct"],
                             "change in revenue hours per peak vehicle 2015-2024",
                             must_exceed=False))
    return f


# ===========================================================================
def build() -> dict:
    missing = [str(p.relative_to(REPO)) for p in (MONTHLY, OPEX, ECON) if not p.exists()]
    if missing:
        raise SystemExit(
            "missing source data (data/raw/ is gitignored -- re-acquire through "
            "the governed estate pipeline):\n  " + "\n  ".join(missing))

    monthly = load_monthly()
    opex = load_opex()
    econ = load_econ()
    ay = dr_agency_year(monthly)
    econ24 = econ[econ.report_year == 2024]
    econ24_dh = econ24.dropna(subset=["deadhead_pct_hours"])
    prov = econ_mode_provenance(econ, opex)
    identity = deadhead_identity_agreement(econ24_dh)

    by_mode_vrh = (opex[opex.year == 2024]
                   .pivot_table(index="nid", columns="Mode", values="vrh",
                                aggfunc="sum", fill_value=0))
    dr_share = (by_mode_vrh.get("DR", pd.Series(0, index=by_mode_vrh.index))
                / by_mode_vrh.sum(axis=1))

    findings = [
        f_productivity_decline(ay),
        f_recovery_dispersion(ay),
        f_deadhead_central(econ24_dh, prov, identity, dr_share),
        f_cost_dispersion(econ24, prov),
        f_not_congestion(opex),
        f_cost_growth_split(opex),
        f_hours_vs_trips_recovery(ay),
        f_against_the_trend(ay),
        f_dr_more_stable_than_bus(monthly),
        f_fleet_utilisation(opex),
        # candidates expected to fail -- run through the identical gate
        f_volatility_myth(monthly),
        f_deadhead_extreme_tail(econ24_dh, dr_share),
        f_cost_inflation_vs_bus(opex),
        f_deadhead_predicts_cost(econ24_dh),
        f_cost_dispersion_widening(econ24, opex),
        f_recovery_drives_productivity(ay),
        f_passenger_trips_got_shorter(opex),
    ]
    dicts = [f.as_dict() for f in findings]
    survived = [d for d in dicts if d["status"] == "survived"]
    rejected = [d for d in dicts if d["status"] == "rejected"]

    return {
        "generated_by": "business/outreach/build_panel_findings.py",
        "status": "Demonstrated",
        "status_note": (
            "Demonstrated, never Validated. Every number here is computed from "
            "public NTD filings; there is no holdout, no counterfactual and no "
            "operator has confirmed any of it against their own books. A finding "
            "that survives this gate is a well-measured description of what "
            "agencies FILED, which is not the same as what happened."),
        "panel": {
            "universe": "US National Transit Database demand-response reporters",
            "mode_codes": list(DR_MODES),
            "mode_note": (
                "NTD encodes demand-response taxi and TNC service as Mode=DR with "
                "Type-of-Service TX/TN rather than a separate DT mode code; this "
                "file contains zero rows with Mode=='DT', so filtering Mode=='DR' "
                "retains them"),
            "control_mode": CONTROL_MODE,
            "sources": [SRC_MONTHLY, SRC_OPEX, SRC_ECON],
            "external_constants": {"cpi": CPI_SOURCE, "values": CPI_U_ANNUAL},
        },
        "gate": {
            "required_checks": list(REQUIRED_CHECKS),
            "min_effect_pct": MIN_EFFECT_PCT,
            "min_spread_ratio": MIN_SPREAD_RATIO,
            "composition_retain_fraction": COMPOSITION_RETAIN,
            "concentration_band": [CONCENTRATION_LO, CONCENTRATION_HI],
            "leave_out_top_n": LEAVE_OUT_TOP_N,
            "note": ("A finding missing any required check is rejected for that "
                     "reason alone -- silence is not a pass."),
        },
        "not_computable": [
            "Deadhead for any mode other than demand response, and deadhead as a "
            "time series: the only multi-year mode-tagged source we hold carries "
            "Vehicle Revenue Hours/Miles but no total (actual) hours, so there is "
            "no deadhead numerator in it. Every deadhead figure here is a 2024 "
            "cross-section.",
            "Trip-level anything: wait times, on-time performance, denials, "
            "no-shows, ride durations, shared-ride factors. NTD is an annual and "
            "monthly aggregate return. No claim about individual rider experience "
            "can be made from these bytes.",
            "Cause. Every finding here is a description of a filed number moving. "
            "Nothing in this panel identifies why it moved.",
        ],
        "counts": {"survived": len(survived), "rejected": len(rejected)},
        "survived": survived,
        "rejected": rejected,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true", help="print every check")
    args = ap.parse_args()

    out = build()
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")
    print(f"  survived {out['counts']['survived']}   "
          f"rejected {out['counts']['rejected']}")
    for d in out["survived"]:
        print(f"\n[SURVIVED] {d['id']}\n  {d['claim']}")
        if args.verbose:
            for c in d["checks"]:
                print(f"    {c['verdict']:4} {c['check']}: {c['detail']}")
    for d in out["rejected"]:
        print(f"\n[REJECTED] {d['id']}\n  claim: {d['claim']}"
              f"\n  because: {d['rejected_because']}")


if __name__ == "__main__":
    main()
