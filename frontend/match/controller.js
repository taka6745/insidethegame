import { currentSnapshot } from "./format.js";

export class MatchController {
  constructor({
    api,
    view,
    questions,
    live,
    storage,
    uuid = () => crypto.randomUUID(),
    schedule = (callback) => requestAnimationFrame(callback),
    timers = globalThis,
  }) {
    Object.assign(this, {
      api,
      view,
      questions,
      live,
      storage,
      uuid,
      schedule,
      timers,
    });
    this.generation = 0;
    this.token = null;
    this.snapshot = null;
    this.retiredEpochs = new Set();
    this.session = null;
    this.pendingTimer = null;
    this.pendingAttempts = 0;
    this.busy = false;
    this.framePending = false;
    this.retry = null;
    view.onUnpin = (id) => this.unpin(id);
    questions.onTrack = (id) => this.track(id);
  }
  async start({ restore = false } = {}) {
    const result = await this.api.profiles();
    this.profile = this.view.profiles(
      result.profiles,
      this.storage.getItem("match-profile"),
    );
    if (!this.profile) throw new Error("No demo profiles are available yet.");
    await this.connect({ restore });
  }
  async connect({ restore = false } = {}) {
    if (!this.profile) {
      try {
        return await this.start({ restore });
      } catch (error) {
        this.view.error(error.message);
        this.view.connection("offline");
        return;
      }
    }
    const generation = ++this.generation;
    this.timers.clearTimeout(this.pendingTimer);
    this.pendingAttempts = 0;
    this.live.stop();
    this.token = null;
    this.busy = false;
    this.snapshot = null;
    this.retry = null;
    this.view.error("");
    this.view.connection("connecting");
    this.questions.status("Connecting to your match…", true);
    this.questions.render({ turns: [], offers: [] });
    try {
      const saved = restore
        ? this.storage.getItem(`match-session:${this.profile}`)
        : null;
      const session = saved
        ? await this.api.restore(saved)
        : await this.api.session(this.profile);
      if (generation !== this.generation) return;
      this.token = session.session_token;
      this.session = session;
      this.storage.setItem(`match-session:${this.profile}`, this.token);
      this.showChat(session);
      this.receive(session.snapshot);
      this.live.connect(this.api.socketUrl(this.token));
    } catch (error) {
      if (generation !== this.generation) return;
      this.view.connection(
        error.code === "session_replaced" || error.status === 409
          ? "replaced"
          : "offline",
      );
      this.view.error(error.message);
      this.questions.status("Reconnect to ask about the match.", true);
    }
  }
  selectProfile(profile) {
    this.profile = profile;
    this.storage.setItem("match-profile", profile);
    return this.connect();
  }
  receive(message) {
    if (
      message?.projection_epoch &&
      this.retiredEpochs.has(message.projection_epoch)
    )
      return;
    const next = currentSnapshot(this.snapshot, message);
    if (next === this.snapshot) return;
    const previousEpoch = this.snapshot?.projection_epoch;
    if (
      previousEpoch &&
      next.projection_epoch &&
      previousEpoch !== next.projection_epoch
    ) {
      this.retiredEpochs.add(previousEpoch);
      if (this.retiredEpochs.size > 8)
        this.retiredEpochs.delete(this.retiredEpochs.values().next().value);
    }
    this.snapshot = next;
    if (this.framePending) return;
    this.framePending = true;
    this.schedule(() => {
      this.framePending = false;
      if (this.snapshot) this.view.render(this.snapshot);
    });
  }
  connection(state) {
    this.view.connection(state);
    if (state === "replaced") {
      this.timers.clearTimeout(this.pendingTimer);
      this.token = null;
      this.generation += 1;
      this.busy = false;
      this.questions.status("This session ended. Reconnect to continue.", true);
    }
  }
  showChat(session) {
    this.session = session;
    this.questions.render(session);
    const pending = session.turns?.some((turn) => turn.status === "pending");
    this.questions.status(
      pending
        ? "An answer is still processing…"
        : "Answers grounded in this match",
      Boolean(pending),
    );
    this.timers.clearTimeout(this.pendingTimer);
    if (!pending) {
      this.pendingAttempts = 0;
      return;
    }
    if (this.pendingAttempts >= 30) {
      this.questions.status(
        "The answer is taking longer than expected. Reconnect to check it.",
        true,
      );
      return;
    }
    const generation = this.generation,
      token = this.token;
    this.pendingTimer = this.timers.setTimeout(
      () => this.refreshPending(token, generation),
      2000,
    );
  }
  async refreshPending(token, generation) {
    this.pendingAttempts += 1;
    try {
      const session = await this.api.restore(token);
      if (generation === this.generation) this.showChat(session);
    } catch (error) {
      if (generation === this.generation) {
        this.view.error(error.message);
        this.questions.status("Reconnect to restore the answer.", true);
      }
    }
  }
  async send(prompt) {
    prompt = prompt.trim();
    if (!prompt || this.busy || !this.token) return;
    const generation = this.generation,
      token = this.token;
    this.busy = true;
    this.view.error("");
    this.questions.status("Checking stats and the match story…", true);
    this.questions.render({
      ...this.session,
      turns: [...(this.session.turns || []), { prompt, status: "pending" }],
    });
    const requestId =
      this.retry?.prompt === prompt ? this.retry.id : this.uuid();
    this.retry = { prompt, id: requestId };
    try {
      await this.api.ask(token, prompt, requestId);
      const session = await this.api.restore(token);
      if (generation !== this.generation) return;
      this.retry = null;
      this.showChat(session);
      this.receive(session.snapshot);
    } catch (error) {
      if (generation !== this.generation) return;
      this.questions.render(this.session);
      this.questions.status(
        "Could not complete that answer. Your question is ready to retry.",
      );
      this.view.error(error.message);
      this.onRetryPrompt?.(prompt);
    } finally {
      if (generation === this.generation) this.busy = false;
    }
  }
  async track(id) {
    if (!this.token) return;
    const generation = this.generation,
      token = this.token;
    try {
      const result = await this.api.track(token, id);
      const session = await this.api.restore(token);
      if (generation !== this.generation) return;
      this.showChat(session);
      this.receive(result.snapshot);
      this.view.error("");
    } catch (error) {
      if (generation === this.generation) this.view.error(error.message);
    }
  }
  async unpin(id) {
    if (!this.token) return;
    const generation = this.generation,
      token = this.token;
    try {
      await this.api.unpin(token, id);
      const session = await this.api.restore(token);
      if (generation !== this.generation) return;
      this.showChat(session);
      this.receive(session.snapshot);
      this.view.error("");
    } catch (error) {
      if (generation === this.generation) this.view.error(error.message);
    }
  }
  async demo(reset = false) {
    try {
      if (reset) {
        await this.api.resetDemo();
        await this.start();
      }
      await this.api.startDemo();
      this.view.error("");
    } catch (error) {
      this.view.error(error.message);
    }
  }
  stop() {
    this.generation += 1;
    this.timers.clearTimeout(this.pendingTimer);
    this.live.stop();
  }
}
