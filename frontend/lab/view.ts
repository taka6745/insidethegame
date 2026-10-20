import { clock, eventSeconds, replaySeconds, title, teamNames } from './format.ts';
import type { Calculation, EventPayload, LabEvent, LabState, PlanResult, Scenario } from './types.ts';

const el = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const text = (id: string, value: string | number | undefined) => { el(id).textContent = value === undefined ? null : String(value); };
const node = <K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, content?: string | number): HTMLElementTagNameMap[K] => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (content !== undefined) element.textContent = String(content);
  return element;
};

/** DOM-only rendering; calculations and persistence belong to backend services. */
export class LabView {
  presetCount: number;
  lastCards: string;
  lastEvents: string;
  recordingEditable: boolean;
  constructor() { this.presetCount = 0; this.lastCards = ''; this.lastEvents = ''; this.recordingEditable = true; }

  scenario(data: Scenario) {
    this.recordingEditable = data.recording_editable !== false;
    const [home, away] = teamNames(data.teams);
    text('home-team', home); text('away-team', away);
    const recording = data.recording || {};
    text('recording-name', recording.filename || 'Recording unavailable');
    text('recording-meta', [recording.synthetic ? 'Synthetic fixture' : recording.title, recording.format, recording.delivery_count !== undefined ? `${recording.delivery_count} deliveries` : null, recording.event_count !== undefined ? `${recording.event_count} events` : null, !this.recordingEditable ? 'Source managed by ETL' : null].filter(Boolean).join(' · '));
    const select = el<HTMLSelectElement>('presets');
    this.presetCount = data.presets?.length || 0;
    select.replaceChildren(...(data.presets?.length ? data.presets.map(preset => {
      const option = node('option', '', preset.label);
      option.value = preset.id;
      return option;
    }) : [node('option', '', 'No ready-made requests for this recording')]));
    select.disabled = !data.presets?.length;
    this.describePreset(data.presets?.[0]?.label || '');
  }

  describePreset(label: string) { text('preset-description', label); }

  error(message = '') {
    text('notice', message);
    el('notice').hidden = !message;
  }

  plan(result: PlanResult) {
    const goal = typeof result.goal === 'string' ? undefined : result.goal;
    el('plan-result').hidden = false;
    text('plan-message', result.clarification?.question || (result.status === 'ready' ? goal?.description : '') || result.message || goal?.description || (typeof result.goal === 'string' ? result.goal : '') || (result.rule ? 'Your rule is ready. Review it, then add it.' : 'The planner could not prepare this filter.'));
    text('plan-options', (result.clarification?.options || []).join(' · '));
    el('reply-form').hidden = !result.conversation_id;
    text('reply-label', result.status === 'clarification' ? 'Your answer' : 'Want to adjust this request?');
    text('plan-rule', result.rule ? JSON.stringify(result.rule, null, 2) : '');
    el('plan-rule').hidden = !result.rule;
    el('plan-rule-details').hidden = !result.rule;
    el<HTMLDetailsElement>('plan-rule-details').open = false;
    el('add-plan').hidden = !result.rule;
  }

  controls(state: LabState | null, busy: string | false) {
    const running = state?.status === 'running';
    const finished = state?.status === 'finished';
    const failed = state?.status === 'error';
    const ready = !!state;
    const disable = (id: string, disabled: boolean) => { el<HTMLButtonElement>(id).disabled = disabled; };
    disable('load-recording', !ready || !!busy || running || !this.recordingEditable);
    disable('default-recording', !ready || !!busy || running);
    disable('start', !ready || !!busy || running || finished || failed);
    disable('reset', !ready || !!busy || running);
    // Configure before replay; no mid-stream planning ambiguity in this test client.
    disable('add-preset', !ready || !!busy || running || finished || failed || !this.presetCount);
    disable('prepare', !ready || !!busy || running || finished || failed || !state?.llm?.configured);
    disable('add-plan', !ready || !!busy || running || finished || failed);
    disable('prompt', !!busy || running || finished);
    disable('reply', !!busy || running || finished);
    disable('send-reply', !ready || !!busy || running || finished || failed);
    disable('presets', !this.presetCount || !!busy || running || finished);
    text('prepare', busy === 'plan' ? 'Preparing your rule…' : 'Prepare request ↗');
    text('start', running ? 'Replay running…' : finished ? 'Replay finished' : '▶ Start replay');
  }

