"""The OpenAPI contract drift gate, runnable locally instead of only on CI.

`platform/contracts/openapi/milexium-api-v0.1.json` is generated from `app/api/app.py`
by `platform/contracts/generate.py`, and `app/sdk-typescript/src/generated/openapi.ts`
is generated from that JSON. Both links have a CI gate ("regenerate, then
`git diff --exit-code`"), and the second one was only added after the generated
TypeScript client had silently gone 835 lines stale while two endpoints landed.

A gate that lives exclusively in `.github/workflows/ci.yml` has one structural
weakness, and it is the same one that let the drift happen: **nothing on a
developer's machine evaluates it.** You learn after you push. This file moves
the first link's check into `pytest`, where a change to `app/api/app.py`
that forgets the regeneration step fails immediately and locally.

It is NOT a replacement for the CI gate and does not try to be:

- CI compares BYTES after regenerating, so it also catches formatting drift and
  a bumped generator version. This compares parsed JSON, so it is blind to
  those and immune to whitespace.
- CI can fail the build. This can only fail a test.
- The TypeScript link has its own local half in
  `app/sdk-typescript/test/generated-drift.test.ts`.

Deliberately, this file WRITES NOTHING. `platform/contracts/generate.py` regenerates the
file on disk; a test that did that would repair the drift it is supposed to
report and pass for the wrong reason.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.api.app import API_VERSION, create_app

_REPO = Path(__file__).resolve().parents[3]
_SPEC = _REPO / "platform" / "contracts" / "openapi" / "milexium-api-v0.1.json"


def _committed() -> dict:
    return json.loads(_SPEC.read_text(encoding="utf-8"))


def _served() -> dict:
    # json round-trip so tuples/enums are compared in the form generate.py
    # actually serialises, not in their in-memory Python form.
    return json.loads(json.dumps(create_app().openapi(), sort_keys=True))


def test_the_committed_openapi_contract_is_a_real_document() -> None:
    """Guards every assertion below: an empty or missing file would make the
    equality test below pass over nothing on both sides."""
    spec = _committed()
    assert spec["info"]["version"] == API_VERSION
    assert len(spec["paths"]) >= 9
    assert "/teardowns" in spec["paths"]
    assert "TeardownRequest" in spec["components"]["schemas"]


def test_the_committed_openapi_contract_matches_what_the_app_serves() -> None:
    """The drift gate itself. If this fails, run:

        py -3 platform/contracts/generate.py
        npm run generate -w @milexium/sdk

    and commit both. The second command is not optional -- the TypeScript types
    are generated from the file the first command writes, and skipping it is
    exactly how they went 835 lines stale.
    """
    committed, served = _committed(), _served()

    assert sorted(committed["paths"]) == sorted(served["paths"]), (
        "the endpoint SET drifted -- an endpoint was added or removed in "
        "app/api/app.py without regenerating platform/contracts/"
    )
    assert sorted(committed["components"]["schemas"]) == sorted(
        served["components"]["schemas"]
    ), "the schema SET drifted"
    assert committed == served, (
        "platform/contracts/openapi/milexium-api-v0.1.json is stale -- regenerate it "
        "(py -3 platform/contracts/generate.py) and then the TypeScript types "
        "(npm run generate -w @milexium/sdk)"
    )


def test_the_generated_typescript_covers_every_path_in_the_contract() -> None:
    """The second link, checked from the Python side too.

    `app/sdk-typescript/test/generated-drift.test.ts` asserts this properly
    (and more), but it only runs if someone runs the Node suite. The historical
    failure was a TypeScript artifact going stale while only Python was being
    run, so the cheap cross-language duplicate earns its place here."""
    generated = (
        _REPO / "app" / "sdk-typescript" / "src" / "generated" / "openapi.ts"
    ).read_text(encoding="utf-8")
    assert len(generated) > 10_000

    missing = [path for path in _committed()["paths"] if f'"{path}": {{' not in generated]
    assert missing == [], (
        f"generated TypeScript types are stale, missing {missing} -- "
        "run 'npm run generate -w @milexium/sdk' and commit"
    )
