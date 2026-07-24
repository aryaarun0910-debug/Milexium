/**
 * `@milexium/sdk` -- typed TypeScript client for the Milexium HTTP API.
 *
 * Public surface: the {@link MilexiumClient} class, its options and error type,
 * and the request/response types (all derived from the OpenAPI contract via
 * `src/generated/openapi.ts`). The raw generated `paths`/`components` are
 * re-exported under `openapi` for callers who want the full contract types.
 */
export { MilexiumClient, MilexiumApiError } from "./client.ts";
export type { MilexiumClientOptions } from "./client.ts";

export type {
  Schemas,
  HealthResponse,
  VersionResponse,
  RecordedEvent,
  EvidencePacket,
  EvidencePack,
  VerifyResponse,
  RecordDecisionRequest,
  RecordOverrideRequest,
  RecordDecisionInput,
  RecordOverrideInput,
  ReasonCode,
  DecisionEvent,
  DecisionEventType,
  DecisionAlternative,
  KnownInput,
  Outcome,
  PackManifest,
  ChainViolation,
  StateViolation,
  VerifyViolation,
  HTTPValidationError,
} from "./types.ts";

export type * as openapi from "./generated/openapi.ts";
