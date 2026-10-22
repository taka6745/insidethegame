import type {
  Audience,
  Follow,
  FollowOption,
  FollowReply,
  FollowSpec,
  FollowTurn,
  MatchSummary,
  Profile,
  Replay,
  ServiceError,
  SnapshotResult,
  ViewerSession,
} from "./types.ts";
import type { Prices } from "./receipt.ts";

export type Fetcher = (
  input: string,
  init: RequestInit,
) => Promise<Pick<Response, "ok" | "status" | "json">>;
interface RequestOptions {
  body?: unknown;
  method?: string;
  signal?: AbortSignal;
  /** Milliseconds before the browser gives up (default 75 s). */
  timeout?: number;
}
interface ErrorBody {
  detail?: unknown;
  message?: unknown;
  error?: unknown;
  code?: unknown;
}

export const QUESTION_TIMEOUT_MS = 255_000;

/** Text safe to show a viewer: our own service messages pass through; anything else (a script error, a raw
 * exception) becomes a plain sentence, so a viewer never sees exception text. */
export function friendly(error: unknown, fallback = "Something went wrong. Please try again."): string {
  const known = error as ServiceError | undefined;
  return known instanceof Error && typeof known.status === "number" && known.message ? known.message : fallback;
}

/** Same-origin application boundary. No provider or database access in the client. */
export class MatchApi {
  fetcher: Fetcher;
  base: string;
  /** The match this viewer has open; session routes are scoped by it. */
  match: string;
  constructor(
    fetcher: Fetcher = (...args) => globalThis.fetch(...args),
    base = "/viewer-api",
    match = "",
  ) {
    this.fetcher = fetcher;
    this.base = base;
    this.match = match;
  }
  /** Response bodies are typed by the backend contract; callers narrow live snapshots. */
  async request<T = unknown>(
    path: string,
    { body, method, signal, timeout = 75000 }: RequestOptions = {},
  ): Promise<T> {
    let response: Awaited<ReturnType<Fetcher>>;
    try {
      response = await this.fetcher(`${this.base}${path}`, {
        method: method || (body === undefined ? "GET" : "POST"),
        headers: { "Content-Type": "application/json" },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        signal: signal || AbortSignal.timeout(timeout),
      });
    } catch (caught) {
      // Never show the browser's raw network or abort text to a viewer.
      const aborted = (caught as Error)?.name === "AbortError" && signal?.aborted;
      const error: ServiceError = new Error((caught as Error)?.name === "TimeoutError"
        ? "The match service is taking too long. Please try again."
        : "Can't reach the match service right now. Check your connection and try again.");
      error.code = aborted ? "aborted" : "network";
      error.status = 0;
      throw error;
    }
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
  /** Matches the viewer can open; global, like profiles. */
  matches(timeout?: number) {
    return this.request<MatchSummary[]>("/matches", { timeout });
  }
  profiles() {
    return this.request<{ profiles: Profile[] }>("/profiles");
  }
  /** Every session route lives under `/matches/{matchId}/sessions`; a token belongs to one match. */
  sessions(token?: string) {
    const root = `/matches/${encodeURIComponent(this.match)}/sessions`;
    return token === undefined ? root : `${root}/${encodeURIComponent(token)}`;
  }
  session(profileId: string, viewerId = "") {
    return this.request<ViewerSession>(this.sessions(), { body: { profile_id: profileId, viewer_id: viewerId } });
  }
  restore(token: string) {
    return this.request<ViewerSession>(this.sessions(token));
  }
  audience(token: string, selection: Audience) {
    return this.request<SnapshotResult>(`${this.sessions(token)}/audience`, {
      method: "PUT", body: selection,
    });
  }
  /** Configured answer prices (US$ per million tokens); a viewer cannot change them. */
  prices() {
    return this.request<Prices & { revision?: number }>("/prices");
  }
  /** `seq` is the snapshot the viewer's picture shows: the answer never cites anything after it. */
  ask(token: string, prompt: string, requestId: string, seq?: number) {
    // Above the backend's question budget (240 s) and nginx's 250 s, so the server answers first.
    return this.request(`${this.sessions(token)}/messages`, {
      body: { prompt, request_id: requestId, ...(Number.isInteger(seq) ? { seq } : {}) },
      timeout: QUESTION_TIMEOUT_MS,
    });
  }
  track(token: string, id: string) {
    return this.request<SnapshotResult>(
      `${this.sessions(token)}/offers/${encodeURIComponent(id)}/track`,
      { body: {} },
    );
  }
  unpin(token: string, id: string | number) {
    return this.request(
      `${this.sessions(token)}/pins/${encodeURIComponent(id)}`,
      { method: "DELETE" },
    );
  }
  replayPage(token: string, turnId: string | number, page: number) {
    return this.request<Replay>(
      `${this.sessions(token)}/turns/${encodeURIComponent(turnId)}/replay/${page}`,
    );
  }
  /** Story follows (contracts §8b): one active follow per viewer. */
  follows(token: string) {
    return this.request<{ follow: Follow | null; follows: Follow[]; turns: FollowTurn[] }>(
      `${this.sessions(token)}/follows`);
  }
  /** `matchId`: another live match of the demo whose story this is (a cross-match option); its own position bounds it. */
  follow(token: string, spec: FollowSpec, seq?: number, matchId?: string) {
    return this.request<SnapshotResult & { follow: Follow; created: boolean }>(`${this.sessions(token)}/follows`, {
      body: { spec, ...(Number.isInteger(seq) ? { seq } : {}), ...(matchId ? { match_id: matchId } : {}) },
    });
  }
  unfollow(token: string, subscriptionId: string) {
    return this.request<SnapshotResult>(
      `${this.sessions(token)}/follows/${encodeURIComponent(subscriptionId)}`, { method: "DELETE" });
  }
  followSuggestions(token: string, seq?: number) {
    return this.request<{ snapshot_id?: string; items: FollowOption[] }>(
      `${this.sessions(token)}/follow/suggestions${Number.isInteger(seq) ? `?seq=${seq}` : ""}`);
  }
  /** One follow-chat turn; a proposal is never a follow until `follow()` confirms it. */
  followMessage(token: string, prompt: string, requestId: string, seq?: number) {
    return this.request<FollowReply>(`${this.sessions(token)}/follow/messages`, {
      body: { prompt, request_id: requestId, ...(Number.isInteger(seq) ? { seq } : {}) },
      timeout: QUESTION_TIMEOUT_MS,
    });
  }
  socketUrl(
    token: string,
    location: Pick<Location, "protocol" | "host"> = globalThis.location,
  ) {
    return `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}${this.base}${this.sessions(token)}/live`;
  }
}

/** Match ids are feed-minted slugs; anything else never reaches a URL. */
export function validMatchId(value: unknown): value is string {
  return typeof value === "string" && /^[a-z0-9][a-z0-9-]{0,63}$/.test(value);
}
