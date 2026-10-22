import test from 'node:test';
import assert from 'node:assert/strict';
import { LabView } from '../lab/view.ts';
import { stub } from './support.ts';

interface NodeDouble { textContent: string; hidden?: boolean; disabled?: boolean; replaceChildren?(): void }
const useDocument = (getElementById: (id: string) => NodeDouble | undefined) => {
  globalThis.document = stub<Document>({ getElementById, createElement: () => ({ textContent: '' }) });
};

test('reuse response displays its explanation without an Add action or fabricated rule', () => {
  const nodes = new Map(['plan-result', 'plan-message', 'plan-rule', 'add-plan', 'plan-options', 'reply-form', 'reply-label', 'plan-rule-details'].map((id): [string, NodeDouble] => [id, { textContent: '', hidden: false }]));
  const original = globalThis.document;
  useDocument(id => nodes.get(id));
  try {
    new LabView().plan({ status: 'reuse', message: 'ETL already provides this standard stat.', rule: null });
    assert.equal(nodes.get('plan-result')!.hidden, false);
    assert.equal(nodes.get('plan-message')!.textContent, 'ETL already provides this standard stat.');
    assert.equal(nodes.get('plan-rule')!.textContent, '');
    assert.equal(nodes.get('plan-rule')!.hidden, true);
    assert.equal(nodes.get('add-plan')!.hidden, true);
  } finally { globalThis.document = original; }
});

test('clarification shows question and reply form without an executable rule', () => {
  const nodes = new Map(['plan-result', 'plan-message', 'plan-rule', 'add-plan', 'plan-options', 'reply-form', 'reply-label', 'plan-rule-details'].map((id): [string, NodeDouble] => [id, { textContent: '', hidden: false }]));
  const original = globalThis.document;
  useDocument(id => nodes.get(id));
  try {
    new LabView().plan({ status: 'clarification', conversation_id: 'opaque', clarification: { question: 'Which player?', options: ['Mbappe', 'Ashworth'] } });
    assert.equal(nodes.get('plan-message')!.textContent, 'Which player?');
    assert.equal(nodes.get('plan-options')!.textContent, 'Mbappe · Ashworth');
    assert.equal(nodes.get('reply-form')!.hidden, false);
    assert.equal(nodes.get('add-plan')!.hidden, true);
  } finally { globalThis.document = original; }
});

test('event details render untrusted raw JSON as text', () => {
  const detail: NodeDouble = { textContent: '' };
  const original = globalThis.document;
  useDocument(() => detail);
  try {
    new LabView().inspectEvent({ seq: 4, canonical: { event_type: 'pass', player_id: '<script>alert(1)</script>' } });
    assert.deepEqual(JSON.parse(detail.textContent), { event_type: 'pass', player_id: '<script>alert(1)</script>' });
  } finally { globalThis.document = original; }
});

test('match selector lists matches once and names teams from the listing', () => {
  const options: NodeDouble[][] = [];
  const nodes = new Map<string, NodeDouble & { value?: string; dataset?: Record<string, string> }>();
  const original = globalThis.document;
  useDocument(id => {
    if (!nodes.has(id)) nodes.set(id, { textContent: '', dataset: {}, replaceChildren(...children: NodeDouble[]) { options.push(children); } });
    return nodes.get(id);
  });
  try {
    const view = new LabView();
    const matches = [{ match_id: 'm1', status: 'live', teams: [{ name: 'Riverton Rovers' }, { name: 'Forgeham United' }] }, { match_id: 'm2', fixture: 'redcastle-whitmore', status: 'scheduled' }];
    view.matches(matches, 'm1');
    view.matches(matches, 'm1');
    assert.equal(options.length, 1);
    assert.deepEqual(options[0]!.map(option => option.textContent), ['Riverton Rovers v Forgeham United · Live', 'redcastle-whitmore · Scheduled']);
    assert.equal(nodes.get('match-select')!.value, 'm1');
    view.match(matches[0]);
    assert.equal(nodes.get('home-team')!.textContent, 'Riverton Rovers');
    assert.match(nodes.get('recording-meta')!.textContent, /^m1 · /);
  } finally { globalThis.document = original; }
});

test('rules can be prepared while a match is live; nothing waits for a replay', () => {
  const nodes = new Map<string, NodeDouble>();
  const original = globalThis.document;
  useDocument(id => {
    if (!nodes.has(id)) nodes.set(id, { textContent: '', replaceChildren() {} });
    return nodes.get(id);
  });
  try {
    const view = new LabView();
    view.controls({ seq: 12, llm: { configured: true } }, false);
    assert.equal(nodes.get('prepare')!.disabled, false);
    view.controls(null, false);
    assert.equal(nodes.get('prepare')!.disabled, true);
    assert.equal(nodes.has('start') || nodes.has('load-recording'), false);
  } finally { globalThis.document = original; }
});

test('header score shows the published values and hides without them', () => {
  const score: NodeDouble = { textContent: '', hidden: true };
  const original = globalThis.document;
  useDocument(id => (id === 'score' ? score : undefined));
  try {
    const view = new LabView();
    view.score([{ id: 'h', name: 'Riverton Rovers', score: 1 }, { id: 'a', name: 'Forgeham United', score: 0 }]);
    assert.equal(score.textContent, 'Riverton Rovers 1 – 0 Forgeham United');
    assert.equal(score.hidden, false);
    view.score([{ id: 'h', name: 'Riverton Rovers', score: null }, { id: 'a', name: 'Forgeham United', score: 0 }]);
    assert.equal(score.hidden, true);
    view.score(null);
    assert.equal(score.hidden, true);
  } finally { globalThis.document = original; }
});
