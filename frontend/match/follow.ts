import { applyOwnSnapshot } from "./controller.ts";
import type { MatchApi } from "./api.ts";
import type { MatchController } from "./controller.ts";
import type { FollowView } from "./follow-view.ts";
import type { ChatSession, FollowOption, FollowSpec, FollowTurn, ServiceError, Timers, TimerId } from "./types.ts";

/** Without a model the chat is refused (503); suggestions still follow in one tap. */
export const FOLLOW_UNAVAILABLE = "Follow chat unavailable right now · tap a suggestion to follow";
const READY = "";

export type FollowApi = Pick<MatchApi, "follows" | "follow" | "unfollow" | "followSuggestions" | "followMessage">;
export type FollowHost = Pick<MatchController, "token" | "generation" | "shown" | "snapshot" | "receive" | "reframe"
  | "connection">;
export type FollowRender = Pick<FollowView, "render" | "status" | "actions" | "suggestions">;

/** The Insights tab's follow chat: suggestions, planner turns, follow and stop following (contracts §8b). */
export class FollowController {
  api: FollowApi;
  view: FollowRender;
  host: FollowHost;
  uuid: () => string;
  timers: Timers;
  turns: FollowTurn[] = [];
  busy = false;
  unavailable = false;
  retry: { prompt: string; id: string } | null = null;
  private pendingTimer: TimerId = null;
  private pendingAttempts = 0;
  constructor({ api, view, host, uuid = () => crypto.randomUUID(), timers = globalThis }: {
    api: FollowApi; view: FollowRender; host: FollowHost; uuid?: () => string; timers?: Timers;
  }) {
    this.api = api;
    this.view = view;
    this.host = host;
    this.uuid = uuid;
    this.timers = timers;
  }
  reset() {
    this.timers.clearTimeout(this.pendingTimer);
    this.turns = [];
    this.busy = false;
    this.retry = null;
    this.view.render([]);
    this.view.suggestions([]);
    this.state("Connecting…", true);
  }
  open(session: ChatSession) {
    this.unavailable = session.mode === "unavailable";
    this.pendingAttempts = 0;
    this.show(session.follow_turns || []);
    void this.suggest();
  }
  private seq() {
    return this.host.shown?.match.seq ?? 0;  // nothing shown yet: never ahead of the picture
  }
  private show(turns: FollowTurn[]) {
    this.turns = turns;
    this.view.render(turns);
    this.timers.clearTimeout(this.pendingTimer);
    const pending = turns.some((turn) => turn.status === "pending");
    if (this.unavailable) this.state(FOLLOW_UNAVAILABLE, true);
    else if (!this.busy) this.state(pending ? "Still working on that…" : READY, pending);
    if (pending && this.pendingAttempts < 30) {
      const generation = this.host.generation;
      this.pendingTimer = this.timers.setTimeout(() => {
        this.pendingAttempts += 1;
        if (generation === this.host.generation) void this.refresh();
      }, 2000);
    }
  }
  /** Saved turns from the server (also after a reload mid-turn). */
  async refresh() {
    const token = this.host.token, generation = this.host.generation;
    if (!token) return;
    try {
      const listing = await this.api.follows(token);
      if (generation === this.host.generation) this.show(listing.turns);
    } catch {
      // The next action or reconnect reloads them.
    }
  }
  async suggest() {
    const token = this.host.token, generation = this.host.generation;
    if (!token) return;
    if (!this.host.shown) {
      // The first state is still held for the picture: suggest once it shows.
      this.timers.setTimeout(() => { if (generation === this.host.generation) void this.suggest(); }, 1000);
      return;
    }
    try {
      const result = await this.api.followSuggestions(token, this.seq());
      if (generation === this.host.generation) this.view.suggestions(result.items);
    } catch {
      // Suggestions are optional; the chat still works.
    }
  }
  async send(prompt: string) {
    prompt = prompt.trim();
    const token = this.host.token, generation = this.host.generation;
    if (!prompt || this.busy || this.unavailable || !token) return;
    const requestId = this.retry?.prompt === prompt ? this.retry.id : this.uuid();
    this.retry = { prompt, id: requestId };
    this.busy = true;
    this.state("Finding that story…", true);
    this.view.render([...this.turns, { request_id: requestId, prompt, status: "pending" }]);
    try {
      await this.api.followMessage(token, prompt, requestId, this.seq());
      const listing = await this.api.follows(token);
      if (generation !== this.host.generation) return;
      this.retry = null;
      this.busy = false;
      this.show(listing.turns);
    } catch (caught) {
      if (generation !== this.host.generation) return;
      this.busy = false;
      this.view.render(this.turns);
      this.fail(caught as ServiceError, "Could not complete that. Your message is ready to retry.");
      if (!this.unavailable && (caught as ServiceError).code !== "session_replaced") this.onRetryPrompt?.(prompt);
    }
  }
  onRetryPrompt?: (prompt: string) => void;
  async follow(option: FollowOption | { spec: FollowSpec }) {
    const token = this.host.token, generation = this.host.generation;
    if (this.busy || !token) return;
    this.busy = true;
    this.state(`Following ${option.spec.label}…`, true);
    try {
      const other = "match_id" in option ? option.match_id : undefined;
      const result = await (other ? this.api.follow(token, option.spec, this.seq(), other)
        : this.api.follow(token, option.spec, this.seq()));
      if (generation !== this.host.generation) return;
      applyOwnSnapshot(this.host, result.snapshot);
      this.done();
    } catch (caught) {
      if (generation === this.host.generation) {
        this.busy = false;
        this.fail(caught as ServiceError, "Could not follow that. Please try again.");
      }
    }
  }
  async unfollow() {
    const token = this.host.token, generation = this.host.generation;
    const follow = this.host.snapshot?.follow || this.host.shown?.follow;
    if (this.busy || !token || !follow) return;
    this.busy = true;
    this.state("Stopping…", true);
    try {
      const result = await this.api.unfollow(token, follow.subscription_id);
      if (generation !== this.host.generation) return;
      applyOwnSnapshot(this.host, result.snapshot);
      this.done();
    } catch (caught) {
      if (generation === this.host.generation) {
        this.busy = false;
        // Already ended elsewhere: the next snapshot shows the insights.
        this.fail(caught as ServiceError, "Could not stop following. Please try again.");
      }
    }
  }
  /** The composer locks while busy or unavailable; suggestions and Follow buttons only while an action runs. */
  private state(text: string, locked: boolean) {
    this.view.status(text, locked || this.unavailable);
    this.view.actions(!this.busy && Boolean(this.host.token));
  }
  private done() {
    this.busy = false;
    this.show(this.turns);
    void this.suggest();
  }
  private fail(error: ServiceError, fallback: string) {
    if (error.code === "session_replaced") {
      this.host.connection("replaced");
      this.state("This session ended. Reconnect to continue.", true);
    } else if (error.code === "model_unavailable") {
      this.unavailable = true;
      this.retry = null;
      this.state(FOLLOW_UNAVAILABLE, true);
    } else if (error.status && error.status < 500 && error.message) {
      this.state(error.message, false);
    } else {
      this.state(fallback, false);
    }
  }
}
