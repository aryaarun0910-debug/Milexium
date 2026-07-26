"""Rendering the operating picture as one self-contained HTML file.

NO NETWORK, NO BUILD STEP, NO SCRIPT. The output is a single file that opens
from disk with the network cable pulled: the CSS is inline, there is no
JavaScript at all, and nothing is fetched. The bar charts are div widths and
the only "interaction" is the browser's own scrolling, because an operational
picture that needs a toolchain to be looked at is not showable.

THE SOURCE IS NOT A FOOTNOTE. Every figure renders as value, then label, then
its citation, in that order and in the same block. There is no hover, no
tooltip and no collapsed panel -- a viewer asking "where did that come from?"
should not have to discover an affordance to find out. That costs vertical
space and the page pays it deliberately.

This module holds no domain knowledge whatever. It receives `Figure` objects
that already carry their attribution and turns them into elements; if it were
deleted the numbers would be unchanged, which is the property that makes it a
renderer rather than a second place where facts are decided.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from argus.command_centre.attribution import ORIGIN_LABELS, Figure, Source
from argus.command_centre.picture import (
    ARGUS_PROHIBITION,
    SYNTHETIC_BANNER,
    OperatingPicture,
)

_CSS = """
:root{
  --bg:#f7f7f5; --panel:#fff; --ink:#16181d; --muted:#5c6270; --line:#dfe1e6;
  --accent:#1f4b99; --warn:#8a4b00; --refuse:#7a1f2b; --ok:#0f5c3f;
  --chip:#eef1f6; --scenario:#6b3fa0;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#111317; --panel:#181b21; --ink:#e8eaee; --muted:#9aa2b1; --line:#2a2f38;
    --accent:#8fb4ef; --warn:#e0a35c; --refuse:#f08a99; --ok:#6fd3a8;
    --chip:#22262e; --scenario:#c6a6ef;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:28px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:19px;margin:0 0 4px;letter-spacing:-.01em}
h3{font-size:15px;margin:18px 0 8px;color:var(--muted);
  text-transform:uppercase;letter-spacing:.08em;font-weight:650}
p{margin:0 0 10px}
a{color:var(--accent)}
.sub{color:var(--muted);margin:0 0 22px}
.banner{border:1px solid var(--refuse);border-left-width:5px;border-radius:6px;
  padding:14px 16px;margin:0 0 18px;background:var(--panel)}
.banner strong{color:var(--refuse)}
.prohibition{border:1px solid var(--line);border-left:5px solid var(--accent);
  border-radius:6px;padding:14px 16px;margin:0 0 26px;background:var(--panel);
  font-style:italic;color:var(--ink)}
section{background:var(--panel);border:1px solid var(--line);border-radius:8px;
  padding:20px 22px;margin:0 0 18px}
.lede{color:var(--muted);margin:0 0 16px;max-width:72ch}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.fig{border:1px solid var(--line);border-radius:6px;padding:12px 14px;background:transparent}
.fig .v{font-size:22px;font-weight:660;letter-spacing:-.01em;
  font-variant-numeric:tabular-nums;word-break:break-word}
.fig .l{font-size:13px;color:var(--muted);margin-top:2px}
.fig .n{font-size:12.5px;color:var(--ink);margin-top:8px;opacity:.85}
.src{margin-top:10px;padding-top:8px;border-top:1px dashed var(--line);
  font:11.5px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--muted);
  word-break:break-word}
.src .tag{display:inline-block;padding:1px 6px;border-radius:3px;background:var(--chip);
  color:var(--ink);margin-right:6px;font-weight:600}
.src .tag.scenario{background:transparent;border:1px solid var(--scenario);color:var(--scenario)}
.sha{opacity:.7}
table{width:100%;border-collapse:collapse;font-size:13.5px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);
  vertical-align:top;font-variant-numeric:tabular-nums}
th{color:var(--muted);font-weight:640;font-size:12px;text-transform:uppercase;
  letter-spacing:.05em;white-space:nowrap}
