# ADR-0010: Placeholder tenant for platform-trained models in the model registry

- **Status:** Accepted (provisional — flagged for revisit)
- **Date:** 2026-07-23

## Context

`themis/canonical/entities.py`'s `ModelVersion` requires `tenant_id` (Program
A's contract: "Tenant ID on every operational record," per
`blueprint/10-security-privacy-and-ai-governance.md`). The five real, trained,
evaluated models this repository has (`forge/knowledge/docs/MODEL_CARDS.md`) are trained once
on public aggregate data (AAR, Chicago TNP, MTA bus/subway, NTD monthly) —
none is tied to a specific consented operator tenant; none is a paying
customer's own model.

## Decision

`aletheia/conformance/fixtures/model_registry_builders.py` mints one shared placeholder
`TenantId` (`reference_tenant_id()`) for all five registered `ModelVersion`
fixtures, rather than either (a) inventing a fake named customer, or (b)
changing the canonical contract to make `tenant_id` optional.

This is accepted as a **stopgap for the model-registry v0.1 fixture layer
only** — it has not been used anywhere a real operator tenant is implied, and
must not be copied into product code that presents these models as belonging
to any actual customer.

## Consequences

- **This is flagged, not resolved.** Program D's full scope will need a real
  answer to "how does a platform-wide model (not owned by any one tenant) fit
  a contract where every record carries a mandatory tenant_id?" Two candidate
  resolutions for a future ADR, not decided here:
  1. A reserved, well-known "platform" tenant convention (a specific `TenantId`
     value meaning "not customer-specific"), or
  2. Loosening `ModelVersion.tenant_id` to `TenantId | None` specifically
     (and only) for this entity, with `None` meaning platform-trained.
- Until one of those is decided, do not read the placeholder tenant id used in
  `model_registry_builders.py` as meaningful — it is a random value with no
  significance beyond satisfying the mandatory field for test fixtures.
- `champion()`/`promote()` in `themis/core/model_registry.py` operate
  per-task, not per-tenant, so this gap does not currently block the
  registry's own behavior — it only affects how these five specific
  `ModelVersion` records should eventually be labeled.
