import type {
  Audience,
  Profile,
  Replay,
  ServiceError,
  SnapshotResult,
  ViewerSession,
} from "./types.ts";

export type Fetcher = (
  input: string,
  init: RequestInit,
) => Promise<Pick<Response, "ok" | "status" | "json">>;
interface RequestOptions {
  body?: unknown;
  method?: string;
  signal?: AbortSignal;
  base?: string;
}
interface ErrorBody {
  detail?: unknown;
  message?: unknown;
  error?: unknown;
  code?: unknown;
}

/** Same-origin application boundary. No provider or database access in the client. */
export class MatchApi {
  fetcher: Fetcher;
  base: string;
  constructor(
    fetcher: Fetcher = (...args) => globalThis.fetch(...args),
    base = "/viewer-api",
  ) {
    this.fetcher = fetcher;
    this.base = base;
  }
  /** Response bodies are typed by the backend contract; callers narrow live snapshots. */
  async request<T = unknown>(
    path: string,
    { body, method, signal, base = this.base }: RequestOptions = {},
  ): Promise<T> {
    const response = await this.fetcher(`${base}${path}`, {
      method: method || (body === undefined ? "GET" : "POST"),
      headers: { "Content-Type": "application/json" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: signal || AbortSignal.timeout(75000),
    });
    let data: unknown;
    try {
      data = await response.json();
    } catch {
      const error: ServiceError = new Error(response.status >= 500
        ? "The match service is temporarily unavailable. Please try again shortly."
        : "The match service returned an invalid response. Please try again.");
      error.status = response.status;
      throw error;
    }
    if (!response.ok) {
      const body = data as ErrorBody;
      const detail = body.detail || body.message || body.error;
      const error: ServiceError = new Error(
        typeof detail === "string"
          ? detail
          : "The match service could not complete that request.",
      );
      error.code = body.code;
      error.status = response.status;
      throw error;
    }
    return data as T;
  }
  profiles() {
    return this.request<{ profiles: Profile[] }>("/profiles");
  }
  session(profileId: string) {
    return this.request<ViewerSession>("/sessions", { body: { profile_id: profileId } });
  }
  restore(token: string) {
    return this.request<ViewerSession>(`/${encodeURIComponent(token)}`);
  }
  audience(token: string, selection: Audience) {
    return this.request<SnapshotResult>(`/${encodeURIComponent(token)}/audience`, {
      method: "PUT", body: selection,
    });
  }
  ask(token: string, prompt: string, requestId: string) {
    return this.request(`/${encodeURIComponent(token)}/messages`, {
      body: { prompt, request_id: requestId },
    });
  }
  track(token: string, id: string) {
    return this.request<SnapshotResult>(
      `/${encodeURIComponent(token)}/offers/${encodeURIComponent(id)}/track`,
      { body: {} },
    );
  }
  unpin(token: string, id: string | number) {
    return this.request(
      `/${encodeURIComponent(token)}/pins/${encodeURIComponent(id)}`,
      { method: "DELETE" },
    );
  }
  replayPage(token: string, turnId: string | number, page: number) {
    return this.request<Replay>(
      `/${encodeURIComponent(token)}/turns/${encodeURIComponent(turnId)}/replay/${page}`,
    );
  }
  startDemo() {
    return this.request("/replay/start", {
      base: "/api",
      body: { interval_ms: 1100 },
    });
  }
  resetDemo() {
    return this.request("/demo/reset", { body: {} });
  }
  socketUrl(
    token: string,
    location: Pick<Location, "protocol" | "host"> = globalThis.location,
  ) {
    return `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}${this.base}/${encodeURIComponent(token)}/live`;
  }
}
