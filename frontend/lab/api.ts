import type { Calculation, EventPayload, LabMatch, LabState, PlanResult, Rule, ServiceError } from './types.ts';

interface ErrorBody { detail?: unknown; message?: unknown; error?: unknown; code?: unknown }
/** The only network boundary. Every lab route is scoped by the selected match. */
export class LabApi {
  base: string;
  match: string;
  constructor(base = '/api', match = '') { this.base = base; this.match = match; }

  /** `/matches/{matchId}{path}` under the lab base. */
  scoped(path: string) { return `/matches/${encodeURIComponent(this.match)}${path}`; }

  async request<T = unknown>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${this.base}${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    return this.parse<T>(response);
  }

  /** Response bodies are typed by the backend contract; errors are narrowed here. */
  async parse<T>(response: Response): Promise<T> {
    const text = await response.text();
    let data: unknown;
    try { data = text ? JSON.parse(text) : {}; }
    catch { throw new Error(`The backend returned an unreadable response (${response.status}).`); }
    if (!response.ok) {
      const body = data as ErrorBody;
      const detail = body.detail || body.message || body.error;
      const message = Array.isArray(detail) ? detail.map((issue: { msg?: unknown }) => issue.msg || 'Invalid input').join('; ') : detail;
      const error: ServiceError = new Error(typeof message === 'string' ? message : `Request failed (${response.status}).`);
      error.code = body.code;
      error.status = response.status;
      throw error;
    }
    return data as T;
  }

  /** Matches with live events come from the backend's match listing (never the feed). */
  async matches(): Promise<LabMatch[]> { return this.parse(await fetch('/viewer-api/matches')); }
  event(seq: number) { return this.request<EventPayload>(this.scoped(`/events/${encodeURIComponent(seq)}`)); }
  state() { return this.request<LabState>(this.scoped('/state')); }
  add(rule: Rule, label?: string) { return this.request<Calculation>(this.scoped('/calculations'), { rule, ...(label ? { label } : {}) }); }
  plan(prompt: string, conversationId: string | null = null) { return this.request<PlanResult>(this.scoped('/plan'), { prompt, ...(conversationId ? { conversation_id: conversationId } : {}) }); }
}
