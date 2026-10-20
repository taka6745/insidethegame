import test from 'node:test';
import assert from 'node:assert/strict';
import { FilterLab } from '../lab/controller.ts';
import type { LabApi } from '../lab/api.ts';
import type { LabView } from '../lab/view.ts';
import type { PlanResult } from '../lab/types.ts';
import { deferred, stub } from './support.ts';

const lab = (api: object, view: object) => new FilterLab(stub<LabApi>(api), stub<LabView>(view));

test('follow-up sends server conversation ID and uses clarified goal as card label', async () => {
  const calls: unknown[][] = [];
  const plans: PlanResult[] = [
    { status: 'clarification', conversation_id: 'c1', message: 'Which player?' },
    { status: 'ready', conversation_id: 'c1', goal: { description: 'Mbappe headed shots after 60 minutes' }, rule: { operation: 'count' } },
    { status: 'unsupported', message: 'Not available' },
  ];
  const filter = lab({ plan: async (...args: unknown[]) => { calls.push(args); return plans.shift(); } }, { plan() {} });
  await filter.requestPlan('Track his headed shots after 60 minutes');
  assert.equal(filter.prepared, null);
  await filter.requestPlan('Mbappe', true);
  assert.deepEqual(calls[1], ['Mbappe', 'c1']);
  assert.equal(filter.planLabel, 'Mbappe headed shots after 60 minutes');
  assert.deepEqual(filter.prepared, { operation: 'count' });
  await filter.requestPlan('Track pressure');
  assert.deepEqual(calls[2], ['Track pressure', null]);
  assert.equal(filter.conversationId, null);
  assert.equal(filter.prepared, null);
});

test('long goal descriptions fit the API card label limit', async () => {
  const description = 'A detailed statistic '.repeat(20);
  const filter = lab({ plan: async () => ({ status: 'ready', goal: { description }, rule: {} }) }, { plan() {} });
  await filter.requestPlan('Track corners');
  assert.equal(filter.planLabel, description.slice(0, 160));
});

test('a failed follow-up preserves retry UI unless the conversation expired', async () => {
  const rendered: PlanResult[] = [];
  const filter = lab({}, { error() {}, controls() {}, plan: (plan: PlanResult) => rendered.push(plan) });
  filter.conversationId = 'c1';
  await filter.action('plan', async () => { throw new Error('Network unavailable'); });
  assert.equal(rendered.at(-1)!.conversation_id, 'c1');
  await filter.action('plan', async () => { throw Object.assign(new Error('Expired'), { code: 'conversation_expired' }); });
  assert.equal(rendered.at(-1)!.conversation_id, null);
});

test('old event response cannot overwrite a newer event or rule inspection', async () => {
  const first = deferred();
  const second = deferred();
  const rendered: unknown[] = [];
  const filter = lab({ event: (index: number) => index === 0 ? first.promise : second.promise }, {
    inspectEventLoading() {}, inspectEvent: (payload: unknown) => rendered.push(payload), inspect: (rule: unknown) => rendered.push(rule),
  });
  const older = filter.inspectEvent(0);
  const newer = filter.inspectEvent(1);
  second.resolve({ delivery_index: 1 });
  await newer;
  filter.inspectRule({ label: 'Rule' });
  first.resolve({ delivery_index: 0 });
  await older;
  assert.deepEqual(rendered, [{ delivery_index: 1 }, { label: 'Rule' }]);
});

test('closing an event inspection invalidates a pending payload', async () => {
  const pending = deferred();
  const rendered: unknown[] = [];
  const filter = lab({ event: () => pending.promise }, {
    inspectEventLoading() {}, inspectEvent: (payload: unknown) => rendered.push(payload),
  });
  const request = filter.inspectEvent(0);
  filter.inspectionSequence++; // Same invalidation performed by the dialog close event.
  pending.resolve({ delivery_index: 0 });
  await request;
  assert.deepEqual(rendered, []);
});
