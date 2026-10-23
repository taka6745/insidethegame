import { parseResponse } from '../shared/http.ts';
import type { Calculation, EventPayload, LabMatch, LabState, PlanResult, Rule } from './types.ts';

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
    return parseResponse<T>(response);
  }

  /** Matches with live events come from the backend's match listing (never the feed). */
  async matches(): Promise<LabMatch[]> { return parseResponse(await fetch('/viewer-api/matches')); }
  event(seq: number) { return this.request<EventPayload>(this.scoped(`/events/${encodeURIComponent(seq)}`)); }
  state() { return this.request<LabState>(this.scoped('/state')); }
  add(rule: Rule, label?: string) { return this.request<Calculation>(this.scoped('/calculations'), { rule, ...(label ? { label } : {}) }); }
  plan(prompt: string, conversationId: string | null = null) { return this.request<PlanResult>(this.scoped('/plan'), { prompt, ...(conversationId ? { conversation_id: conversationId } : {}) }); }
}
