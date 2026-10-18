import test from 'node:test';
import assert from 'node:assert/strict';
import { FilterLab } from '../lab/controller.js';

const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

test('follow-up sends server conversation ID and uses clarified goal as card label', async () => {
  const calls = [];
  const plans = [
    { status: 'clarification', conversation_id: 'c1', message: 'Which player?' },
    { status: 'ready', conversation_id: 'c1', goal: { description: 'Mbappe headed shots after 60 minutes' }, rule: { operation: 'count' } },
    { status: 'unsupported', message: 'Not available' },
  ];
  const lab = new FilterLab({ plan: async (...args) => { calls.push(args); return plans.shift(); } }, { plan() {} });
  await lab.requestPlan('Track his headed shots after 60 minutes');
  assert.equal(lab.prepared, null);
  await lab.requestPlan('Mbappe', true);
  assert.deepEqual(calls[1], ['Mbappe', 'c1']);
  assert.equal(lab.planLabel, 'Mbappe headed shots after 60 minutes');
  assert.deepEqual(lab.prepared, { operation: 'count' });
  await lab.requestPlan('Track pressure');
  assert.deepEqual(calls[2], ['Track pressure', null]);
  assert.equal(lab.conversationId, null);
  assert.equal(lab.prepared, null);
});

test('long goal descriptions fit the API card label limit', async () => {
  const description = 'A detailed statistic '.repeat(20);
  const lab = new FilterLab({ plan: async () => ({ status: 'ready', goal: { description }, rule: {} }) }, { plan() {} });
  await lab.requestPlan('Track corners');
  assert.equal(lab.planLabel, description.slice(0, 160));
});

test('a failed follow-up preserves retry UI unless the conversation expired', async () => {
  const rendered = [];
  const lab = new FilterLab({}, { error() {}, controls() {}, plan: plan => rendered.push(plan) });
  lab.conversationId = 'c1';
  await lab.action('plan', async () => { throw new Error('Network unavailable'); });
  assert.equal(rendered.at(-1).conversation_id, 'c1');
  await lab.action('plan', async () => { throw Object.assign(new Error('Expired'), { code: 'conversation_expired' }); });
  assert.equal(rendered.at(-1).conversation_id, null);
});

test('old event response cannot overwrite a newer event or rule inspection', async () => {
  const first = deferred();
  const second = deferred();
  const rendered = [];
  const lab = new FilterLab({ event: index => index === 0 ? first.promise : second.promise }, {
    inspectEventLoading() {}, inspectEvent: payload => rendered.push(payload), inspect: rule => rendered.push(rule),
  });
  const older = lab.inspectEvent(0);
  const newer = lab.inspectEvent(1);
  second.resolve({ delivery_index: 1 });
  await newer;
  lab.inspectRule({ label: 'Rule' });
  first.resolve({ delivery_index: 0 });
  await older;
  assert.deepEqual(rendered, [{ delivery_index: 1 }, { label: 'Rule' }]);
});

test('closing an event inspection invalidates a pending payload', async () => {
  const pending = deferred();
  const rendered = [];
  const lab = new FilterLab({ event: () => pending.promise }, {
    inspectEventLoading() {}, inspectEvent: payload => rendered.push(payload),
  });
  const request = lab.inspectEvent(0);
  lab.inspectionSequence++; // Same invalidation performed by the dialog close event.
  pending.resolve({ delivery_index: 0 });
  await request;
  assert.deepEqual(rendered, []);
});
