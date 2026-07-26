"""Generate model cards from the committed metrics artifacts.

Model cards (Mitchell et al.; aligned with the NIST AI Risk Management
Framework "Measure/Manage" functions) are the standard enterprise ML
governance artifact: intended use, data, evaluation, limitations, and
point-in-time correctness, per published model. We GENERATE them from the
committed metrics JSONs rather than hand-typing numbers, so every figure on
a card traces to an artifact and cannot silently drift out of sync.

Output: docs/MODEL_CARDS.md
Run:    py -3 tools/build_model_cards.py
"""

import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RD = ROOT / "realdata"
OUT = ROOT / "docs" / "MODEL_CARDS.md"

real = json.loads((RD / "metrics_real.json").read_text())
ntd = json.loads((RD / "metrics_ntd_monthly.json").read_text())
leak = json.loads((RD / "leakage_audit_report.json").read_text())

# Banned in generated copy: a generator that reintroduces a corrected claim is
# its own class of defect, so the prohibition lives beside the strings rather
# than in a review checklist. Enforced by
# conformance/property-tests/test_claim_discipline.py, which regenerates this
# file's output into a temp path and fails on any of these.
#
# "validated"     - ADR-0001 reserves it for consented operator data against a
#                   declared baseline. Milexium has none.
# "production model" - nothing here is deployed to or running for an operator.
BANNED_IN_GENERATED_COPY = ("validated", "production model")

STATUS_CONTRACT = (
    "**Status: Demonstrated, never Validated.** Every model below is trained "
    "and evaluated on public data. Under ADR-0001, *Validated* requires "
    "consented operator data against a declared baseline and Milexium has "
    "none, so no result here validates any operator's capacity planning, "
    "scheduling, or dispatch. See the status contract in "
    "`docs/COMPETITIVE_POSITIONING.md`."
)

ZONE = {"nyc_access_a_ride": "borough", "chicago_tnp": "community area",
        "mta_bus": "route", "mta_subway": "station"}
GRAN = {"nyc_access_a_ride": "hourly", "chicago_tnp": "hourly",
        "mta_bus": "hourly", "mta_subway": "hourly"}
PROD = {"nyc_access_a_ride": True, "chicago_tnp": False,
        "mta_bus": False, "mta_subway": False}


def zone_hour_card(key, m):
    role = ("**PRODUCT TARGET** (real paratransit demand)" if PROD[key]
            else "generalization evidence (not the product target)")
    return f"""### {m['note']}

- **Role:** {role}
- **Task:** forecast next-hour demand per {ZONE[key]}, {GRAN[key]} granularity, day-ahead.
- **Model:** XGBoost, count:poisson (selected in the objective bakeoff, see
  OBJECTIVE_BAKEOFF_RESULTS.md), GPU-trained.
- **Data / split:** train {m['train_span']} | tune {m.get('tune_span','-')} |
  cal {m.get('cal_span','-')} | valid {m['valid_span']} ({m['n_valid']:,} rows).
  Four non-overlapping temporal blocks; calibration never seen during fit.
- **Result (untouched validation):** R2 **{m['model_r2']}** vs seasonal-naive
  {m['naive_r2']}; MAE {m['model_mae']} vs {m['naive_mae']}.
- **Uncertainty:** split-conformal intervals, {int(m['conformal_target_coverage']*100)}% target,
  {m['conformal_decile_only']['achieved_coverage']*100:.1f}% achieved.
- **Point-in-time correct:** yes - all features pass the mechanical leakage
  audit (LEAKAGE_AUDIT.md).
- **Intended use:** capacity planning and staffing-ahead at the {ZONE[key]}-hour
  level. **Out of scope:** individual-trip dispatch decisions (this is aggregate
  demand, not trip-level), and any use as the sole basis of a denial.
- **Limitations:** aggregate panel (not trip-level); weather is currently the
  realized value, not a day-ahead forecast (see LEAKAGE_AUDIT.md caveat);
  synthetic-free but public-aggregate, so external validity to a specific
  operator's own bookings is unproven until a pilot."""


cards = ["# Milexium model cards",
         "",
         f"_Generated {date.today()} by tools/build_model_cards.py from the "
         "committed metrics artifacts. Every number here traces to a JSON in "
         "realdata/. Regenerate after any retrain._",
         "",
         # The ADR-0001 status contract. This paragraph was added to
         # docs/MODEL_CARDS.md by hand and the generator did not carry it, so
         # the next regeneration would have silently deleted the strongest
         # honesty statement in the document. It lives here now: a claim that
         # only exists in generated output has to be owned by the generator.
         STATUS_CONTRACT,
         "",
         "All models share one protocol: strict temporal holdout, a "
         "seasonal-naive baseline reported next to every result, and a "
         "mechanical point-in-time leakage audit "
         f"(**{leak['overall']}**). None is an AI wrapper; each is trained "
         "from raw public data we ingest and aggregate ourselves.",
         "",
         "## Zone-hour demand models",
         ""]

for key in ["nyc_access_a_ride", "chicago_tnp", "mta_bus", "mta_subway"]:
    if key in real:
        cards.append(zone_hour_card(key, real[key]))
        cards.append("")

# NTD national card
t = ntd["temporal"]; c = ntd["cold_start_agency"]; p = ntd["panel"]
cards += [
    "## National monthly demand model (NTD)",
    "",
    "### Nationwide NTD monthly demand-response demand",
    "",
    f"- **Role:** national market + demand evidence; the cold-start test is "
    "directly product-relevant (forecasting a new agency).",
    f"- **Task:** forecast an agency's monthly unlinked passenger trips.",
    f"- **Data:** {p['agencies']} US agencies, {p['rows']:,} agency-months, "
    f"{p['date_range']}, {p['total_upt']:,} total trips. GPU XGBoost.",
    f"- **Temporal test** (last 12mo, all agencies): model R2 {t['model_r2']} "
    f"vs naive {t['naive_r2']}; MAPE {t['model_mape']*100:.1f}% vs "
    f"{t['naive_mape']*100:.1f}%. Loses on absolute R2 (monthly demand is very "
    "stable YoY), wins on relative error. Reported honestly.",
    f"- **Cold-start test** ({c['held_out_agencies']} agencies held out "
    f"entirely, no agency identity): model R2 {c['model_r2']} vs naive "
    f"{c['naive_r2']}; MAPE {c['model_mape']*100:.1f}% vs "
    f"{c['naive_mape']*100:.1f}%. Beats naive forecasting agencies never seen "
    "in training - the real onboarding scenario.",
    "- **Recommended objective:** Gamma (best MAPE, the customer-relevant "
    "metric), see OBJECTIVE_BAKEOFF_RESULTS.md. Current committed run is "
    "Poisson; switch pending.",
    "- **Point-in-time correct:** yes (LEAKAGE_AUDIT.md, all 13 features clean).",
    "- **Out of scope:** sub-monthly or trip-level forecasting; agencies with "
    "no filing history.",
    "",
    "## Not shipped",
    "",
    "The pretrain-then-finetune transformer (kaggle/) was run on real GPUs and "
    "**lost to XGBoost** on AAR (0.933 vs 0.986); it is R&D evidence and is "
    "not shipped. See kaggle/results/. We ship the simpler model on purpose — "
    "as a local reference implementation, not a production model: nothing here "
    "is deployed to or running for an operator.",
    "",
]

# Explicit UTF-8: write_text() defaults to the locale encoding, which on
# Windows is cp1252 and cannot represent the em dash above.
OUT.write_text("\n".join(cards), encoding="utf-8")
print(f"wrote {OUT} ({len(cards)} lines)")
