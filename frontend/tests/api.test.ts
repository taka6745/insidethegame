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
    assert.equal(url, '/api/calculations');
    assert.equal(options.method, 'POST');
    assert.deepEqual(JSON.parse(String(options.body)), { rule });
    return new Response(JSON.stringify({ id: 'calc-45', value: 0 }), { status: 201 });
  });
  try { assert.equal((await new LabApi().add(rule)).id, 'calc-45'); }
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
    assert.equal(url, '/api/events/3');
    assert.equal(options.method, 'GET');
    return new Response(JSON.stringify({ delivery_index: 3, raw: { typeId: 1 }, canonical: { event_type: 'pass' } }));
  });
  try { assert.equal(stub<{ event_type: string }>((await new LabApi().event(3)).canonical).event_type, 'pass'); }
  finally { globalThis.fetch = original; }
});

test('recording upload sends original file bytes and an encoded filename', async () => {
  const original = globalThis.fetch;
  const file = stub<File>(Object.assign(new Blob(['{"synthetic":true}'], { type: 'application/json' }), { name: 'my recording.json' }));
  setFetch(async (url, options) => {
    assert.equal(url, '/api/recording');
    assert.equal(options.method, 'POST');
    assert.equal(options.headers['X-Recording-Filename'], 'my%20recording.json');
    assert.equal(options.body, file);
    return new Response(JSON.stringify({ scenario: {}, state: {} }));
  });
  try { assert.deepEqual(await new LabApi().loadRecording(file), { scenario: {}, state: {} }); }
  finally { globalThis.fetch = original; }
});

test('oversized recording is rejected before a network request', async () => {
  await assert.rejects(new LabApi().loadRecording(stub<File>({ size: 16 * 1024 * 1024 + 1 })), /16 MiB/);
});

test('recording validation errors preserve the backend explanation', async () => {
  const original = globalThis.fetch;
  setFetch(async () => new Response(JSON.stringify({ code: 'invalid_recording', message: 'Recordings must declare synthetic: true.' }), { status: 422 }));
  try { await assert.rejects(new LabApi().loadRecording(stub<File>({ size: 20, name: 'bad.json' })), /must declare synthetic: true/); }
  finally { globalThis.fetch = original; }
});
