import test from 'node:test';
import assert from 'node:assert/strict';
import { LabView } from '../lab/view.js';

test('reuse response displays its explanation without an Add action or fabricated rule', () => {
  const nodes = new Map(['plan-result', 'plan-message', 'plan-rule', 'add-plan'].map(id => [id, { textContent: '', hidden: false }]));
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