  state(state: LabState, inspectRule: (calculation: Calculation) => void, inspectEvent: (deliveryIndex: number) => unknown) {
    text('status', title(state.status));
    el('status').dataset.status = state.status;
    const events = state.events || [];
    text('clock', clock(state.match_time_seconds ?? replaySeconds(events)));
    text('progress', `${state.position ?? events.length} of ${state.total ?? 0} deliveries · forward only`);
    text('event-count', `${state.position ?? events.length} deliveries received`);
    el('progress-bar').style.width = `${Math.min(100, (state.position || 0) / (state.total || 1) * 100)}%`;
    text('total-rules', state.metrics?.total_rules ?? state.calculations?.length ?? 0);
    text('candidates', state.metrics?.candidate_count ?? 0);
    text('changes', state.metrics?.changed_count ?? 0);
    text('model-status', state.llm?.configured ? 'Local model configured · runs only when requested' : 'Local model not configured · sample filters still work');
    this.cards(state.calculations || [], inspectRule);
    this.events(events, inspectEvent);
  }

  cards(calculations: Calculation[], inspectRule: (calculation: Calculation) => void) {
    const signature = JSON.stringify(calculations);
    if (signature === this.lastCards) return;
    this.lastCards = signature;
    if (!calculations.length) {
      const empty = node('div', 'empty-stats');
      const copy = node('p', '', 'Your custom stats will appear here.');
      copy.append(node('small', '', 'Add a filter to get started.'));
      empty.append(node('span', '', '＋'), copy);
      el('cards').replaceChildren(empty);
      return;
    }
    el('cards').replaceChildren(...calculations.map(calc => {
      const card = node('button', 'stat-card');
      card.type = 'button';
      card.append(node('span', 'stat-label', calc.label || calc.rule?.label || calc.id), node('strong', 'stat-value', calc.value ?? '–'), node('span', 'stat-detail', 'View structured rule ↗'));
      card.addEventListener('click', () => inspectRule(calc));
      return card;
    }));
  }

  events(events: LabEvent[], inspectEvent: (deliveryIndex: number) => unknown) {
    const signature = JSON.stringify(events);
    if (signature === this.lastEvents) return;
    this.lastEvents = signature;
    if (!events.length) {
      el('events').replaceChildren(node('div', 'empty-events', 'The feed starts when you press Start replay. Events move forward only.'));
      return;
    }
    el('events').replaceChildren(...events.slice(-60).reverse().map(event => {
      const row = node('button', 'event-row');
      row.type = 'button';
      row.disabled = event.delivery_index === undefined;
      row.addEventListener('click', () => inspectEvent(event.delivery_index as number));
      const type = event.event_type || event.type || event.typeName || 'event';
      row.dataset.type = type;
      const info = node('div', 'event-info');
      const revision = event.deleted ? ' · Retracted' : Number(event.revision) > 1 ? ` · Correction v${event.revision}` : '';
      info.append(node('strong', '', title(type) + revision));
      const player = event.player_name || event.player || event.player_id || event.playerId;
      const team = event.team_name || event.team_id || event.team || event.teamId;
      info.append(node('span', '', [team, player, event.body_part === 'head' ? 'Headed touch' : null].filter(Boolean).join(' · ')));
      row.append(node('time', '', clock(eventSeconds(event))), info, node('span', 'event-id', event.id || event.event_id || event.eventId || ''));
      if (event.key_moment) row.classList.add('key-moment');
      row.setAttribute('aria-label', `Inspect ${title(type)} at ${clock(eventSeconds(event))}`);
      return row;
    }));
  }

  inspectEventLoading(deliveryIndex: number) {
    text('rule-title', `Delivery ${deliveryIndex + 1}`);
    text('detail-description', 'Received event payload and canonical event.');
    text('rule-detail', 'Loading received payload…');
    el<HTMLDialogElement>('rule-dialog').showModal();
  }

  inspectEvent(payload: EventPayload) {
    text('rule-detail', JSON.stringify({ raw: payload.raw, canonical: payload.canonical }, null, 2));
  }

  inspectEventError(message: string) { text('rule-detail', message); }

  inspect(calculation: Calculation) {
    text('detail-description', 'Stored by the backend. Indexed and evaluated against incoming events.');
    text('rule-title', calculation.label || 'Calculation rule');
    text('rule-detail', JSON.stringify(calculation.rule, null, 2));
    el<HTMLDialogElement>('rule-dialog').showModal();
  }
}
