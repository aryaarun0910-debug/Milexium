"""Independent JSON-Schema verifier.

Validates raw dict payloads with the `jsonschema` library directly against
the schema exported from a Pydantic model, rather than asking that same
Pydantic model to `model_validate` its own output -- a bug in a Pydantic
custom validator would not be caught by re-running the exact same validator.
"""

from __future__ import annotations

from typing import Any

import jsonschema


def export_schema(model: type) -> dict:
    """The JSON Schema contract for a canonical entity. Also written to
    architecture/contracts/ as the versioned, reviewable artifact -- this
    function is what produced that file, not a second hand-maintained copy.
    """
    return model.model_json_schema()


def verify_against_schema(instance: dict[str, Any], model: type) -> list[str]:
    """Returns human-readable error strings; an empty list means valid."""
    schema = export_schema(model)
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    return [
        f"{'/'.join(str(p) for p in error.path) or '<root>'}: {error.message}"
        for error in validator.iter_errors(instance)
    ]
