import test from 'node:test';
import assert from 'node:assert/strict';
import { LabApi } from '../lab/api.ts';
import { setFetch, stub } from './support.ts';

test('clarification reply sends opaque conversation ID without client history', async () => {
  const original = globalThis.fetch;
  setFetch(async (url, options) => {
    assert.deepEqual(JSON.parse(String(options.body)), { prompt: 'Mbappe', conversation_id: 'c1' });
    return new Response(JSON.stringify({ status: 'ready' }));
  });
  try { await new LabApi().plan('Mbappe', 'c1'); }
  finally { globalThis.fetch = original; }
});

test('structured rules are sent unchanged to the backend', async () => {
  const rule = { operation: 'count', where: { event_type: 'corner', match_time_seconds: { greater_than: 3600 } } };
  const original = globalThis.fetch;
  setFetch(async (url, options) => {
    assert.equal(url, '/api/matches/m1/calculations');
    assert.equal(options.method, 'POST');
    assert.deepEqual(JSON.parse(String(options.body)), { rule });
    return new Response(JSON.stringify({ id: 'calc-45', value: 0 }), { status: 201 });
  });
  try { assert.equal((await new LabApi('/api', 'm1').add(rule)).id, 'calc-45'); }
  finally { globalThis.fetch = original; }
});

test('failed planner requests remain errors rather than fake rules', async () => {
  const original = globalThis.fetch;
  setFetch(async () => new Response(JSON.stringify({ detail: 'Local model unavailable' }), { status: 503 }));
  try { await assert.rejects(new LabApi().plan('corners'), /Local model unavailable/); }
  finally { globalThis.fetch = original; }
});

test('event inspection requests the received delivery index', async () => {
  const original = globalThis.fetch;
  setFetch(async (url, options) => {
    assert.equal(url, '/api/matches/m1/events/3');
    assert.equal(options.method, 'GET');
    return new Response(JSON.stringify({ delivery_index: 3, raw: { typeId: 1 }, canonical: { event_type: 'pass' } }));
  });
  try { assert.equal(stub<{ event_type: string }>((await new LabApi('/api', 'm1').event(3)).canonical).event_type, 'pass'); }
  finally { globalThis.fetch = original; }
});

test('the lab lists matches from the backend listing, never the feed', async () => {
  const original = globalThis.fetch;
  setFetch(async (url) => {
    assert.equal(url, '/viewer-api/matches');
    return new Response(JSON.stringify([{ match_id: 'm1', status: 'live' }]));
  });
  try { assert.equal((await new LabApi().matches())[0]!.match_id, 'm1'); }
  finally { globalThis.fetch = original; }
});
