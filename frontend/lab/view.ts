import { clock, eventSeconds, replaySeconds, title, teamNames } from './format.ts';
import type { Calculation, EventPayload, LabEvent, LabMatch, LabState, PlanResult } from './types.ts';

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
  lastCards: string;
  lastEvents: string;
  constructor() { this.lastCards = ''; this.lastEvents = ''; }

  /** The match selector; options change only when the listed matches do. */
  matches(matches: LabMatch[], chosen: string) {
    const select = el<HTMLSelectElement>('match-select');
    const label = (match: LabMatch) => `${match.teams?.length ? teamNames(match.teams).join(' v ') : match.fixture || match.match_id} · ${title(match.status)}`;
    const signature = JSON.stringify(matches.map(match => [match.match_id, label(match)]));
    if (select.dataset.signature !== signature) {
      select.dataset.signature = signature;
      select.replaceChildren(...(matches.length ? matches.map(match => {
        const option = node('option', '', label(match));
        option.value = match.match_id;
        return option;
      }) : [node('option', '', 'No matches yet')]));
    }
    select.disabled = !matches.length;
    select.value = chosen;
    if (!matches.length) this.match(undefined);
  }

  match(match: LabMatch | undefined) {
    const [home, away] = match?.teams?.length ? teamNames(match.teams) : ['Home', 'Away'];
    text('home-team', home); text('away-team', away);
    text('recording-meta', match ? `${match.match_id} · live events as received` : 'Start a match from the developer config screen.');
    text('status', match ? title(match.status) : 'No match');
    el('status').dataset.status = match?.status ?? '';
    if (!match) { this.lastEvents = ''; this.lastCards = ''; }
  }

  /** Shown as published by the backend; hidden until both teams have a value. */
  score(teams: LabState['score']) {
    const [home, away] = teams || [];
    const ready = !!home && !!away && home.score != null && away.score != null;
    text('score', ready ? `${home.name} ${home.score} – ${away.score} ${away.name}` : '');
    el('score').hidden = !ready;
  }

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
    const ready = !!state;
    const disable = (id: string, disabled: boolean) => { el<HTMLButtonElement>(id).disabled = disabled; };
    // Rules evaluate over the events this match has received; they can be added at any time.
    disable('prepare', !ready || !!busy || !state?.llm?.configured);
    disable('add-plan', !ready || !!busy);
    disable('prompt', !!busy);
    disable('reply', !!busy);
    disable('send-reply', !ready || !!busy);
    text('prepare', busy === 'plan' ? 'Preparing your rule…' : 'Prepare request ↗');
  }

  state(state: LabState, inspectRule: (calculation: Calculation) => void, inspectEvent: (seq: number) => unknown) {
    const events = state.events || [];
    text('clock', clock(state.match_time_seconds ?? replaySeconds(events)));
    text('progress', `${state.seq ?? events.length} events received · forward only`);
    text('event-count', `${state.seq ?? events.length} events received`);
    text('total-rules', state.metrics?.total_rules ?? state.calculations?.length ?? 0);
    text('candidates', state.metrics?.candidate_count ?? 0);
    text('changes', state.metrics?.changed_count ?? 0);
    text('model-status', state.llm?.configured ? 'Local model configured · runs only when requested' : 'No model configured · custom stats unavailable');
    this.score(state.score);
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

  events(events: LabEvent[], inspectEvent: (seq: number) => unknown) {
    const signature = JSON.stringify(events);
    if (signature === this.lastEvents) return;
    this.lastEvents = signature;
    if (!events.length) {
      el('events').replaceChildren(node('div', 'empty-events', 'Events appear here as the live match sends them.'));
      return;
    }
    el('events').replaceChildren(...events.slice(-60).reverse().map(event => {
      const row = node('button', 'event-row');
      row.type = 'button';
      row.disabled = event.seq === undefined;
      row.addEventListener('click', () => inspectEvent(event.seq as number));
      const type = event.type || 'event';
      row.dataset.type = type;
      const info = node('div', 'event-info');
      const revision = event.deleted ? ' · Retracted' : Number(event.revision) > 1 ? ` · Correction v${event.revision}` : '';
      info.append(node('strong', '', title(type) + revision));
      info.append(node('span', '', [event.team, event.player, event.body_part === 'head' ? 'Headed touch' : null].filter(Boolean).join(' · ')));
      row.append(node('time', '', clock(eventSeconds(event))), info, node('span', 'event-id', event.id || ''));
      row.setAttribute('aria-label', `Inspect ${title(type)} at ${clock(eventSeconds(event))}`);
      return row;
    }));
  }

  inspectEventLoading(seq: number) {
    text('rule-title', `Event ${seq}`);
    text('detail-description', 'The canonical event as this match received it.');
    text('rule-detail', 'Loading received payload…');
    el<HTMLDialogElement>('rule-dialog').showModal();
  }

  inspectEvent(payload: EventPayload) {
    text('rule-detail', JSON.stringify(payload.canonical, null, 2));
  }

  inspectEventError(message: string) { text('rule-detail', message); }

  inspect(calculation: Calculation) {
    text('detail-description', 'Stored by the backend. Indexed and evaluated against incoming events.');
    text('rule-title', calculation.label || 'Calculation rule');
    text('rule-detail', JSON.stringify(calculation.rule, null, 2));
    el<HTMLDialogElement>('rule-dialog').showModal();
  }
}
