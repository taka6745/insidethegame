import type { ConnectionState, Timers, TimerId } from "./types.ts";
import { isRecord } from "./types.ts";

/** The browser WebSocket surface this adapter uses; tests supply doubles. */
export type LiveSocket = Pick<WebSocket, "onopen" | "onmessage" | "onerror" | "onclose" | "close">;
export interface LiveOptions {
  createSocket?: (url: string) => LiveSocket;
  timers?: Timers;
  random?: () => number;
  onSnapshot: (message: Record<string, unknown>) => void;
  onState: (state: ConnectionState) => void;
}

/** One socket per viewer. Reconnect gets a complete snapshot, never an unbounded delta queue. */
export class LiveConnection {
  createSocket: (url: string) => LiveSocket;
  timers: Timers;
  random: () => number;
  onSnapshot: (message: Record<string, unknown>) => void;
  onState: (state: ConnectionState) => void;
  socket: LiveSocket | null;
  retry: TimerId;
  watchdog: TimerId;
  attempt: number;
  generation: number;
  url: string;
  constructor({
    createSocket = (url) => new WebSocket(url),
    timers = globalThis,
    random = Math.random,
    onSnapshot,
    onState,
  }: LiveOptions) {
    this.createSocket = createSocket;
    this.timers = timers;
    this.random = random;
    this.onSnapshot = onSnapshot;
    this.onState = onState;
    this.socket = null;
    this.retry = null;
    this.watchdog = null;
    this.attempt = 0;
    this.generation = 0;
    this.url = "";
  }
  connect(url: string) {
    this.stop();
    this.url = url;
    this.attempt = 0;
    this.open(this.generation);
  }
  open(generation: number) {
    if (generation !== this.generation) return;
    this.onState(this.attempt ? "reconnecting" : "connecting");
    let socket: LiveSocket;
    try {
      socket = this.createSocket(this.url);
    } catch {
      this.schedule(generation);
      return;
    }
    this.socket = socket;
    this.armWatchdog(socket);
    socket.onopen = () => {
      if (generation === this.generation) this.armWatchdog(socket);
    };
    socket.onmessage = (event) => {
      if (generation !== this.generation) return;
      this.armWatchdog(socket);
      let message: unknown;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (!isRecord(message) || message.type !== "snapshot") return;
      this.attempt = 0;
      this.onSnapshot(message);
      this.onState("live");
    };
    socket.onerror = () => {
      if (generation === this.generation) this.onState("reconnecting");
    };
    socket.onclose = (event) => {
      if (generation !== this.generation) return;
      this.timers.clearTimeout(this.watchdog);
      this.socket = null;
      if ([4001, 4009].includes(event.code)) {
        this.onState("replaced");
        return;
      }
      // The match was purged or never existed: never reconnect to it.
      if (event.code === 4404) {
        this.onState("gone");
        return;
      }
      this.schedule(generation);
    };
  }
  armWatchdog(socket: LiveSocket) {
    this.timers.clearTimeout(this.watchdog);
    this.watchdog = this.timers.setTimeout(() => {
      this.onState("stale");
      socket.close();
    }, 45000);
  }
  schedule(generation: number) {
    this.attempt += 1;
    // After 8 failures it says offline but keeps trying every ~30 s; a live match comes back by itself.
    this.onState(this.attempt > 8 ? "offline" : "reconnecting");
    const delay =
      Math.min(30000, 500 * 2 ** (this.attempt - 1)) *
      (0.75 + this.random() * 0.5);
    this.retry = this.timers.setTimeout(() => this.open(generation), delay);
  }
  stop() {
    this.generation += 1;
    this.timers.clearTimeout(this.retry);
    this.timers.clearTimeout(this.watchdog);
    if (this.socket) {
      this.socket.onclose = null;
      this.socket.close();
      this.socket = null;
    }
  }
}
