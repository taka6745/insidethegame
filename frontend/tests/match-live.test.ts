import test from "node:test";
import assert from "node:assert/strict";
import { LiveConnection } from "../match/live.ts";
import type { LiveSocket } from "../match/live.ts";
import type { ConnectionState, Timers } from "../match/types.ts";
import { stub } from "./support.ts";

interface SocketDouble {
  url: string;
  closed?: boolean;
  close(): void;
  onopen(): void;
  onmessage(event: { data: string }): void;
  onclose(event: { code: number }): void;
}
function fixture() {
  const jobs = new Map<number, { fn: () => void; delay: number }>(),
    sockets: SocketDouble[] = [],
    states: ConnectionState[] = [],
    snapshots: unknown[] = [];
  let id = 0;
  const timers = {
    setTimeout(fn: () => void, delay: number) {
      jobs.set(++id, { fn, delay });
      return id;
    },
    clearTimeout(key: number) {
      jobs.delete(key);
    },
  };
  const live = new LiveConnection({
    timers: stub<Timers>(timers),
    random: () => 0.5,
    createSocket(url) {
      const double: Pick<SocketDouble, "url" | "closed" | "close"> = {
        url,
        close() {
          this.closed = true;
        },
      };
      const socket = stub<SocketDouble>(double);
      sockets.push(socket);
      return stub<LiveSocket>(socket);
    },
    onSnapshot: (value) => snapshots.push(value),
    onState: (value) => states.push(value),
  });
  return { live, jobs, sockets, states, snapshots };
}
test("one socket, bounded reconnect delay, terminal takeover does not reconnect", () => {
  const f = fixture();
  f.live.connect("ws://local/live");
  f.sockets[0]!.onclose({ code: 1006 });
  assert.equal([...f.jobs.values()][0]!.delay, 500);
  [...f.jobs.values()][0]!.fn();
  assert.equal(f.sockets.length, 2);
  f.sockets[1]!.onclose({ code: 4001 });
  assert.equal(f.states.at(-1), "replaced");
  assert.equal(f.live.attempt, 1);
});
test("heartbeats maintain liveness without rerendering or resetting retry budget", () => {
  const f = fixture();
  f.live.connect("ws://local/live");
  const socket = f.sockets[0]!;
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
  const old = f.sockets[0]!;
  f.live.connect("ws://new");
  assert.equal(old.closed, true);
  old.onmessage({ data: '{"type":"snapshot","version":999}' });
  assert.equal(f.snapshots.length, 0);
});
test("silent connection becomes stale and closes after watchdog", () => {
  const f = fixture();
  f.live.connect("ws://local");
  f.sockets[0]!.onopen();
  const job = [...f.jobs.values()][0]!;
  assert.equal(job.delay, 45000);
  job.fn();
  assert.equal(f.states.at(-1), "stale");
  assert.equal(f.sockets[0]!.closed, true);
});
test("after eight reconnects it shows offline but keeps retrying at the cap; stop cancels pending work", () => {
  const f = fixture();
  f.live.connect("ws://local");
  for (let index = 0; index < 10; index++) {
    f.sockets.at(-1)!.onclose({ code: 1006 });
    if (index === 9) break;
    const job = [...f.jobs.values()].at(-1)!;
    f.jobs.clear();
    job.fn();
  }
  assert.equal(f.states.at(-1), "offline");
  assert.equal(f.sockets.length, 10);
  assert.deepEqual([...f.jobs.values()].map((job) => job.delay), [30000]);
  f.live.stop();
  assert.equal(f.jobs.size, 0);
});
test("close 4404 means the match is gone: no reconnect", () => {
  const f = fixture();
  f.live.connect("ws://local/viewer-api/matches/m1/sessions/t/live");
  f.sockets[0]!.onclose({ code: 4404 });
  assert.equal(f.states.at(-1), "gone");
  assert.equal(f.jobs.size, 0);
  assert.equal(f.sockets.length, 1);
});
