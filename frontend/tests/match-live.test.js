import test from "node:test";
import assert from "node:assert/strict";
import { LiveConnection } from "../match/live.js";

function fixture() {
  const jobs = new Map(),
    sockets = [],
    states = [],
    snapshots = [];
  let id = 0;
  const timers = {
    setTimeout(fn, delay) {
      jobs.set(++id, { fn, delay });
      return id;
    },
    clearTimeout(key) {
      jobs.delete(key);
    },
  };
  const live = new LiveConnection({
    timers,
    random: () => 0.5,
    createSocket(url) {
      const socket = {
        url,
        close() {
          this.closed = true;
        },
      };
      sockets.push(socket);
      return socket;
    },
    onSnapshot: (value) => snapshots.push(value),
    onState: (value) => states.push(value),
  });
  return { live, jobs, sockets, states, snapshots };
}
test("one socket, bounded reconnect delay, terminal takeover does not reconnect", () => {
  const f = fixture();
  f.live.connect("ws://local/live");
  f.sockets[0].onclose({ code: 1006 });
  assert.equal([...f.jobs.values()][0].delay, 500);
  [...f.jobs.values()][0].fn();
  assert.equal(f.sockets.length, 2);
  f.sockets[1].onclose({ code: 4001 });
  assert.equal(f.states.at(-1), "replaced");
  assert.equal(f.live.attempt, 1);
});
test("heartbeats maintain liveness without rerendering or resetting retry budget", () => {
  const f = fixture();
  f.live.connect("ws://local/live");
  const socket = f.sockets[0];
  socket.onopen();
  socket.onmessage({ data: '{"type":"heartbeat"}' });
  assert.equal(f.snapshots.length, 0);
  assert.equal(f.jobs.size, 1);
  socket.onmessage({ data: '{"type":"snapshot","version":3}' });
  assert.equal(f.snapshots.length, 1);
  assert.equal(f.states.at(-1), "live");
});
test("old socket callbacks cannot update a switched profile", () => {
  const f = fixture();
  f.live.connect("ws://old");
  const old = f.sockets[0];
  f.live.connect("ws://new");
  assert.equal(old.closed, true);
  old.onmessage({ data: '{"type":"snapshot","version":999}' });
  assert.equal(f.snapshots.length, 0);
});
test("silent connection becomes stale and closes after watchdog", () => {
  const f = fixture();
  f.live.connect("ws://local");
  f.sockets[0].onopen();
  const job = [...f.jobs.values()][0];
  assert.equal(job.delay, 45000);
  job.fn();
  assert.equal(f.states.at(-1), "stale");
  assert.equal(f.sockets[0].closed, true);
});
test("retry budget stops after eight reconnects and stop cancels pending work", () => {
  const f = fixture();
  f.live.connect("ws://local");
  for (let index = 0; index < 9; index++) {
    f.sockets.at(-1).onclose({ code: 1006 });
    const job = [...f.jobs.values()].at(-1);
    f.jobs.clear();
    if (index < 8) job.fn();
  }
  assert.equal(f.states.at(-1), "offline");
  assert.equal(f.sockets.length, 9);
  f.live.stop();
  assert.equal(f.jobs.size, 0);
});
