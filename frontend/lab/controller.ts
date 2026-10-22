import { LabApi } from './api.ts';
import { LabView } from './view.ts';
import type { Calculation, LabMatch, LabState, Rule, ServiceError } from './types.ts';

type ActionName = 'add' | 'plan';
const byId = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

/** Coordinates user actions and one non-overlapping polling loop. */
export class FilterLab {
  api: LabApi;
  view: LabView;
  state: LabState | null;
  busy: ActionName | false;
  prepared: Rule | null;
  refreshSequence: number;
  inspectionSequence: number;
  connectionFailed: boolean;
  conversationId: string | null;
  planLabel: string;
  matches: LabMatch[] = [];
  matchesAt = 0;
  constructor(api: LabApi, view: LabView) {
    this.api = api;
    this.view = view;
    this.state = null;
    this.busy = false;
    this.prepared = null;
    this.refreshSequence = 0;
    this.inspectionSequence = 0;
    this.connectionFailed = false;
    this.conversationId = null;
    this.planLabel = '';
  }

  async start() {
    byId('match-select').addEventListener('change', event => this.select((event.target as HTMLSelectElement).value));
    byId('prompt-form').addEventListener('submit', event => {
      event.preventDefault();
      const prompt = byId<HTMLInputElement>('prompt').value.trim();
      if (!prompt) { this.view.error('Describe the stat you want to track first.'); return; }
      this.action('plan', async () => {
        await this.requestPlan(prompt);
      });
    });
    byId('reply-form').addEventListener('submit', event => {
      event.preventDefault();
      const reply = byId<HTMLInputElement>('reply').value.trim();
      if (!reply || !this.conversationId) return;
      this.action('plan', async () => {
        await this.requestPlan(reply, true);
        byId<HTMLInputElement>('reply').value = '';
      });
    });
    byId('add-plan').addEventListener('click', () => this.action('add', async () => {
      if (!this.prepared) return;
      await this.api.add(this.prepared, this.planLabel);
      this.prepared = null;
      this.conversationId = null;
      this.view.plan({ message: 'Added. Your filter will update as events arrive.' });
    }));
    byId('rule-dialog').addEventListener('close', () => { this.inspectionSequence++; });
    byId('close-dialog').addEventListener('click', () => byId<HTMLDialogElement>('rule-dialog').close());
    await this.poll();
  }

  /** Switching match drops everything scoped to the previous one. */
  select(matchId: string) {
    if (matchId === this.api.match) return;
    this.api.match = matchId;
    try { sessionStorage.setItem('lab-match', matchId); } catch { /* Storage is optional. */ }
    this.refreshSequence++;
    this.inspectionSequence++;
    this.state = null;
    this.prepared = null;
    this.conversationId = null;
    byId('plan-result').hidden = true;
    this.view.match(this.matches.find(match => match.match_id === matchId));
    this.view.controls(null, this.busy);
  }

  /** The selector lists matches with live events first, as the backend orders them. */
  async loadMatches() {
    this.matchesAt = Date.now();
    this.matches = await this.api.matches();
    let saved: string | null = null;
    try { saved = sessionStorage.getItem('lab-match'); } catch { /* Storage is optional. */ }
    const ids = this.matches.map(match => match.match_id);
    const chosen = ids.includes(this.api.match) ? this.api.match : saved && ids.includes(saved) ? saved : ids[0] ?? '';
    this.view.matches(this.matches, chosen);
    if (chosen !== this.api.match) this.select(chosen);
    else this.view.match(this.matches.find(match => match.match_id === chosen));
  }

  async refresh() {
    const request = ++this.refreshSequence;
    const match = this.api.match;
    const next = { ...await this.api.state(), match_id: match };
    if (request !== this.refreshSequence) return;
    this.state = next;
    window.labState = next;
    window.dispatchEvent(new CustomEvent('lab-state', { detail: next }));
    if (this.connectionFailed) { this.view.error(); this.connectionFailed = false; }
    if (this.state.error) this.view.error(this.state.error);
    this.view.state(this.state, calculation => this.inspectRule(calculation), seq => this.inspectEvent(seq));
    this.view.controls(this.state, this.busy);
  }

  async requestPlan(prompt: string, followup = false) {
    if (!followup) { this.conversationId = null; this.planLabel = prompt; }
    this.prepared = null;
    const conversationId = this.conversationId;
    this.view.plan({ message: 'The agent is preparing and checking your rule…' });
    const plan = await this.api.plan(prompt, conversationId);
    const goal = typeof plan.goal === 'string' ? undefined : plan.goal;
    this.prepared = plan.status === 'ready' ? plan.rule || null : null;
    this.conversationId = plan.conversation_id || (plan.status === 'failed' ? conversationId : null);
    this.planLabel = (goal?.description || this.planLabel).slice(0, 160);
    this.view.plan({ ...plan, conversation_id: this.conversationId });
  }

  inspectRule(calculation: Calculation) {
    this.inspectionSequence++;
    this.view.inspect(calculation);
  }

  async inspectEvent(seq: number) {
    const request = ++this.inspectionSequence;
    this.view.inspectEventLoading(seq);
    try {
      const payload = await this.api.event(seq);
      if (request === this.inspectionSequence) this.view.inspectEvent(payload);
    } catch (error) {
      if (request === this.inspectionSequence) this.view.inspectEventError((error as ServiceError).message);
    }
  }

  async action(name: ActionName, operation: () => Promise<unknown>) {
    if (this.busy) return;
    this.busy = name;
    this.view.error();
    this.view.controls(this.state, this.busy);
    try { await operation(); await this.refresh(); }
    catch (caught) {
      const error = caught as ServiceError;
      this.view.error(error.message);
      if (name === 'plan') {
        if (['conversation_expired', 'conversation_limit'].includes(String(error.code))) this.conversationId = null;
        this.view.plan({ message: error.message, conversation_id: this.conversationId });
      }
    }
    finally { this.busy = false; this.view.controls(this.state, this.busy); }
  }

  async poll() {
    try {
      if (Date.now() - this.matchesAt > 5000) await this.loadMatches();
      if (!this.api.match) { this.view.controls(null, this.busy); return; }
      await this.refresh();
    } catch (error) { this.connectionFailed = true; this.view.error((error as ServiceError).message); }
    finally { window.setTimeout(() => this.poll(), 700); }
  }
}

if (typeof document !== 'undefined') new FilterLab(new LabApi(), new LabView()).start();
