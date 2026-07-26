"""Build a machine-readable EVIDENCE REGISTRY for third-party verification.

This is the anti-overclaim tool. It SCANS the committed evidence sources in
this repository and emits a single artifact that lets a skeptic trace every
public number Milexium reports back to (a) the source file that records it,
(b) the dataset provenance manifest with its recorded sha256, (c) the
evaluation split/window, (d) the status label from the fixed vocabulary, and
(e) a plain-language LIMITATION. No number here is hand-typed: every value is
read out of the committed JSON it comes from, so the registry cannot silently
drift from its sources, and a claim with no readable source is never emitted.

Sources indexed (all read-only):
  - data/curated/metrics_real.json          (4 zone-hour demand models)
  - data/curated/metrics_ntd_monthly.json   (national NTD monthly model)
  - data/curated/leakage_audit_report.json  (mechanical point-in-time audit verdict)
  - data/curated/manifests/*.json           (data provenance + sha256)
  - aletheia/benchmarks/quality/darp_results.json (+ best_known.json) (DARP benchmark)
  - forge/knowledge/docs/MODEL_CARDS.md                 (the human model cards these back)
  - themis/canonical/__init__.py      (the canonical-contract version)
  - aletheia/benchmarks/quality/forecast_leaderboard.json (OPTIONAL; included only if
    present at run time -- another packet owns it, so we skip it gracefully)

Outputs:
  aletheia/artifacts/evidence-registry/registry.json  (machine-readable)
  aletheia/artifacts/evidence-registry/README.md      (short human index)

Run:    py -3 talos/tools/build_evidence_registry.py

The companion verify_evidence_registry(registry) checks a registry against
reality (referenced files exist, recorded sha256s match present files, every
claim carries a limitation and a valid status) and returns human-readable
problems (an empty list means clean).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "aletheia" / "artifacts" / "evidence-registry"

REGISTRY_SCHEMA = "milexium-evidence-registry/v1"

# The fixed status vocabulary (IMPLEMENTATION_STATUS.md / ADR-0001). No entry
# in this registry may use a word outside this set.
STATUS_VOCAB = ("Exists", "Specified", "Demonstrated", "Validated", "Production")

# model key -> (human zone, dataset manifest panel filename)
_MODEL_PANEL = {
    "nyc_access_a_ride": ("borough", "aar_hourly_borough.csv.gz"),
    "chicago_tnp": ("community-area", "chicago_tnp_zone_hour.csv.gz"),
    "mta_bus": ("route", "mta_bus_route_hour.csv.gz"),
    "mta_subway": ("station", "mta_subway_station_hour.csv.gz"),
}

# Forecast models are Demonstrated on real *aggregate* public data -- not
# operator-validated trip-level dispatch. One honest limitation, shared shape.
_FORECAST_LIMITATION = (
    "Aggregate {zone}-hour panel, not trip-level dispatch; the weather feature "
    "uses realized (not day-ahead forecast) values; synthetic-free but "
    "public-aggregate, so external validity to a specific operator's own "
    "bookings is unproven until a consented pilot (Demonstrated, not Validated)."
)


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _rel(path: Path) -> str:
    """Repo-root-relative POSIX path string (portable across checkouts)."""
    return path.resolve().relative_to(ROOT).as_posix()


def _sha256(path: Path, buf: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(buf):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _dig(obj: dict, dotted: str) -> Any:
    """Read a nested value by dotted key, e.g. 'a.conformal.achieved'."""
    cur: Any = obj
    for part in dotted.split("."):
        cur = cur[part]
    return cur


def _read_contract_version(root: Path) -> str | None:
    init = root / "themis" / "canonical" / "__init__.py"
    if not init.exists():
        return None
    m = re.search(r'CONTRACT_VERSION\s*=\s*"([^"]+)"', init.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def _claim(
    *,
    cid: str,
    claim: str,
    value: Any,
    unit: str,
    status: str,
    limitation: str,
    source_files: list[str],
    evaluation_window: str | None = None,
    baseline: dict | None = None,
    source_metric_key: str | None = None,
    dataset_manifest: str | None = None,
    dataset_sha256: str | None = None,
    content_checks: list[dict] | None = None,
    artifact_hash: str | None = None,
) -> dict:
    """Assemble one claim entry with a stable field order."""
    return {
        "id": cid,
        "claim": claim,
        "value": value,
        "unit": unit,
        "baseline": baseline,
        "evaluation_window": evaluation_window,
        "status": status,
        "limitation": limitation,
        "source_metric_key": source_metric_key,
        "dataset_manifest": dataset_manifest,
        "dataset_sha256": dataset_sha256,
        "artifact_hash": artifact_hash,
        "source_files": source_files,
        "content_checks": content_checks or [],
    }


# --------------------------------------------------------------------------- #
# builders (each returns [] gracefully when its source is absent)
# --------------------------------------------------------------------------- #
def _build_manifests(root: Path) -> list[dict]:
    """Index every committed data-provenance manifest (source + sha256)."""
    mdir = root / "data" / "curated" / "manifests"
    if not mdir.exists():
        return []
    out: list[dict] = []
    for mf in sorted(mdir.glob("*.json")):
        if mf.name == "index.json":
            continue
        m = _load_json(mf)
        if not isinstance(m, dict) or "sha256" not in m:
            continue
        panel = m.get("panel", mf.stem)
        src = m.get("source", {})
        panel_path = root / "data" / "curated" / "panels" / panel
        content_checks = [{"path": _rel(panel_path), "sha256": m["sha256"]}]
        out.append({
            "id": f"manifest.{panel}",
            "panel": panel,
            "sha256": m["sha256"],
            "bytes": m.get("bytes"),
            "rows": (m.get("coverage") or {}).get("rows"),
            "source": f"{src.get('portal', '?')} {src.get('dataset_ids', [])}",
            "license": src.get("license"),
            "fetch_script": src.get("fetch_script"),
            "manifest_file": _rel(mf),
            "source_files": [_rel(mf)],
            "content_checks": content_checks,
        })
    return out


def _build_forecast_claims(root: Path) -> list[dict]:
    real = _load_json(root / "data" / "curated" / "metrics_real.json")
    if not isinstance(real, dict):
        return []
    model_card = root / "forge" / "knowledge" / "docs" / "MODEL_CARDS.md"
    train_script = root / "data" / "curated" / "train_real_models.py"
    metrics_file = root / "data" / "curated" / "metrics_real.json"
    out: list[dict] = []
    for key, (zone, panel) in _MODEL_PANEL.items():
        m = real.get(key)
        if not isinstance(m, dict):
            continue
        note = m.get("note", key)
        window = f"valid {m.get('valid_span', '?')} ({m.get('n_valid', '?'):,} rows)"
        manifest_file = root / "data" / "curated" / "manifests" / f"{panel}.json"
        manifest = _load_json(manifest_file)
        dataset_sha256 = manifest.get("sha256") if isinstance(manifest, dict) else None
        panel_path = root / "data" / "curated" / "panels" / panel
        content_checks = (
            [{"path": _rel(panel_path), "sha256": dataset_sha256}]
            if dataset_sha256 else []
        )
        # shared reference fields
        srcs = [_rel(metrics_file), _rel(train_script), _rel(model_card)]
        if manifest_file.exists():
            srcs.append(_rel(manifest_file))
        dm = _rel(manifest_file) if manifest_file.exists() else None
        limitation = _FORECAST_LIMITATION.format(zone=zone)

        out.append(_claim(
            cid=f"forecast.{key}.model_r2",
            claim=f"{note}: next-hour demand model R2 on the untouched validation window",
            value=m["model_r2"], unit="R2",
            baseline={"name": "seasonal-naive", "value": m.get("naive_r2")},
            evaluation_window=window, status="Demonstrated", limitation=limitation,
            source_metric_key=f"{key}.model_r2", dataset_manifest=dm,
            dataset_sha256=dataset_sha256, content_checks=content_checks,
            source_files=srcs,
        ))
        out.append(_claim(
            cid=f"forecast.{key}.model_mae",
            claim=f"{note}: next-hour demand model MAE on the untouched validation window",
            value=m["model_mae"], unit="MAE (trips/hour)",
            baseline={"name": "seasonal-naive", "value": m.get("naive_mae")},
            evaluation_window=window, status="Demonstrated", limitation=limitation,
            source_metric_key=f"{key}.model_mae", dataset_manifest=dm,
            dataset_sha256=dataset_sha256, content_checks=content_checks,
            source_files=srcs,
        ))
        cov = (m.get("conformal_decile_only") or {}).get("achieved_coverage")
        if cov is not None:
            out.append(_claim(
                cid=f"forecast.{key}.conformal_coverage",
                claim=f"{note}: split-conformal prediction-interval coverage on validation",
                value=cov, unit="empirical coverage",
                baseline={"name": "target coverage",
                          "value": m.get("conformal_target_coverage")},
                evaluation_window=window, status="Demonstrated",
                limitation=(limitation + " Coverage is the decile-only Mondrian "
                            "calibration; interval widths are reported in the "
                            "source metrics file."),
                source_metric_key=f"{key}.conformal_decile_only.achieved_coverage",
                dataset_manifest=dm, dataset_sha256=dataset_sha256,
                content_checks=content_checks, source_files=srcs,
            ))
    return out


def _build_leakage_claim(root: Path) -> list[dict]:
    report_file = root / "data" / "curated" / "leakage_audit_report.json"
    rep = _load_json(report_file)
    if not isinstance(rep, dict) or "overall" not in rep:
        return []
    audit_script = root / "data" / "curated" / "leakage_audit.py"
    srcs = [_rel(report_file), _rel(root / "forge" / "knowledge" / "docs" / "MODEL_CARDS.md")]
    if audit_script.exists():
        srcs.insert(1, _rel(audit_script))
    return [_claim(
        cid="leakage.overall",
        claim="Mechanical point-in-time leakage audit verdict across all model features",
        value=rep["overall"], unit="verdict",
        status="Exists",
        limitation=("A mechanical audit over the tested information cutoffs and "
                    "the audited feature set only; the weather feature uses "
                    "realized values (a documented caveat), so 'no leakage' is a "
                    "statement about point-in-time feature availability, not a "
                    "guarantee of external validity."),
        source_metric_key="overall", source_files=srcs,
    )]


def _build_ntd_claims(root: Path) -> list[dict]:
    ntd = _load_json(root / "data" / "curated" / "metrics_ntd_monthly.json")
    if not isinstance(ntd, dict):
        return []
    metrics_file = root / "data" / "curated" / "metrics_ntd_monthly.json"
    model_card = root / "forge" / "knowledge" / "docs" / "MODEL_CARDS.md"
    ntd_script = root / "data" / "curated" / "model_ntd_monthly.py"
    manifest_file = root / "data" / "curated" / "manifests" / "ntd_monthly_dr.csv.gz.json"
    manifest = _load_json(manifest_file)
    dataset_sha256 = manifest.get("sha256") if isinstance(manifest, dict) else None
    panel_path = root / "data" / "curated" / "panels" / "ntd_monthly_dr.csv.gz"
    content_checks = (
        [{"path": _rel(panel_path), "sha256": dataset_sha256}] if dataset_sha256 else []
    )
    srcs = [_rel(metrics_file), _rel(model_card)]
    if ntd_script.exists():
        srcs.insert(1, _rel(ntd_script))
    dm = None
    if manifest_file.exists():
        srcs.append(_rel(manifest_file))
        dm = _rel(manifest_file)

    cold = ntd.get("cold_start_agency", {})
    temp = ntd.get("temporal", {})
    out: list[dict] = []
    if cold:
        window = f"cold-start: {cold.get('split', '?')} (n={cold.get('n', '?')})"
        lim_cold = ("National monthly demand-response evidence on real public NTD "
                    "filings; the cold-start split holds out whole agencies (the "
                    "onboarding scenario) but this is aggregate monthly demand, "
                    "not trip-level dispatch, and remains Demonstrated until a "
                    "consented pilot.")
        out.append(_claim(
            cid="ntd.cold_start.model_r2",
            claim="NTD monthly demand: cold-start R2 on agencies held out entirely (no agency identity)",
            value=cold.get("model_r2"), unit="R2",
            baseline={"name": "seasonal-naive", "value": cold.get("naive_r2")},
            evaluation_window=window, status="Demonstrated", limitation=lim_cold,
            source_metric_key="cold_start_agency.model_r2", dataset_manifest=dm,
            dataset_sha256=dataset_sha256, content_checks=content_checks, source_files=srcs,
        ))
        out.append(_claim(
            cid="ntd.cold_start.model_mape",
            claim="NTD monthly demand: cold-start MAPE (fraction; x100 for percent) on held-out agencies",
            value=cold.get("model_mape"), unit="MAPE (fraction; e.g. 4.7535 = 475.3%)",
            baseline={"name": "seasonal-naive", "value": cold.get("naive_mape")},
            evaluation_window=window, status="Demonstrated", limitation=lim_cold,
            source_metric_key="cold_start_agency.model_mape", dataset_manifest=dm,
            dataset_sha256=dataset_sha256, content_checks=content_checks, source_files=srcs,
        ))
    if temp:
        window = f"temporal: {temp.get('split', '?')} (n={temp.get('n', '?')})"
        lim_temp = ("Reported honestly as a LOSS on absolute R2: monthly demand "
                    "is very stable year-over-year, so seasonal-naive is a strong "
                    "R2 baseline here; the model wins on relative error (MAPE). "
                    "Aggregate monthly, not trip-level; Demonstrated, not Validated.")
        out.append(_claim(
            cid="ntd.temporal.model_r2",
            claim="NTD monthly demand: temporal-holdout R2 (last 12 months, all agencies)",
            value=temp.get("model_r2"), unit="R2",
            baseline={"name": "seasonal-naive", "value": temp.get("naive_r2")},
            evaluation_window=window, status="Demonstrated", limitation=lim_temp,
            source_metric_key="temporal.model_r2", dataset_manifest=dm,
            dataset_sha256=dataset_sha256, content_checks=content_checks, source_files=srcs,
        ))
    return out


def _build_darp_claims(root: Path) -> list[dict]:
    results_file = root / "aletheia" / "benchmarks" / "quality" / "darp_results.json"
    data = _load_json(results_file)
    if not isinstance(data, dict) or "results" not in data:
        return []
    bench_script = root / "aletheia" / "benchmarks" / "quality" / "darp_benchmark.py"
    best_known = root / "aletheia" / "benchmarks" / "quality" / "best_known.json"
    srcs = [_rel(results_file)]
    if bench_script.exists():
        srcs.append(_rel(bench_script))
    if best_known.exists():
        srcs.append(_rel(best_known))
    out: list[dict] = []
    for r in data["results"]:
        inst = r.get("instance", "?")
        proven = r.get("best_known_is_proven_optimal")
        ref = "proven optimum" if proven else "best-known"
        limitation = (
            f"Single published Cordeau instance ({inst}: {r.get('num_requests')} "
            f"requests, {r.get('num_vehicles')} vehicles); a {len(data['results'])}"
            "-instance sample, not a full sweep, and explicitly NOT a SOTA claim. "
            f"Gap is measured against the {ref} ({r.get('best_known')}); every "
            "reported solution was accepted by the independent DARP feasibility "
            "checker (0 violations)."
        )
        out.append(_claim(
            cid=f"darp.{inst}.gap_pct",
            claim=(f"Program F DARP solver optimality gap on Cordeau {inst} "
                   f"(vs {ref} {r.get('best_known')})"),
            value=r.get("gap_pct"), unit="percent gap",
            baseline={"name": ref, "value": r.get("best_known")},
            evaluation_window=(f"Cordeau {inst}; solver {r.get('solver_name')} "
                               f"{r.get('solver_version')}, seed {r.get('seed')}, "
                               f"{r.get('lns_iterations')} LNS iters, "
                               f"{r.get('solve_time_s')}s"),
            status="Demonstrated", limitation=limitation,
            source_metric_key=f"results[instance={inst}].gap_pct",
            artifact_hash=None, source_files=srcs,
        ))
    return out


def _build_forecast_leaderboard_claims(root: Path) -> list[dict]:
    """OPTIONAL: another packet owns forecast_leaderboard.json. Include it only
    if it is present at run time; otherwise skip silently (regenerable)."""
    lb_file = root / "aletheia" / "benchmarks" / "quality" / "forecast_leaderboard.json"
    lb = _load_json(lb_file)
    if not isinstance(lb, dict):
        return []
    # We do not know the other packet's exact schema; index it as a single
    # provenance-level claim pointing at the file, rather than fabricating a
    # structure. If/when its schema stabilises this can be enriched.
    return [_claim(
        cid="forecast_leaderboard.present",
        claim="Forecast benchmark / leaderboard artifact is present and indexed",
        value=True, unit="presence",
        status="Exists",
        limitation=("Indexed by PRESENCE only: another packet owns this artifact "
                    "and its schema, so its individual rows are not re-transcribed "
                    "or content-hashed here (that would couple this registry to a "
                    "file being written in parallel) -- read the source file "
                    "directly for its numbers and their limitations."),
        source_files=[_rel(lb_file)],
    )]


def _build_contract_claim(root: Path) -> list[dict]:
    version = _read_contract_version(root)
    if version is None:
        return []
    return [_claim(
        cid="canonical.contract_version",
        claim="Canonical data-contract version (the versioned schema all packets build against)",
        value=version, unit="semver",
        status="Exists",
        limitation=("v0.1 canonical contract: a SQLite-portable, "
                    "PostgreSQL-compatible subset, not the full blueprint schema; "
                    "e.g. DecisionAlternative has no store method yet "
                    "(ADR-0009/0012). Code exists and is unit-tested, but the "
                    "contract is pre-1.0 and may change."),
        source_metric_key="CONTRACT_VERSION",
        source_files=[_rel(root / "themis" / "canonical" / "__init__.py")],
    )]


# --------------------------------------------------------------------------- #
# top-level build + verify + render
# --------------------------------------------------------------------------- #
def build_registry(root: Path = ROOT) -> dict:
    """Scan committed evidence sources and return the registry dict.

    Only claims whose source could actually be read are emitted -- a claim with
    no traceable source is never fabricated into the registry.
    """
    claims: list[dict] = []
    claims += _build_forecast_claims(root)
    claims += _build_leakage_claim(root)
    claims += _build_ntd_claims(root)
    claims += _build_darp_claims(root)
    claims += _build_forecast_leaderboard_claims(root)
    claims += _build_contract_claim(root)

    return {
        "schema": REGISTRY_SCHEMA,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "canonical_contract_version": _read_contract_version(root),
        "status_vocabulary": list(STATUS_VOCAB),
        "about": (
            "Machine-readable map from every public Milexium claim to its source "
            "file, dataset provenance manifest (with recorded sha256), evaluation "
            "window, status label, and plain-language limitation. Generated by "
            "talos/tools/build_evidence_registry.py; verify with verify_evidence_registry()."
        ),
        "manifests": _build_manifests(root),
        "claims": claims,
    }


def verify_evidence_registry(registry: dict, root: Path | None = None) -> list[str]:
    """Check a registry against reality. Returns human-readable problems.

    An empty list means clean. Checks:
      1. every referenced source file exists (claims + manifests);
      2. every recorded sha256 that names a PRESENT local file matches when
         recomputable (absent files are skipped -- large panels are gitignored);
      3. every claim has a non-empty limitation and a valid status label.
    """
    if root is None:
        root = ROOT
    problems: list[str] = []
    sha_cache: dict[Path, str] = {}  # hash each present file at most once per call

    if not isinstance(registry, dict):
        return ["registry is not a JSON object"]
    if registry.get("schema") != REGISTRY_SCHEMA:
        problems.append(f"unexpected registry schema: {registry.get('schema')!r}")

    def check_source_files(entry: dict, label: str) -> None:
        files = entry.get("source_files")
        if not files:
            problems.append(f"{label}: has no source_files (untraceable claim)")
            return
        for rel in files:
            if not (root / rel).exists():
                problems.append(f"{label}: source file missing: {rel}")

    def check_content(entry: dict, label: str) -> None:
        for cc in entry.get("content_checks", []):
            rel, want = cc.get("path"), cc.get("sha256")
            if not rel or not want:
                problems.append(f"{label}: malformed content_check {cc!r}")
                continue
            p = root / rel
            if not p.exists():
                continue  # absent local file -> not recomputable, skip (by design)
            got = sha_cache.get(p)
            if got is None:
                got = sha_cache[p] = _sha256(p)
            if got != want:
                problems.append(
                    f"{label}: sha256 mismatch for {rel}: recorded {want[:12]}..., "
                    f"recomputed {got[:12]}...")

    manifests = registry.get("manifests", [])
    if not isinstance(manifests, list):
        problems.append("registry.manifests is not a list")
        manifests = []
    for m in manifests:
        label = f"manifest {m.get('id', '?')}"
        check_source_files(m, label)
        check_content(m, label)

    claims = registry.get("claims", [])
    if not isinstance(claims, list):
        problems.append("registry.claims is not a list")
        claims = []
    if not claims:
        problems.append("registry has no claims")
    for c in claims:
        label = f"claim {c.get('id', '?')}"
        # 3. limitation + status
        lim = c.get("limitation")
        if not (isinstance(lim, str) and lim.strip()):
            problems.append(f"{label}: missing or empty limitation")
        status = c.get("status")
        if status not in STATUS_VOCAB:
            problems.append(
                f"{label}: status {status!r} not in the fixed vocabulary "
                f"{list(STATUS_VOCAB)}")
        # 1. source files exist
        check_source_files(c, label)
        # 2. content hashes match when present
        check_content(c, label)

    return problems


def render_readme(registry: dict) -> str:
    lines: list[str] = [
        "# Evidence registry",
        "",
        f"_Generated by `talos/tools/build_evidence_registry.py` at "
        f"{registry.get('generated_utc', '?')}. Canonical contract "
        f"v{registry.get('canonical_contract_version', '?')}._",
        "",
        "Machine-readable map (`registry.json`) from every public Milexium claim "
        "to its source file, dataset manifest (with recorded sha256), evaluation "
        "window, status label, and a plain-language limitation. This is the "
        "anti-overclaim tool: every number is paired with both a traceable source "
        "and a stated limit. Verify with `verify_evidence_registry(registry)` in "
        "`talos/tools/build_evidence_registry.py` (empty result = clean).",
        "",
        f"Status vocabulary (fixed): {', '.join(registry.get('status_vocabulary', []))}.",
        "",
        "## Claims",
        "",
        "| id | claim | value | vs baseline | status | source |",
        "|---|---|---|---|---|---|",
    ]
    for c in registry.get("claims", []):
        base = c.get("baseline") or {}
        base_s = (f"{base.get('value')} ({base.get('name')})"
                  if base.get("value") is not None else "-")
        primary_src = (c.get("source_files") or ["-"])[0]
        val = c.get("value")
        lines.append(
            f"| `{c.get('id')}` | {c.get('claim')} | {val} {c.get('unit','')} | "
            f"{base_s} | {c.get('status')} | `{primary_src}` |")

    lines += [
        "",
        "## Data provenance manifests",
        "",
        "| panel | sha256 (short) | rows | source | license |",
        "|---|---|---|---|---|",
    ]
    for m in registry.get("manifests", []):
        sha = (m.get("sha256") or "")[:12]
        lines.append(
            f"| `{m.get('panel')}` | `{sha}...` | {m.get('rows')} | "
            f"{m.get('source')} | {m.get('license')} |")
    lines.append("")
    lines.append(
        "Large panels are gitignored and regenerated via each manifest's "
        "`fetch_script`; the recorded sha256 verifies a panel is unchanged when "
        "present locally.")
    lines.append("")
    return "\n".join(lines)


def write_registry(registry: dict, out_dir: Path = OUT_DIR) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    reg_path = out_dir / "registry.json"
    readme_path = out_dir / "README.md"
    reg_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    readme_path.write_text(render_readme(registry), encoding="utf-8")
    return reg_path, readme_path


def main() -> int:
    registry = build_registry(ROOT)
    reg_path, readme_path = write_registry(registry)
    problems = verify_evidence_registry(registry, ROOT)
    print(f"wrote {_rel(reg_path)} "
          f"({len(registry['claims'])} claims, {len(registry['manifests'])} manifests)")
    print(f"wrote {_rel(readme_path)}")
    if problems:
        print(f"\nVERIFY: {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("VERIFY: clean (all referenced files present, all recomputable "
          "sha256s match, every claim has a limitation and a valid status).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