tr.short td{background:rgba(138,75,0,.10)}
code{font:12.5px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  background:var(--chip);padding:1px 5px;border-radius:3px}
.pill{display:inline-block;padding:1px 8px;border-radius:99px;font-size:11.5px;
  font-weight:650;border:1px solid currentColor}
.pill.no{color:var(--refuse)} .pill.yes{color:var(--ok)} .pill.cf{color:var(--warn)}
.refusal{border:1px solid var(--line);border-left:5px solid var(--refuse);
  border-radius:6px;padding:14px 16px;margin:0 0 12px}
.refusal h4{margin:0 0 6px;font-size:15px;color:var(--refuse)}
.refusal .what{margin:0 0 8px}
.refusal .why{color:var(--muted);margin:0}
.finding{border:1px solid var(--line);border-left:5px solid var(--warn);
  border-radius:6px;padding:14px 16px;margin:0 0 12px}
ul{margin:0 0 10px;padding-left:20px} li{margin:0 0 7px}
.bar{height:9px;border-radius:2px;background:var(--accent);display:block;min-width:2px}
.bar.wc{background:var(--warn)}
.muted{color:var(--muted)}
footer{color:var(--muted);font-size:12.5px;margin-top:26px;border-top:1px solid var(--line);
  padding-top:16px}
