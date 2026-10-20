/** Same-origin application boundary. No provider or database access in the client. */
export class MatchApi {
  constructor(
    fetcher = (...args) => globalThis.fetch(...args),
    base = "/viewer-api",
  ) {
    this.fetcher = fetcher;
    this.base = base;
  }
  async request(path, { body, method, signal, base = this.base } = {}) {
    const response = await this.fetcher(`${base}${path}`, {
      method: method || (body === undefined ? "GET" : "POST"),
      headers: { "Content-Type": "application/json" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: signal || AbortSignal.timeout(75000),
    });
    let data;
    try {
      data = await response.json();
    } catch {
      const error = new Error(response.status >= 500
        ? "The match service is temporarily unavailable. Please try again shortly."
        : "The match service returned an invalid response. Please try again.");
      error.status = response.status;
      throw error;
    }
    if (!response.ok) {
      const detail = data.detail || data.message || data.error;
      const error = new Error(
        typeof detail === "string"
          ? detail
          : "The match service could not complete that request.",
      );
      error.code = data.code;
      error.status = response.status;
      throw error;
    }
    return data;
  }
  profiles() {
    return this.request("/profiles");
  }
  session(profileId) {
    return this.request("/sessions", { body: { profile_id: profileId } });
  }
  restore(token) {
    return this.request(`/${encodeURIComponent(token)}`);
  }
  audience(token, selection) {
    return this.request(`/${encodeURIComponent(token)}/audience`, {
      method: "PUT", body: selection,
    });
  }
  ask(token, prompt, requestId) {
    return this.request(`/${encodeURIComponent(token)}/messages`, {
      body: { prompt, request_id: requestId },
    });
  }
  track(token, id) {
    return this.request(
      `/${encodeURIComponent(token)}/offers/${encodeURIComponent(id)}/track`,
      { body: {} },
    );
  }
  unpin(token, id) {
    return this.request(
      `/${encodeURIComponent(token)}/pins/${encodeURIComponent(id)}`,
      { method: "DELETE" },
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
  socketUrl(token, location = globalThis.location) {
    return `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}${this.base}/${encodeURIComponent(token)}/live`;
  }
}
