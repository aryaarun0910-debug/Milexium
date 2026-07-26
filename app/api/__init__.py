"""Program M (v0.1 HTTP surface): the Milexium HTTP/OpenAPI API.

A FastAPI backend over `app.sdk.MilexiumClient` that lets non-Python
software integrate the decision loop. This is an API package, not a website:
it serves JSON and an OpenAPI schema, no rendered pages.

Public surface:

    from app.api import app                # the ASGI app (uvicorn app.api:app)
    from app.api import create_app         # build a fresh app over an injected client
    from app.api import in_memory_client   # the demo store-backing seam

The machine-readable API contract is the OpenAPI document FastAPI serves at
`/openapi.json` (browsable at `/docs`). See `app.api.app` for the endpoint
set and the explicit v0.1 scope boundaries (no ingestion/forecast over HTTP; no
auth/multi-tenant gateway/rate limiting -- all Specified).

Beyond the decision loop the app exposes the two capabilities an integrator
actually asks for by name: `POST /teardowns` (the deadhead teardown, ADR-0039)
and `POST /operator-exports/validate` (a dry-run intake check on an export
sample that stores nothing, ADR-0038). `app.api.app` records why those two
map honestly onto HTTP when ingestion still does not.
"""

from app.api.app import app, create_app, in_memory_client

__all__ = ["app", "create_app", "in_memory_client"]

__version__ = "0.1.0"