"""


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def _source_line(source: Source) -> str:
    tag_class = "tag scenario" if source.origin == "scenario" else "tag"
    sha = (
        f' <span class="sha">sha256 {_esc(source.sha256[:16])}…</span>'
        if source.sha256
        else ""
    )
    return (
        f'<div class="src"><span class="{tag_class}">{_esc(ORIGIN_LABELS[source.origin])}</span>'
        f"{_esc(source.citation)}{sha}<br>{_esc(source.detail)}</div>"
    )


def _figure_card(figure: Figure) -> str:
    note = f'<div class="n">{_esc(figure.note)}</div>' if figure.note else ""
    return (
        f'<div class="fig"><div class="v">{_esc(figure.display)}</div>'
        f'<div class="l">{_esc(figure.label)}</div>{note}{_source_line(figure.source)}</div>'
    )


def _cards(picture: OperatingPicture, *keys: str) -> str:
    cards = [_figure_card(picture.figure(key)) for key in keys if picture.has(key)]
    return f'<div class="grid">{"".join(cards)}</div>' if cards else ""


def _table(
    headers: list[str],
    rows: list[list[str]],
    source: Source | None = None,
    row_classes: list[str] | None = None,
) -> str:
    """A table and, beneath it, the source of every number in it.

    `source` is optional in the signature and required in practice: a table
    rendered without one shows a visible marker rather than nothing, so the
    omission is impossible to miss on the page and easy to assert on in a test.
    """
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = []
    for index, row in enumerate(rows):
        cls = f' class="{row_classes[index]}"' if row_classes and row_classes[index] else ""
        body.append(f"<tr{cls}>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    attribution = (
        _source_line(source)
        if source is not None
        else '<div class="src">UNATTRIBUTED TABLE — this is a defect</div>'
    )
    return (
        f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>{attribution}'
    )


def _pill(ok: bool, yes: str = "certified", no: str = "refused") -> str:
    cls = "yes" if ok else "no"
    return f'<span class="pill {cls}">{_esc(yes if ok else no)}</span>'


def render_html(picture: OperatingPicture) -> str:
    """Turn the picture into one string of HTML. No I/O, so it is testable."""
    out: list[str] = []
    add = out.append

    # A complete document, because this file is opened from disk rather than
    # embedded: without an explicit charset a browser guesses, and every em
    # dash and plus-minus sign on the page is a candidate for mojibake.
    add("<!doctype html>")
    add('<html lang="en"><head><meta charset="utf-8">')
    add('<meta name="viewport" content="width=device-width, initial-scale=1">')
    add(f"<title>Milexium command centre — {_esc(picture.service_day)}</title>")
    add(f"<style>{_CSS}</style>")
    add('</head><body><div class="wrap">')

    # ---- header -------------------------------------------------------
    add("<h1>Milexium command centre</h1>")
    add(
        f'<p class="sub">Synthetic service day {_esc(picture.service_day)} · built '
        f'{_esc(picture.generated_at.strftime("%Y-%m-%d %H:%M UTC"))} · '
        f"{len(picture.ledger)} attributed figures</p>"
    )
    add(f'<div class="banner"><strong>{_esc(SYNTHETIC_BANNER)}</strong></div>')
    add(f'<div class="prohibition">{_esc(ARGUS_PROHIBITION)}</div>')

    origins = picture.ledger.by_origin()
    add("<section>")
    add("<h2>How to read this page</h2>")
    add(
        '<p class="lede">Every number below carries the layer that produced it, the '
        "exact call or file it came from, and a statement of what was read — printed "
        "underneath the number, not hidden behind a tooltip. Where a layer declined to "
        "produce something, this page renders the refusal instead of a substitute.</p>"
    )
    add(
        _table(
            ["Attribution", "Figures", "What it means"],
            [
                [
                    _esc(ORIGIN_LABELS[origin]),
                    str(count),
                    _esc(
                        {
                            "themis": "A governed record. Argus read it; Argus did not decide it.",
                            "metis": "A model, solver or checker output, computed this run.",
                            "aletheia": "Evidence: an evidence packet, a teardown, a re-derivation.",
                            "corpus": "A committed file, cited by repo path and SHA-256.",
                            "scenario": "A DECLARED modelling input with no authority behind it. "
                            "Listed in full at the foot of the page.",
                            "argus": "This page measuring itself — build time, figure counts. "
                            "Not a claim about transport.",
                        }[origin]
                    ),
                ]
                for origin, count in origins.items()
            ],
            picture.table_sources.get("attribution_summary"),
        )
    )
    add("</section>")

    # ---- current state -------------------------------------------------
    add("<section>")
    add("<h2>Current state</h2>")
    add(
        '<p class="lede">What is in play on this service day, as governed records. '
        "Nothing here is inferred.</p>"
    )
    add(
        _cards(
            picture,
            "requests_in_play",
            "vehicles_in_play",
            "runs_in_play",
            "denied_requests",
            "no_show_requests",
            "quarantined",
            "export_rows",
            "repair_records",
        )
    )
    add("<h3>Vehicles</h3>")
    add(
        _table(
            ["Vehicle", "Observed shift envelope", "Trips", "Runs"],
            [
                [
                    f"<code>{_esc(v['label'])}</code>",
                    f"{_esc(v['shift_start'])}–{_esc(v['shift_end'])} UTC",
                    str(v["trips"]),
                    _esc(", ".join(v["runs"]) or "—"),
                ]
                for v in picture.vehicles
            ],
            picture.table_sources.get("vehicles"),
        )
    )
    add("<h3>Requests</h3>")
    add(
        _table(
            ["Ref", "Vehicle", "Run", "Zones", "Scheduled", "Status", "On time"],
            [
                [
                    f"<code>{_esc(r['ref'])}</code>",
                    _esc(r["vehicle"]),
                    _esc(r["run"] or "—"),
                    f"{_esc(r['pickup_zone'])} → {_esc(r['dropoff_zone'])}",
                    _esc(r["scheduled"]),
                    _esc(r["status"]),
                    _esc("not computed" if r["on_time"] is None else r["on_time"]),
                ]
                for r in picture.requests
            ],
            picture.table_sources.get("requests"),
        )
    )
    add("</section>")

    # ---- forecast risk ---------------------------------------------------
    add("<section>")
    add("<h2>Forecast risk for the upcoming window</h2>")
    add(
        '<p class="lede">Where and when demand is likely to exceed capacity. This is '
        "the section where the layer boundary is most visible: Argus asks Metis for a "
        "forecast, and renders whatever Metis says — including nothing.</p>"
    )
    add(_cards(picture, "forecast_available", "forecast_feature_schema"))
    add("<h3>Demand already in the book, against capacity in service</h3>")
    peak = max((band.pickups for band in picture.hour_bands), default=1) or 1
    rows = []
    classes = []
    for band in picture.hour_bands:
        width = int(100 * band.pickups / peak)
        wc_width = int(100 * band.wheelchair_pickups / peak)
        rows.append(
            [
                f"{band.hour:02d}:00",
                f'{band.pickups} <span class="bar" style="width:{width}%"></span>',
                f'{band.wheelchair_pickups} <span class="bar wc" style="width:{wc_width}%"></span>',
                str(band.vehicles_in_service),
                str(band.accessible_in_service),
                str(band.accessible_positions),
                (
                    '<span class="pill no">demand &gt; positions</span>'
                    if band.accessible_short
                    else '<span class="muted">—</span>'
                ),
            ]
        )
        classes.append("short" if band.accessible_short else "")
    add(
        _table(
            [
                "Hour",
                "Scheduled pickups",
                "of which ASSIGNED wheelchair",
                "Vehicles in service",
                "Accessible in service",
                "Wheelchair positions",
                "",
            ],
            rows,
            picture.table_sources.get("hour_bands"),
            classes,
        )
    )
    add(_cards(picture, "hours_accessible_short"))
    add("</section>")

    # ---- scarce accessible capacity --------------------------------------
    add("<section>")
    add("<h2>Scarce accessible capacity</h2>")
    add(
        '<p class="lede">A wheelchair position is not a seat and the two are not '
        "fungible. This is the resource that actually binds, so it is counted "
        "separately everywhere on this page rather than folded into a capacity "
        "total.</p>"
    )
    add(
        _cards(
            picture,
            "wheelchair_positions_total",
            "wheelchair_requests",
            "accessible_vehicles",
            "equipment_layer_can_bind",
            "projected_requests",
            "mean_trip_minutes",
        )
    )
    add("</section>")

    # ---- the decision ----------------------------------------------------
    add("<section>")
    add("<h2>The decision, and every alternative that was rejected</h2>")
    add(
        '<p class="lede">One late booking, three candidate vehicles, two independent '
        "authorities. Each line below is a separate solve or a separate certification "
        "run at build time — not a summary, and not asserted.</p>"
    )
    add(
        _cards(
            picture,
            "decision_status",
            "decision_served",
            "decision_reason_codes",
            "feasibility_violations",
            "alternatives_probed",
            "equipment_checker_refusals",
        )
    )
    add("<h3>Candidate placements</h3>")
    add(
        '<p class="lede">Two authorities answer different questions and are shown '
        "separately rather than reconciled. <code>metis.decide.solve</code> is the "
        "authority on <em>whether to serve</em>: it carries a shift start and end per "
        "vehicle, and denies. <code>certify_insertion</code> is the authority on "
        "<em>what a schedule can absorb</em>: its instance has one depot window for the "
        "whole fleet and cannot express a shift end at all, so where it certifies, it is "
        "answering a strictly weaker question. Neither is edited to agree with the "
        "other.</p>"
    )
    add(
        _table(
            ["Vehicle", "Authority", "Verdict", "Binding constraint", "How it was established"],
            [
                [
                    f"<code>{_esc(o.label)}</code>",
                    f"<code>{_esc(o.authority)}</code>",
                    _pill(o.feasible),
                    f"<code>{_esc(o.binding)}</code>",
                    _esc(o.detail),
                ]
                for o in picture.options
            ],
            picture.table_sources.get("options"),
        )
    )
    add("</section>")

    # ---- future capacity cost --------------------------------------------
    add("<section>")
    add("<h2>What it would cost in future capacity</h2>")
    add(
        '<p class="lede">Foreclosure at decision time: how many likely future trips a '
        "commitment makes infeasible, stratified by whether they need a "
        "wheelchair-accessible vehicle. The feasibility half is exact — a hypothetical "
        "trip counts only when two independent checkers accept a concrete schedule for "
        "it. The demand half is a stated placeholder.</p>"
    )
    add(_cards(picture, "reach_empty_fleet", "reach_committed_fleet", "day_foreclosure"))
    if picture.capacity_rows:
        add("<h3>Foreclosure by commitment</h3>")
        add(
            _table(
                [
                    "Commitment",
                    "Kind",
                    "Accessible vehicle",
                    "Future trips foreclosed",
                    "of which accessible",
                    "Larger than its own noise?",
                ],
                [
                    [
                        f"<code>{_esc(row['label'])}</code>",
                        (
                            f'<span class="pill cf">{_esc(row["kind"])}</span>'
                            if "COUNTERFACTUAL" in row["kind"]
                            else _esc(row["kind"])
                        ),
                        "yes" if row["accessible"] else "no",
                        f"{row['trips_foreclosed']:.2f} ± {row['stderr']:.2f}",
                        f"{row['accessible_trips_foreclosed']:.2f} ± "
                        f"{row['accessible_stderr']:.2f}",
                        _pill(row["distinguishable_from_zero"], "yes", "no — sampling noise"),
                    ]
                    for row in picture.capacity_rows
                ],
                picture.table_sources.get("capacity_rows"),
            )
        )
    add(_cards(picture, "counterfactual_foreclosure", "foreclosure_distinguishable"))
    add(_cards(picture, "capacity_prior_note"))
    add("</section>")

    # ---- uncertainty -----------------------------------------------------
    if picture.has("drift_serving"):
        add("<section>")
        add("<h2>Uncertainty, and what would invalidate this</h2>")
        add(
            '<p class="lede">Milexium\'s serve-time drift monitor, run at build time on '
            "the only real demand panel in this repository. It is here because it "
            "answers the invalidation question with a measurement rather than a "
            "paragraph — and because the same monitor is shown returning both answers, "
            "so a reader can tell a real test from a warning that is always on. "
            "<strong>It is about the Access-A-Ride panel, not about the synthetic "
            "operator above.</strong></p>"
        )
        add(_cards(picture, "drift_control", "drift_serving", "drift_reference_rows"))
        if picture.drift_features:
            add("<h3>Per feature</h3>")
            add(
                _table(
                    ["Feature", "PSI", "Band", "KS p-value", "Flagged"],
                    [
                        [
                            f"<code>{_esc(f['feature'])}</code>",
                            "n/a" if f["psi"] is None else f"{f['psi']:.4f}",
                            _esc(f["psi_band"] or (f["note"] or "")[:28]),
                            "n/a" if f["ks_p_value"] is None else f"{f['ks_p_value']:.2e}",
                            (
                                '<span class="pill no">yes</span>'
                                if f["flagged"]
                                else '<span class="muted">—</span>'
                            ),
                        ]
                        for f in picture.drift_features
                    ],
                    picture.table_sources.get("drift_features"),
                )
            )
        add("</section>")

    # ---- authorisation ---------------------------------------------------
    add("<section>")
    add("<h2>Human authorisation</h2>")
    add(
        '<p class="lede">The recommendation, the denial and the human review, on an '
        "append-only hash-chained ledger, read back after they were written.</p>"
    )
    add(
        _cards(
            picture,
            "authorisation",
            "ledger_events",
            "chain_integrity",
            "alternatives_on_the_record",
        )
    )
    add(
        _table(
            ["#", "Event", "Actor", "At", "Reason codes", "prev_hash → hash"],
            [
                [
                    str(e["sequence"]),
                    f"<code>{_esc(e['event_type'])}</code>",
                    f"{_esc(e['actor_type'])}:{_esc(e['actor_id'])}",
                    _esc(e["occurred_at"]),
                    _esc(", ".join(e["reason_codes"]) or "—"),
                    f"<code>{_esc(e['prev_hash'] or '∅')}</code> → "
                    f"<code>{_esc(e['hash'])}</code>",
                ]
                for e in picture.ledger_events
            ],
            picture.table_sources.get("ledger_events"),
        )
    )
    add("</section>")

    # ---- outcome ---------------------------------------------------------
    add("<section>")
    add("<h2>The later actual outcome, against what was expected</h2>")
    add(
        '<p class="lede">The recommendation was recorded before the outcome was known. '
        "This is the comparison that makes the record worth keeping.</p>"
    )
    add(_cards(picture, "expected_outcome", "actual_outcome", "outcome_agreement", "on_time_flag"))
    add("<h3>What the day cost</h3>")
    add(
        _cards(
            picture,
            "deadhead_minutes",
            "deadhead_share",
            "ntd_peer_deadhead",
            "cost_per_vrh",
            "value_at_full_cost",
            "unattributable_minutes",
        )
    )
    add("</section>")

    # ---- refusals --------------------------------------------------------
    add("<section>")
    add(f"<h2>What this platform refused to tell you ({len(picture.refusals)})</h2>")
    add(
        '<p class="lede">A surface that only shows confident answers misrepresents the '
        "product. Each of these is a place the platform declined, and the reason the "
        "decline is the feature.</p>"
    )
    for refusal in picture.refusals:
        add(
            f'<div class="refusal"><h4>{_esc(refusal.headline)}</h4>'
            f'<p class="what">{_esc(refusal.refused)}</p>'
            f'<p class="why">{_esc(refusal.why)}</p>'
            f'<div class="src"><span class="tag">{_esc(ORIGIN_LABELS[refusal.source.origin])}</span>'
            f"{_esc(refusal.source.citation)}<br>{_esc(refusal.source.detail)}</div></div>"
        )
    add("</section>")

    # ---- findings --------------------------------------------------------
    if picture.findings:
        add("<section>")
        add("<h2>Found while wiring the layers together</h2>")
        add(
            '<p class="lede">This page is the first surface that touches Themis, Metis '
            "and Aletheia at once. What it hit is reported here rather than worked "
            "around in the layer that has the problem.</p>"
        )
        for finding in picture.findings:
            add(f'<div class="finding">{_esc(finding)}</div>')
        add("</section>")

    # ---- scenario inputs -------------------------------------------------
    add("<section>")
    add("<h2>Every declared input this picture rests on</h2>")
    add(
        '<p class="lede">These are modelling assumptions with no authority behind them. '
        "They are listed in full, and every figure that depends on one is tagged "
        "<em>DECLARED scenario input</em> where it appears above.</p>"
    )
    add(
        _table(
            ["Input", "Value", "Why it is declared rather than read"],
            [
                [_esc(s.name), f"<code>{_esc(s.value)}</code>", _esc(s.why)]
                for s in picture.scenario_inputs
            ],
            picture.table_sources.get("scenario_inputs"),
        )
    )
    add("</section>")

    # ---- limitations -----------------------------------------------------
    add("<section>")
    add("<h2>Limitations</h2>")
    add("<ul>")
    for limitation in picture.limitations:
        add(f"<li>{_esc(limitation)}</li>")
    add("</ul>")
    add(_cards(picture, "runtime_seconds"))
    add("</section>")

    add(
        "<footer>Demonstrated. Not Validated. No customers, no pilots, no operator "
        "data. Generated by <code>argus/command_centre/</code>; the structured data "
        "behind every figure on this page is written alongside it as "
        "<code>operating_picture.json</code>.</footer>"
    )
    add("</div></body></html>")
    return "\n".join(out)


def write_artifact(picture: OperatingPicture, output_dir: Path) -> tuple[Path, Path]:
    """Write the page and its machine-checkable sidecar. Returns both paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    page = output_dir / "index.html"
    sidecar = output_dir / "operating_picture.json"
    page.write_text(render_html(picture), encoding="utf-8")
    sidecar.write_text(
        json.dumps(picture.to_record(), indent=1, sort_keys=False, default=str) + "\n",
        encoding="utf-8",
    )
    return page, sidecar
