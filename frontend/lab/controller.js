import { LabApi } from './api.js';
import { LabView } from './view.js';

/** Coordinates user actions and one non-overlapping polling loop. */
class FilterLab {
  constructor(api, view) {
    this.api = api;
    this.view = view;
    this.state = null;
    this.busy = false;
    this.prepared = null;
    this.scenario = null;
    this.refreshSequence = 0;
    this.connectionFailed = false;
  }

  async start() {
    document.getElementById('presets').addEventListener('change', event => {
      this.view.describePreset(this.scenario?.presets.find(item => item.id === event.target.value)?.label || '');
    });
    document.getElementById('add-preset').addEventListener('click', () => this.action('add', async () => {
      const id = document.getElementById('presets').value;
      const preset = this.scenario.presets.find(item => item.id === id);
      if (preset) await this.api.add(preset.rule, preset.label);
    }));
    document.getElementById('prompt-form').addEventListener('submit', event => {
      event.preventDefault();
      const prompt = document.getElementById('prompt').value.trim();
      if (!prompt) { this.view.error('Describe the stat you want to track first.'); return; }
      this.action('plan', async () => {
        this.prepared = null;
        this.view.plan({ message: 'The agent is preparing and checking your rule…' });
        const plan = await this.api.plan(prompt);
        this.prepared = plan.rule || null;
        this.view.plan(plan);
      });
    });
    document.getElementById('add-plan').addEventListener('click', () => this.action('add', async () => {
      if (!this.prepared) return;
      await this.api.add(this.prepared, document.getElementById('prompt').value.trim());
      this.prepared = null;
      this.view.plan({ message: 'Added. Your filter will update as events arrive.' });
    }));
    document.getElementById('start').addEventListener('click', () => this.action('start', () => this.api.start()));
    document.getElementById('reset').addEventListener('click', () => this.action('reset', async () => {
      await this.api.reset();
      this.prepared = null;
      document.getElementById('plan-result').hidden = true;
    }));
    document.getElementById('close-dialog').addEventListener('click', () => document.getElementById('rule-dialog').close());
    await this.poll();
  }

  async refresh() {
    const request = ++this.refreshSequence;
    const next = await this.api.state();
    if (request !== this.refreshSequence) return;
    this.state = next;
    if (this.connectionFailed) { this.view.error(); this.connectionFailed = false; }
    if (this.state.error) this.view.error(this.state.error);
    this.view.state(this.state, calculation => this.view.inspect(calculation));
    this.view.controls(this.state, this.busy);
  }

  async action(name, operation) {
    if (this.busy) return;
    this.busy = name;
    this.view.error();
    this.view.controls(this.state, this.busy);
    try { await operation(); await this.refresh(); }
    catch (error) {
      this.view.error(error.message);
      if (name === 'plan') this.view.plan({ message: error.message });
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
    } catch (error) { this.connectionFailed = true; this.view.error(error.message); }
    finally { window.setTimeout(() => this.poll(), 700); }
  }
}

new FilterLab(new LabApi(), new LabView()).start();
