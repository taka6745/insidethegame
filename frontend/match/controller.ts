import { currentSnapshot } from "./format.ts";
import { HeldUpdates } from "./hold.ts";
import { liveSource } from "./media.ts";
import type { MatchApi } from "./api.ts";
import type { AudienceView } from "./audience-view.ts";
import type { QuestionView } from "./chat-view.ts";
import type { LiveConnection } from "./live.ts";
import type { MatchView } from "./view.ts";
import type {
  Audience,
  ChatSession,
  ConnectionState,
  Replay,
  ServiceError,
  Snapshot,
  Timers,
  TimerId,
} from "./types.ts";
import { isRecord } from "./types.ts";

/** A moment playlist (follow or key-event clips) cut back to the clips a held state's picture has passed (none while its time is unknown). */
export function playlistUntil(playlist: Replay | null | undefined, seconds: number | null | undefined): Replay | null {
  if (!playlist || seconds == null) return null;
  const clips = playlist.clips.filter((clip) => clip.end <= seconds);
  return clips.length ? { ...playlist, clips, total_items: clips.length,
    seconds: clips.reduce((sum, clip) => sum + clip.end - clip.start, 0) } : null;
}

export type ControllerApi = Pick<
  MatchApi,
  | "profiles"
  | "session"
  | "restore"
  | "audience"
  | "ask"
  | "track"
  | "unpin"
  | "socketUrl"
  | "replayPage"
> & { match: string };
export type ControllerView = Pick<MatchView, "render" | "error" | "connection" | "onUnpin"> & {
  audience: Pick<AudienceView, "setBusy" | "render">;
};
export type ControllerQuestions = Pick<QuestionView, "render" | "status" | "onTrack" | "onReplayPage" | "onClarify">
  & Partial<Pick<QuestionView, "askedAt">>;
export interface ControllerOptions {
  api: ControllerApi;
  view: ControllerView;
  questions: ControllerQuestions;
  live: Pick<LiveConnection, "connect" | "stop">;
  storage: Pick<Storage, "getItem" | "setItem">;
  uuid?: () => string;
  schedule?: (callback: () => void) => unknown;
  timers?: Timers;
  /** Live video time; live states wait for it to reach their producer time. */
  playhead?: () => number | null;
  now?: () => number;
  /** The open match was purged or never existed; the page returns to the match picker. */
  onGone?: () => void;
}
/** A viewer's own change (audience, follow) answered with its new snapshot: show it now. */
export function applyOwnSnapshot(controller: Pick<MatchController, "receive" | "reframe" | "snapshot">, snapshot: unknown) {
  controller.receive(snapshot);
  controller.reframe(controller.snapshot);
}

/** Shown when the backend has no model: questions are refused, live insights continue. */
export const ANSWERS_UNAVAILABLE = "Answers unavailable right now · live insights and stats continue";

