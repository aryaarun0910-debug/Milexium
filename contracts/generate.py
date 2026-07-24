"""Regenerate the language-neutral contract artifacts from the Python source
of truth (contracts-first, per ADR-0026).

Today the Pydantic canonical models and the FastAPI app ARE the authoritative
contract source; this script derives the portable artifacts from them so they
cannot drift:

- contracts/jsonschema/canonical-v0.1.json  -- the 12 canonical entities
- contracts/openapi/milexium-api-v0.1.json  -- the public HTTP surface

Protobuf (contracts/proto/) + Buf codegen for Rust/TS/Python clients is the
next step, deferred until the buf/protoc toolchain is installed (ADR-0026);
the .proto seed is hand-maintained until then. Run:  py -3 contracts/generate.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the repo root importable when run standalone (pytest sets this via
# pyproject's pythonpath, a bare `py -3 contracts/generate.py` does not).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packages.canonical import (
    DecisionAlternative,
    DecisionEvent,
    Driver,
    ForecastVintage,
    ModelVersion,
    Outcome,
    OutboxEntry,
    Policy,
    ScheduleRun,
    ServiceRequest,
    Tenant,
    Vehicle,
)
from packages.canonical import CONTRACT_VERSION

_HERE = Path(__file__).parent
_ENTITIES = {
    "Tenant": Tenant,
    "ServiceRequest": ServiceRequest,
    "Vehicle": Vehicle,
    "Driver": Driver,
    "Policy": Policy,
    "ModelVersion": ModelVersion,
    "ForecastVintage": ForecastVintage,
    "ScheduleRun": ScheduleRun,
    "DecisionAlternative": DecisionAlternative,
    "DecisionEvent": DecisionEvent,
    "Outcome": Outcome,
    "OutboxEntry": OutboxEntry,
}


def write_jsonschema() -> Path:
    out = {
        "contract_version": CONTRACT_VERSION,
        "generated_by": "contracts/generate.py from packages.canonical (Pydantic source of truth)",
        "note": "Generated. Do not hand-edit -- change packages/canonical and regenerate.",
        "entities": {name: model.model_json_schema() for name, model in _ENTITIES.items()},
    }
    path = _HERE / "jsonschema" / "canonical-v0.1.json"
    path.write_text(newline="\n", data=json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    return path


def write_openapi() -> Path | None:
    try:
        from packages.api.app import create_app
    except Exception as exc:  # noqa: BLE001 -- API is optional at contract-gen time
        print(f"  (skipped OpenAPI: {exc})")
        return None
    app = create_app()
    spec = app.openapi()
    path = _HERE / "openapi" / "milexium-api-v0.1.json"
    path.write_text(newline="\n", data=json.dumps(spec, indent=2, sort_keys=True), encoding="utf-8")
    return path


if __name__ == "__main__":
    js = write_jsonschema()
    print(f"wrote {js.relative_to(_HERE.parent)} ({len(_ENTITIES)} entities)")
    oa = write_openapi()
    if oa is not None:
        print(f"wrote {oa.relative_to(_HERE.parent)}")
