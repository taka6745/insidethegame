import test from 'node:test';
import assert from 'node:assert/strict';
import { LabApi } from '../lab/api.js';

test('structured rules are sent unchanged to the backend', async () => {
  const rule = { operation: 'count', where: { event_type: 'corner', match_time_seconds: { greater_than: 3600 } } };
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/calculations');
    assert.equal(options.method, 'POST');
    assert.deepEqual(JSON.parse(options.body), { rule });
    return new Response(JSON.stringify({ id: 'calc-45', value: 0 }), { status: 201 });
  };
  try { assert.equal((await new LabApi().add(rule)).id, 'calc-45'); }
  finally { globalThis.fetch = original; }
});

test('failed planner requests remain errors rather than fake rules', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Local model unavailable' }), { status: 503 });
  try { await assert.rejects(new LabApi().plan('corners'), /Local model unavailable/); }
  finally { globalThis.fetch = original; }
});
