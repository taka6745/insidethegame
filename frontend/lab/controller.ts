import { LabApi } from './api.ts';
import type { RecordingResult } from './api.ts';
import { LabView } from './view.ts';
import type { Calculation, LabState, Rule, Scenario, ServiceError } from './types.ts';

type ActionName = 'recording' | 'add' | 'plan' | 'start' | 'reset';
const byId = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

/** Coordinates user actions and one non-overlapping polling loop. */
export class FilterLab {
  api: LabApi;
  view: LabView;
  state: LabState | null;
  busy: ActionName | false;
  prepared: Rule | null;
  scenario: Scenario | null;
  refreshSequence: number;
  inspectionSequence: number;
  connectionFailed: boolean;
  conversationId: string | null;
  planLabel: string;
  constructor(api: LabApi, view: LabView) {
    this.api = api;
    this.view = view;
    this.state = null;
    this.busy = false;
    this.prepared = null;
    this.scenario = null;
    this.refreshSequence = 0;
    this.inspectionSequence = 0;
    this.connectionFailed = false;
    this.conversationId = null;
    this.planLabel = '';
  }

  async start() {
    const fileInput = byId<HTMLInputElement>('recording-file');
    byId('load-recording').addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
      const file = fileInput.files?.[0];
      if (file) this.action('recording', async () => this.recording(await this.api.loadRecording(file)));
      fileInput.value = '';
    });
    byId('default-recording').addEventListener('click', () => this.action('recording', async () => this.recording(await this.api.defaultRecording())));
    byId('presets').addEventListener('change', event => {
      const value = (event.target as HTMLSelectElement).value;
      this.view.describePreset(this.scenario?.presets!.find(item => item.id === value)?.label || '');
    });
    byId('add-preset').addEventListener('click', () => this.action('add', async () => {
      const id = byId<HTMLSelectElement>('presets').value;
      const preset = this.scenario!.presets!.find(item => item.id === id);
      if (preset) await this.api.add(preset.rule, preset.label);
    }));
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
    byId('start').addEventListener('click', () => this.action('start', () => this.api.start()));
    byId('reset').addEventListener('click', () => this.action('reset', async () => {
      await this.api.reset();
      this.prepared = null;
      this.conversationId = null;
      byId('plan-result').hidden = true;
    }));
    byId('rule-dialog').addEventListener('close', () => { this.inspectionSequence++; });
    byId('close-dialog').addEventListener('click', () => byId<HTMLDialogElement>('rule-dialog').close());
    await this.poll();
  }

  async refresh() {
    const request = ++this.refreshSequence;
    const next = await this.api.state();
    if (request !== this.refreshSequence) return;
    this.state = next;
    window.labState = next;
    window.dispatchEvent(new CustomEvent('lab-state', { detail: next }));
    if (this.connectionFailed) { this.view.error(); this.connectionFailed = false; }
    if (this.state.error) this.view.error(this.state.error);
    this.view.state(this.state, calculation => this.inspectRule(calculation), deliveryIndex => this.inspectEvent(deliveryIndex));
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

  recording(result: RecordingResult) {
    this.scenario = result.scenario;
    this.view.scenario(this.scenario);
    this.prepared = null;
    this.conversationId = null;
    byId('plan-result').hidden = true;
  }

  inspectRule(calculation: Calculation) {
    this.inspectionSequence++;
    this.view.inspect(calculation);
  }

  async inspectEvent(deliveryIndex: number) {
    const request = ++this.inspectionSequence;
    this.view.inspectEventLoading(deliveryIndex);
    try {
      const payload = await this.api.event(deliveryIndex);
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
      if (!this.scenario) {
        this.scenario = await this.api.scenario();
        this.view.scenario(this.scenario);
      }
      await this.refresh();
    } catch (error) { this.connectionFailed = true; this.view.error((error as ServiceError).message); }
    finally { window.setTimeout(() => this.poll(), 700); }
  }
}

if (typeof document !== 'undefined') new FilterLab(new LabApi(), new LabView()).start();
