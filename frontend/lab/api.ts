import type { Calculation, EventPayload, LabState, PlanResult, Rule, Scenario, ServiceError } from './types.ts';

interface ErrorBody { detail?: unknown; message?: unknown; error?: unknown; code?: unknown }
export interface RecordingResult { scenario: Scenario; state?: LabState }

/** The only network boundary. Replace this adapter when the product API is ready. */
export class LabApi {
  base: string;
  constructor(base = '/api') { this.base = base; }

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

  async loadRecording(file: File): Promise<RecordingResult> {
    if (file.size > 16 * 1024 * 1024) throw new Error('Recording must be 16 MiB or smaller.');
    const response = await fetch(`${this.base}/recording`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Recording-Filename': encodeURIComponent(file.name) },
      body: file,
    });
    return this.parse(response);
  }
  defaultRecording() { return this.request<RecordingResult>('/recording/default', {}); }
  scenario() { return this.request<Scenario>('/scenario'); }
  event(deliveryIndex: number) { return this.request<EventPayload>(`/events/${encodeURIComponent(deliveryIndex)}`); }
  state() { return this.request<LabState>('/state'); }
  add(rule: Rule, label?: string) { return this.request<Calculation>('/calculations', { rule, ...(label ? { label } : {}) }); }
  plan(prompt: string, conversationId: string | null = null) { return this.request<PlanResult>('/plan', { prompt, ...(conversationId ? { conversation_id: conversationId } : {}) }); }
  start() { return this.request('/replay/start', { interval_ms: 1000 }); }
  reset() { return this.request('/reset', {}); }
}
