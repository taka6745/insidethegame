import test from 'node:test';
import assert from 'node:assert/strict';
import { FilterLab } from '../lab/controller.js';

const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

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
