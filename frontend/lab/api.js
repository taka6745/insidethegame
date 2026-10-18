/** The only network boundary. Replace this adapter when the product API is ready. */
export class LabApi {
  constructor(base = '/api') { this.base = base; }

  async request(path, body) {
    const response = await fetch(`${this.base}${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const text = await response.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; }
    catch { throw new Error(`The backend returned an unreadable response (${response.status}).`); }
    if (!response.ok) {
      const detail = data.detail || data.message || data.error;
      const message = Array.isArray(detail) ? detail.map(issue => issue.msg || 'Invalid input').join('; ') : detail;
      throw new Error(typeof message === 'string' ? message : `Request failed (${response.status}).`);
    }
    return data;
  }

  scenario() { return this.request('/scenario'); }
  state() { return this.request('/state'); }
  add(rule, label) { return this.request('/calculations', { rule, ...(label ? { label } : {}) }); }
  plan(prompt) { return this.request('/plan', { prompt }); }
  start() { return this.request('/replay/start', { interval_ms: 1000 }); }
  reset() { return this.request('/reset', {}); }
}
