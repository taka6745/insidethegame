import test from 'node:test';
import assert from 'node:assert/strict';
import { LabView } from '../lab/view.js';

test('reuse response displays its explanation without an Add action or fabricated rule', () => {
  const nodes = new Map(['plan-result', 'plan-message', 'plan-rule', 'add-plan', 'plan-options', 'reply-form', 'reply-label', 'plan-rule-details'].map(id => [id, { textContent: '', hidden: false }]));
  const original = globalThis.document;
  globalThis.document = { getElementById: id => nodes.get(id) };
  try {
    new LabView().plan({ status: 'reuse', message: 'ETL already provides this standard stat.', rule: null });
    assert.equal(nodes.get('plan-result').hidden, false);
    assert.equal(nodes.get('plan-message').textContent, 'ETL already provides this standard stat.');
    assert.equal(nodes.get('plan-rule').textContent, '');
    assert.equal(nodes.get('plan-rule').hidden, true);
    assert.equal(nodes.get('add-plan').hidden, true);
  } finally { globalThis.document = original; }
});

test('clarification shows question and reply form without an executable rule', () => {
  const nodes = new Map(['plan-result', 'plan-message', 'plan-rule', 'add-plan', 'plan-options', 'reply-form', 'reply-label', 'plan-rule-details'].map(id => [id, { textContent: '', hidden: false }]));
  const original = globalThis.document;
  globalThis.document = { getElementById: id => nodes.get(id) };
  try {
    new LabView().plan({ status: 'clarification', conversation_id: 'opaque', clarification: { question: 'Which player?', options: ['Mbappe', 'Palmer'] } });
    assert.equal(nodes.get('plan-message').textContent, 'Which player?');
    assert.equal(nodes.get('plan-options').textContent, 'Mbappe · Palmer');
    assert.equal(nodes.get('reply-form').hidden, false);
    assert.equal(nodes.get('add-plan').hidden, true);
  } finally { globalThis.document = original; }
});

test('event details render untrusted raw JSON as text', () => {
  const detail = { textContent: '' };
  const original = globalThis.document;
  globalThis.document = { getElementById: () => detail };
  try {
    new LabView().inspectEvent({ raw: { text: '<script>alert(1)</script>' }, canonical: { event_type: 'pass' } });
    assert.deepEqual(JSON.parse(detail.textContent), { raw: { text: '<script>alert(1)</script>' }, canonical: { event_type: 'pass' } });
  } finally { globalThis.document = original; }
});

test('recording metadata uses the loaded filename and real delivery counts', () => {
  const nodes = new Map(['home-team', 'away-team', 'recording-name', 'recording-meta', 'presets', 'preset-description'].map(id => [id, { textContent: '', replaceChildren() {} }]));
  const original = globalThis.document;
  globalThis.document = { getElementById: id => nodes.get(id) };
  try {
    new LabView().scenario({ teams: [], presets: [], recording: { filename: 'my-match.json', format: 'Opta-inspired', synthetic: true, delivery_count: 45, event_count: 42 } });
    assert.equal(nodes.get('recording-name').textContent, 'my-match.json');
    assert.equal(nodes.get('recording-meta').textContent, 'Synthetic fixture · Opta-inspired · 45 deliveries · 42 events');
  } finally { globalThis.document = original; }
});
