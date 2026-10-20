/** One socket per viewer. Reconnect gets a complete snapshot, never an unbounded delta queue. */
export class LiveConnection {
  constructor({
    createSocket = (url) => new WebSocket(url),
    timers = globalThis,
    random = Math.random,
    onSnapshot,
    onState,
  }) {
    Object.assign(this, { createSocket, timers, random, onSnapshot, onState });
    this.socket = null;
    this.retry = null;
    this.watchdog = null;
    this.attempt = 0;
    this.generation = 0;
  }
  connect(url) {
    this.stop();
    this.url = url;
    this.attempt = 0;
    this.open(this.generation);
  }
  open(generation) {
    if (generation !== this.generation) return;
    this.onState(this.attempt ? "reconnecting" : "connecting");
    let socket;
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
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (message.type !== "snapshot") return;
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
      this.schedule(generation);
    };
  }
  armWatchdog(socket) {
    this.timers.clearTimeout(this.watchdog);
    this.watchdog = this.timers.setTimeout(() => {
      this.onState("stale");
      socket.close();
    }, 45000);
  }
  schedule(generation) {
    this.attempt += 1;
    if (this.attempt > 8) {
      this.onState("offline");
      return;
    }
    this.onState("reconnecting");
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
