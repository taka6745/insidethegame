import { ChatApi } from './chat-api.js';
import { ChatView } from './chat-view.js';

/** Independent question requests never block the event replay poller. */
export class ChatController {
  constructor(api, view, storage = sessionStorage) {
    this.api = api; this.view = view; this.storage = storage;
    this.runId = null; this.token = null; this.generation = 0; this.busy = false; this.session = null;
    this.polling = false; this.polledAt = 0; this.retry = null;
    this.restoreAllowed = typeof performance !== 'undefined' && performance.getEntriesByType('navigation')[0]?.type === 'reload';
  }
  async start() {
    const data = await this.api.profiles();
    this.view.profiles(data.profiles, this.storage.getItem('chat-profile'));
    this.profile = document.getElementById('chat-profile').value;
    document.getElementById('chat-profile').addEventListener('change', event => {
      this.profile = event.target.value; this.storage.setItem('chat-profile', this.profile);
      this.connect(true);
    });
    document.getElementById('chat-reconnect').addEventListener('click', () => this.connect(true));
    document.getElementById('chat-form').addEventListener('submit', event => {
      event.preventDefault();
      const field = document.getElementById('chat-prompt');
      const prompt = field.value.trim();
      if (prompt) { field.value = ''; this.send(prompt); }
    });
    window.addEventListener('lab-state', event => this.updateRun(event.detail));
    if (window.labState) this.updateRun(window.labState);
  }
  async updateRun(state) {
    if (state.run_id === this.runId) {
      if (this.token && !this.busy && !this.polling && Date.now() - this.polledAt > 1500) await this.pollHistory();
      return;
    }
    this.runId = state.run_id;
    await this.connect(false);
  }
  async connect(takeover) {
    const generation = ++this.generation;
    this.busy = true; this.token = null; this.retry = null;
    this.view.render({ turns: [], offers: [] }, () => {});
    this.view.status('Opening match chat…', true);
    const key = `chat-token:${this.profile}:${this.runId}`;
    try {
      const saved = takeover || !this.restoreAllowed ? null : this.storage.getItem(key);
      this.restoreAllowed = false;
      let session;
      if (saved) session = await this.api.history(saved);
      else session = await this.api.session(this.profile);
      if (generation !== this.generation) return;
      if (session.run_id !== this.runId) return;
      this.token = session.session_token;
      this.storage.setItem(key, this.token);
      this.show(session);
    } catch (error) { if (generation === this.generation) this.view.status(error.message + ' Use Reconnect to take over.', true); }
    finally { if (generation === this.generation) this.busy = false; }
  }
  async pollHistory() {
    const generation = this.generation, token = this.token;
    this.polling = true; this.polledAt = Date.now();
    try {
      const session = await this.api.history(token);
      if (generation === this.generation && !this.busy) this.show(session);
    } catch (error) {
      if (generation === this.generation) {
        if (error.code === 'session_replaced') this.token = null;
        this.view.status(error.message + ' Use Reconnect to continue.', true);
      }
    } finally { this.polling = false; }
  }
  show(session) {
    this.session = session;
    this.view.render(session, id => this.track(id));
    const pending = session.turns.some(t => t.status === 'pending');
    this.view.status(`${session.mode === 'local' ? 'Microsoft Agent Framework · Local model' : 'Fixture agent · Listed examples only'} · Synthetic match`, pending);
  }
  async send(prompt) {
    if (this.busy || !this.token) return;
    const generation = this.generation, token = this.token;
    this.busy = true; this.view.status('Checking the match…', true);
    this.view.render({ ...this.session, turns: [...this.session.turns, { prompt, reply: null }] }, () => {});
    try {
      const requestId = this.retry?.prompt === prompt ? this.retry.id : crypto.randomUUID();
      this.retry = { prompt, id: requestId };
      await this.api.ask(token, prompt, requestId);
      this.retry = null;
      const session = await this.api.history(token);
      if (generation === this.generation) this.show(session);
    } catch (error) { if (generation === this.generation) this.view.status(error.message, false); }
    finally { if (generation === this.generation) this.busy = false; }
  }
  async track(offerId) {
    const generation = this.generation, token = this.token;
    try {
      await this.api.track(token, offerId);
      const session = await this.api.history(token);
      if (generation === this.generation) this.show(session);
    } catch (error) { if (generation === this.generation) this.view.status(error.message, false); }
  }
}

if (typeof document !== 'undefined') {
  for (const button of document.querySelectorAll('[data-workspace-tab]')) button.addEventListener('click', () => {
    for (const tab of document.querySelectorAll('[data-workspace-tab]')) {
      const active = tab === button;
      tab.setAttribute('aria-selected', String(active));
      document.getElementById(tab.dataset.workspaceTab).hidden = !active;
    }
  });
  new ChatController(new ChatApi(), new ChatView()).start().catch(error => new ChatView().status(error.message, true));
}
