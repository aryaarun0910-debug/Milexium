"""Program M (first slice): the Milexium Python SDK facade.

This module is the **stable public surface** of the SDK. Import from here:

    from packages.sdk import MilexiumClient

    client = MilexiumClient.in_memory(tenant_name="Demo Mobility Co")
    summary = client.ingest(adapter, rows)          # Connect
    client.record_decision(aggregate_id=..., payload=...)   # decide
    client.record_override(aggregate_id=..., actor_id=..., payload=...)
    packet = client.evidence_for(aggregate_id)      # evidence, verified
    client.teardown_deadhead(segments, ...)         # where the empty time sat

Everything under `packages.sdk` other than the names re-exported below is
internal and may change without notice. This is a composition/facade layer: it
lets an external developer drive the whole loop without knowing which internal
package (`canonical`, `connect`, `evidence`, `verify`) each capability lives in.
It adds no new domain logic.

The HTTP/OpenAPI surface over this same client lives in a separate package,
`packages.api` (a FastAPI backend), so non-Python software can integrate the
loop. Still Specified (all per blueprint/08-sdk-api-and-developer-experience.md):
the CLI, plugin certification, auth, the multi-tenant API gateway, and the
TypeScript/Rust SDKs. The value here is narrow and honest -- one import, one
client, the whole loop reachable, including `forecast`, `export_pack` and
`teardown_deadhead`.

Not wired into a top-level `packages/__init__.py`; import directly as above.
"""

from packages.sdk.client import IngestSummary, MilexiumClient

__all__ = [
    "MilexiumClient",
    "IngestSummary",
]

__version__ = "0.1.0"
CONTRACT_VERSION = "0.1.0"