export class MatchController {
  api: ControllerApi;
  view: ControllerView;
  questions: ControllerQuestions;
  live: Pick<LiveConnection, "connect" | "stop">;
  storage: Pick<Storage, "getItem" | "setItem">;
  uuid: () => string;
  schedule: (callback: () => void) => unknown;
  timers: Timers;
  playhead: () => number | null;
  now: () => number;
  held: HeldUpdates<Snapshot>;
  holdTimer: TimerId;
  generation: number;
  token: string | null;
  snapshot: Snapshot | null;
  shown: Snapshot | null;
  retiredEpochs: Set<unknown>;
  session: ChatSession | null;
  pendingTimer: TimerId;
  pendingAttempts: number;
  busy: boolean;
  framePending: boolean;
  retry: { prompt: string; id: string } | null;
  audienceBusy: boolean;
  profile?: string | null;
  onRetryPrompt?: (prompt: string) => void;
  /** A session opened (also after waiting for kick-off). */
  onOpened?: () => void;
  /** The follow chat: reset on every connect, opened with each new session. */
  follows?: { open(session: ChatSession): void; reset(): void };
  onGone: () => void;
  constructor({
    api,
    view,
    questions,
    live,
    storage,
    uuid = () => crypto.randomUUID(),
    schedule = (callback) => requestAnimationFrame(callback),
    timers = globalThis,
    playhead = () => null,
    now = () => Date.now(),
    onGone = () => {},
  }: ControllerOptions) {
    this.onGone = onGone;
    this.api = api;
    this.view = view;
    this.questions = questions;
    this.live = live;
    this.storage = storage;
    this.uuid = uuid;
    this.schedule = schedule;
    this.timers = timers;
    this.playhead = playhead;
    this.now = now;
    this.held = new HeldUpdates();
    this.holdTimer = null;
    this.generation = 0;
    this.token = null;
    this.snapshot = null;
    this.shown = null;
    this.retiredEpochs = new Set();
    this.session = null;
    this.pendingTimer = null;
    this.pendingAttempts = 0;
    this.busy = false;
    this.framePending = false;
    this.retry = null;
    this.audienceBusy = false;
    view.onUnpin = (id) => this.unpin(id);
    questions.onTrack = (id) => this.track(id);
    questions.onClarify = (text) => this.send(text);
    questions.onReplayPage = (turnId, page) => {
      if (!this.token) return Promise.reject(new Error("Reconnect to load more clips."));
      return this.api.replayPage(this.token, turnId, page);
    };
  }
  /** Opening the page resumes this tab's saved session; `connect()` alone (Reconnect) takes over from another tab. */
  async start({ restore = true } = {}) {
    const result = await this.api.profiles();
    const saved = this.storage.getItem("match-profile");
    this.profile = result.profiles.find(profile => profile.id === saved)?.id
      || result.profiles[0]?.id;
    if (!this.profile) throw new Error("No demo profiles are available yet.");
    this.storage.setItem("match-profile", this.profile);
    await this.connect({ restore });
  }
  async connect({ restore = false } = {}): Promise<void> {
    if (!this.profile) {
      try {
        return await this.start({ restore });
      } catch (error) {
        this.view.error((error as ServiceError).message);
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
    this.audienceBusy = false;
    this.view.audience.setBusy(false);
    this.snapshot = null;
    this.shown = null;
    this.held.clear();
    this.retry = null;
    this.view.error("");
    this.view.connection("connecting");
    this.questions.status("Connecting to your match…", true);
    this.questions.render({ turns: [], offers: [] });
    this.follows?.reset();
    const key = `match-session:${this.api.match}:${this.profile}`;
    try {
      const saved = restore ? this.storage.getItem(key) : null;
      // A stale token is 404 too; only a 404 for a fresh session means the match is gone.
      const session = (saved
        ? await this.api.restore(saved).catch((error: ServiceError) => {
          if (error.status !== 404) throw error;
          return null;
        })
        : null) ?? await this.api.session(this.profile);
      if (generation !== this.generation) return;
      this.token = session.session_token;
      this.session = session;
      this.storage.setItem(key, this.token);
      this.showChat(session);
      this.receive(session.snapshot);
      this.follows?.open(session);
      this.live.connect(this.api.socketUrl(this.token));
      this.onOpened?.();
    } catch (caught) {
      if (generation !== this.generation) return;
      const error = caught as ServiceError;
      if (error.status === 404 && error.code === "match_not_started") return this.wait(generation);
      // Just opened: ETL has not served the match details yet.
      if (error.status === 503 && error.code === "snapshot_unavailable") return this.wait(generation, "connecting");
      if (error.status === 404) return this.connection("gone");
      this.view.connection(
        error.code === "session_replaced" || error.status === 409
          ? "replaced"
          : "offline",
      );
      this.view.error(error.message);
      this.questions.status("Reconnect to ask about the match.", true);
    }
  }
  /** Linked before its MA1 arrived (or its details): say so and try again until the match opens. */
  wait(generation: number, state: "waiting" | "connecting" = "waiting") {
    this.view.connection(state);
    this.questions.status(state === "waiting"
      ? "Questions open with the match, about a minute before kick-off." : "Connecting to your match…", true);
    this.pendingTimer = this.timers.setTimeout(() => {
      if (generation === this.generation) void this.connect();
    }, 5000);
  }
  async selectAudience(selection: Audience) {
    if (!this.token || this.audienceBusy) return;
    const generation = this.generation, token = this.token;
    this.audienceBusy = true;
    this.view.audience.setBusy(true);
    try {
      const session = await this.api.audience(token, selection);
      if (generation !== this.generation) return;
      applyOwnSnapshot(this, session.snapshot);
      this.view.error("");
    } catch (error) {
      if (generation !== this.generation) return;
      if (this.snapshot) this.view.audience.render(this.snapshot);
      this.view.error((error as ServiceError).message);
    } finally {
      if (generation === this.generation) {
        this.audienceBusy = false;
        this.view.audience.setBusy(false);
      }
    }
  }
  receive(message: unknown) {
    const epoch = isRecord(message) ? message.projection_epoch : undefined;
    if (epoch && this.retiredEpochs.has(epoch)) return;
    const next = currentSnapshot(this.snapshot, message);
    if (!next || next === this.snapshot) return;
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
    const media = next.match.media;
    this.held.push(next, liveSource(media) ? media!.seconds : null, this.now());
    this.release();
  }
  /** A viewer's own audience or follow change applies now: the shown and held states take its framing,
   * feed mode and narratives, each only up to its own clock, so nothing runs ahead of the picture. */
  reframe(next: Snapshot | null) {
    if (!next) return;
    const frame = (state: Snapshot): Snapshot => ({
      ...state, bucket_id: next.bucket_id, audience: next.audience,
      audience_buckets: next.audience_buckets, feed_mode: next.feed_mode, follow: next.follow,
      // Another match's clips run on that match's video; the server already bounds them to its played position.
      follow_playlist: next.follow_match ? next.follow_playlist ?? null
        : playlistUntil(next.follow_playlist, state.match.media?.seconds),
      moment_playlist: playlistUntil(next.moment_playlist, state.match.media?.seconds),
      narratives: next.narratives.filter((n) =>
        (n.period || 0) < (state.match.period || 0) || ((n.period || 0) === (state.match.period || 0)
          && Number(n.clock_seconds) <= Number(state.match.clock_seconds))),
    });
    for (const held of this.held.queue) held.item = frame(held.item);
    if (this.shown) this.view.render(this.shown = frame(this.shown));
  }
  /** Render the newest state the live picture has reached; recheck while any is held. */
  release() {
    if (this.framePending) return;
    this.framePending = true;
    this.schedule(() => {
      this.framePending = false;
      const ready = this.held.release(this.playhead(), this.now());
      if (ready) this.view.render(this.shown = ready);
      this.timers.clearTimeout(this.holdTimer);
      if (this.held.size)
        this.holdTimer = this.timers.setTimeout(() => this.release(), 250);
    });
  }
  connection(state: ConnectionState) {
    this.view.connection(state);
    if (state === "gone") {
      this.stop();
      this.token = null;
      this.busy = false;
      this.onGone();
      return;
    }
    if (state === "replaced") {
      this.timers.clearTimeout(this.pendingTimer);
      this.token = null;
      this.generation += 1;
      this.busy = false;
      this.questions.status("This session ended. Reconnect to continue.", true);
    }
  }
  showChat(session: ChatSession) {
    this.session = session;
    this.questions.render(session);
    if (session.mode === "unavailable") {
      this.timers.clearTimeout(this.pendingTimer);
      this.questions.status(ANSWERS_UNAVAILABLE, true);
      return;
    }
    const pending = session.turns?.some((turn) => turn.status === "pending");
    this.questions.status(
      pending
        ? "An answer is still processing…"
        : "Answers grounded in live matches",
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
  async refreshPending(token: string | null, generation: number) {
    this.pendingAttempts += 1;
    try {
      const session = await this.api.restore(token as string);
      if (generation === this.generation) this.showChat(session);
    } catch (error) {
      if (generation === this.generation) {
        this.view.error((error as ServiceError).message);
        this.questions.status("Reconnect to restore the answer.", true);
      }
    }
  }
  async send(prompt: string) {
    prompt = prompt.trim();
    if (!prompt || this.busy || !this.token) return;
    const generation = this.generation,
      token = this.token;
    this.busy = true;
    this.view.error("");
    this.questions.status("Checking stats and the match story…", true);
    const requestId =
      this.retry?.prompt === prompt ? this.retry.id : this.uuid();
    const watched = this.shown?.match.clock_seconds;
    if (typeof watched === "number") this.questions.askedAt?.set(requestId, watched);
    this.questions.render({
      ...this.session,
      turns: [...(this.session!.turns || []), { request_id: requestId, prompt, status: "pending" }],
    });
    this.retry = { prompt, id: requestId };
    try {
      // Nothing shown yet (first state still held for the picture): answer from kick-off, never ahead.
      await this.api.ask(token, prompt, requestId, this.shown?.match.seq ?? 0);
      const session = await this.api.restore(token);
      if (generation !== this.generation) return;
      this.retry = null;
      this.showChat(session);
      this.receive(session.snapshot);
    } catch (error) {
      if (generation !== this.generation) return;
      this.questions.render(this.session!);
      if ((error as ServiceError).code === "session_replaced") {
        this.connection("replaced");
        return;
      }
      if ((error as ServiceError).code === "model_unavailable") {
        this.retry = null;
        this.session = { ...this.session, mode: "unavailable" };
        this.questions.status(ANSWERS_UNAVAILABLE, true);
        return;
      }
      this.questions.status(
        "Could not complete that answer. Your question is ready to retry.",
      );
      this.view.error((error as ServiceError).message);
      this.onRetryPrompt?.(prompt);
    } finally {
      if (generation === this.generation) this.busy = false;
    }
  }
  async track(id: string) {
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
      if (generation === this.generation) this.view.error((error as ServiceError).message);
    }
  }
  async unpin(id: string | number) {
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
      if (generation === this.generation) this.view.error((error as ServiceError).message);
    }
  }
  stop() {
    this.generation += 1;
    this.timers.clearTimeout(this.pendingTimer);
    this.timers.clearTimeout(this.holdTimer);
    this.live.stop();
  }
}
