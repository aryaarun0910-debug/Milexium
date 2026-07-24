/**
 * MilexiumClient: a thin, typed wrapper over `fetch` for the Milexium HTTP API.
 *
 * Every method mirrors one endpoint of the OpenAPI contract one-to-one, and
 * every request/response type is imported from `./types.ts` (which derives them
 * from the generated `src/generated/openapi.ts`). The client adds no domain
 * logic: it builds a request, calls `fetch`, and parses JSON.
 */
import type {
  EvidencePack,
  EvidencePacket,
  HealthResponse,
  RecordDecisionInput,
  RecordOverrideInput,
  RecordedEvent,
  VerifyResponse,
  VersionResponse,
} from "./types.ts";

/** Options for constructing a {@link MilexiumClient}. */
export interface MilexiumClientOptions {
  /** Base URL of the API, e.g. `http://localhost:8000`. A trailing slash is
   * tolerated. */
  baseUrl: string;
  /** `fetch` implementation to use. Defaults to the global `fetch` (Node 18+,
   * all modern browsers). Injectable so tests can supply a mock. */
  fetch?: typeof fetch;
  /** Extra headers sent on every request (e.g. an auth token once the API
   * gateway exists). */
  headers?: Record<string, string>;
}

/** Thrown when the API responds with a non-2xx status. `body` is the parsed
 * JSON error payload when the response had one (e.g. an `HTTPValidationError`),
 * otherwise the raw text or `undefined`. */
export class MilexiumApiError extends Error {
  readonly status: number;
  readonly url: string;
  readonly body: unknown;

  constructor(status: number, url: string, body: unknown) {
    super(`Milexium API request to ${url} failed with HTTP ${status}`);
    this.name = "MilexiumApiError";
    this.status = status;
    this.url = url;
    this.body = body;
  }
}

export class MilexiumClient {
  readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly baseHeaders: Record<string, string>;

  constructor(options: MilexiumClientOptions) {
    // Normalise: drop a single trailing slash so `${baseUrl}${path}` is clean.
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.fetchImpl = options.fetch ?? globalThis.fetch;
    this.baseHeaders = { ...options.headers };
    if (typeof this.fetchImpl !== "function") {
      throw new TypeError(
        "No fetch implementation available; pass `fetch` in MilexiumClientOptions.",
      );
    }
  }

  /** `GET /health` -- liveness probe. */
  health(): Promise<HealthResponse> {
    return this.request<HealthResponse>("GET", "/health");
  }

  /** `GET /version` -- API / SDK / contract versions. */
  version(): Promise<VersionResponse> {
    return this.request<VersionResponse>("GET", "/version");
  }

  /** `POST /decisions` -- record a RECOMMENDATION (a system act). */
  recordDecision(body: RecordDecisionInput): Promise<RecordedEvent> {
    return this.request<RecordedEvent>("POST", "/decisions", body);
  }

  /** `POST /decisions/{aggregate_id}/overrides` -- record an OVERRIDE (a human
   * act). `aggregateId` travels in the path; the body carries the rest. */
  recordOverride(
    aggregateId: string,
    body: RecordOverrideInput,
  ): Promise<RecordedEvent> {
    return this.request<RecordedEvent>(
      "POST",
      `/decisions/${encodeURIComponent(aggregateId)}/overrides`,
      body,
    );
  }

  /** `GET /decisions/{aggregate_id}/evidence` -- the reconstructed
   * EvidencePacket for one aggregate. */
  evidence(aggregateId: string): Promise<EvidencePacket> {
    return this.request<EvidencePacket>(
      "GET",
      `/decisions/${encodeURIComponent(aggregateId)}/evidence`,
    );
  }

  /** `GET /decisions/{aggregate_id}/evidence-pack` -- the portable,
   * self-verifying EvidencePack for one aggregate. */
  evidencePack(aggregateId: string): Promise<EvidencePack> {
    return this.request<EvidencePack>(
      "GET",
      `/decisions/${encodeURIComponent(aggregateId)}/evidence-pack`,
    );
  }

  /** `GET /decisions/{aggregate_id}/verify` -- independent hash-chain check. */
  verify(aggregateId: string): Promise<VerifyResponse> {
    return this.request<VerifyResponse>(
      "GET",
      `/decisions/${encodeURIComponent(aggregateId)}/verify`,
    );
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const headers: Record<string, string> = { accept: "application/json", ...this.baseHeaders };
    const init: { method: string; headers: Record<string, string>; body?: string } = {
      method,
      headers,
    };
    if (body !== undefined) {
      headers["content-type"] = "application/json";
      init.body = JSON.stringify(body);
    }

    const response = await this.fetchImpl(url, init);
    const text = await response.text();
    const parsed: unknown = text.length > 0 ? JSON.parse(text) : undefined;

    if (!response.ok) {
      throw new MilexiumApiError(response.status, url, parsed);
    }
    return parsed as T;
  }
}
