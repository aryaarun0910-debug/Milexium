"""Regenerate the language-neutral contract artifacts from the Python source
of truth (contracts-first, per ADR-0026).

Today the Pydantic canonical models and the FastAPI app ARE the authoritative
contract source; this script derives the portable artifacts from them so they
cannot drift:

- talos/contracts/jsonschema/canonical-v0.1.json  -- the 12 canonical entities
- talos/contracts/openapi/milexium-api-v0.1.json  -- the public HTTP surface

Protobuf (talos/contracts/proto/) + Buf codegen for Rust/TS/Python clients is the
next step, deferred until the buf/protoc toolchain is installed (ADR-0026);
the .proto seed is hand-maintained until then. Run:  py -3 talos/contracts/generate.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the repo root importable when run standalone (pytest sets this via
# pyproject's pythonpath, a bare `py -3 talos/contracts/generate.py` does not).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from themis.canonical import (
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
    StopTimeObservation,
    Tenant,
    Vehicle,
    VehicleObservation,
)
from themis.canonical import CONTRACT_VERSION

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
    # Request-independent operational/telemetry family (ADR-0035). Exported to
    # the contract layer because external producers (GTFS-Realtime and every
    # AVL source like it) map onto these, not onto the rider-request entities.
    "VehicleObservation": VehicleObservation,
    "StopTimeObservation": StopTimeObservation,
    "OutboxEntry": OutboxEntry,
}


def write_jsonschema() -> Path:
    out = {
        "contract_version": CONTRACT_VERSION,
        "generated_by": "talos/contracts/generate.py from themis.canonical (Pydantic source of truth)",
        "note": "Generated. Do not hand-edit -- change themis/canonical and regenerate.",
        "entities": {name: model.model_json_schema() for name, model in _ENTITIES.items()},
    }
    path = _HERE / "jsonschema" / "canonical-v0.1.json"
    path.write_text(newline="\n", data=json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    return path


def write_openapi() -> Path | None:
    try:
        from argus.api.app import create_app
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
    print(f"wrote {js.relative_to(_HERE.parents[1])} ({len(_ENTITIES)} entities)")
    oa = write_openapi()
    if oa is not None:
        print(f"wrote {oa.relative_to(_HERE.parents[1])}")
