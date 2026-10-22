import { LabApi } from "../lab/api.ts";

export interface PromptVersion { version: number; template: string; placeholders: string[]; source: string; created_at: string }
export interface PromptRole { role: string; active_version: number; placeholders: string[]; versions: PromptVersion[] }
/** `label` is viewer-facing (may use `{home}`/`{away}`); `description` goes to the narrative author. */
export interface AudienceOption { id: string; label?: string | null; team?: "home" | "away" | null; description: string }
export interface AudienceLayer { id: string; description: string; options: AudienceOption[] }
export interface AudienceBucket { id: string; selections: Record<string, string>; enabled: boolean }
export interface AudienceConfig { layers: AudienceLayer[]; buckets: AudienceBucket[] }
/** A fixture's audience template; `inherited` until the fixture saves its own (from the default).
 * Only `enabled` buckets are generated and offered to viewers. */
export interface AudienceTemplate {
  fixture: string;
  inherited: boolean;
  revision: number;
  config: AudienceConfig;
}
/** `GET /dev/audience-templates`: saved templates, and each match's fixture and enabled buckets. */
export interface TemplateIndex {
  templates: { fixture: string; revision: number }[];
  matches: { match_id: string; fixture: string; revision: number; enabled: string[] }[];
}
export interface ServiceStatus { name: string; status: string; http_status?: number; detail?: string }
/** A seq gap in a match's received events: open until recovered from ETL or skipped. */
export interface StreamGap { match_id: string; seq: number; age_seconds: number; pending: number; state: "open" | "recovered" | "skipped" | string }
export interface Pipeline { services: ServiceStatus[]; gaps?: StreamGap[] }
/** A demo account; `selections` maps default-template layer ids to option ids (its default audience). */
export interface DemoProfile { id: string; display_name: string; selections: Record<string, string> }
export interface ProfilesDocument { revision: number; profiles: DemoProfile[] }

/** Feed admin (contracts §7): catalogue metadata and runs only. */
export interface Recording {
  fixture: string;
  source_match_id?: string;
  description?: string;
  teams?: { id: string; name: string; position?: string }[];
  duration_seconds?: number;
  capabilities?: Record<string, unknown>;
  synthetic?: boolean;
}
export interface Run {
  run_id: string;
  match_id: string;
  fixture: string;
  kickoff: string;
  status: "scheduled" | "live" | "finished" | string;
  seq?: number;
  video_seconds?: number;
}
/** Feed demo settings (`GET`/`PUT /demo`): fixtures (the main game first; it starts first and opens by default),
 * stagger, run cap and start points. */
export interface DemoSettings {
  fixtures: string[];
  main_fixture: string;
  stagger_seconds: number;
  max_active_runs: number;
  start_points: { id: string; label: string; period: number; minute: number; seed: string | null }[];
  revision: number;
}
export type PurgeTarget = { match_id: string } | { all: true };
export interface PurgeResult { match_ids: string[]; purged: Record<string, number> }

/** A revision-checked backend config table (`GET`/`PUT /dev/config/{table}`). */
export interface ConfigDocument { table: string; revision: number; value: Record<string, unknown> }
export const CONFIG_TABLES = [
  { id: "presentation", title: "Presentation", hint: "Card slots, default and fallback stats ({team} or all), excluded stats, protected kinds." },
  { id: "replay-timing", title: "Replay timing", hint: "Clip timing per event type, lead-ins, clip/page limits, and playback: the sting between clips (asset, hold, cut, fades) and slow motion around events." },
  { id: "key-moment-ranks", title: "Key-moment ranks", hint: "Rank of goal, dismissal, penalty and card (1 = most important)." },
  { id: "prices", title: "Answer prices", hint: "US dollars per million input and output tokens; viewer receipts estimate cost from these." },
  { id: "stream", title: "Stream", hint: "Seconds a seq gap may stay open before the backend recovers it from ETL or skips it." },
  { id: "subscriptions", title: "Story follows", hint: "Follow decision, novelty, prefilter, catch-up, limits and suggestions; served to the engine with each match's follow targets." },
  { id: "key-moment-feed", title: "Key-moment feed", hint: "Pivotal moment kinds every feed shows and their labels ({team}, {scorer}, {player}, {score}…)." },
  { id: "storyline-policy", title: "Storyline policy", hint: "Storyline lifecycle, salience, focus rotation and analysis caps; the engine reads it at GET /storyline-policy." },
  { id: "cross-match", title: "Cross-match", hint: "Questions, pins and follows about the demo's other live matches: on/off, the name share that picks another match, other teams in follow suggestions." },
  { id: "follow-offer", title: "Follow offer", hint: "The \"Follow this story?\" offer on answers: the yes/no decision question, its threshold, requests per minute and timeout." },
] as const;

/** Thrown when another editor saved first; the screen keeps the draft and offers a reload. */
export class ConflictError extends Error {
  status = 409;
}

const errors = new LabApi();

/** Purge order from contracts §5: the producer first so nothing re-creates rows downstream. */
export const PURGE_OWNERS = [
  { owner: "feed", path: "/feed-api/admin/matches/purge" },
  { owner: "etl", path: "/purge-api/etl" },
  { owner: "engine", path: "/purge-api/engine" },
  { owner: "backend", path: "/purge-api/backend" },
] as const;

/** Every developer-only route: backend `/dev/` via `/dev-api/`, the feed console via `/feed-api/`,
 * each owner's purge via `/purge-api/{owner}`. The viewer and lab never call these. */
export class DevApi {
  base: string;
  feed: string;
  fetcher: typeof fetch;
  constructor(base = "/dev-api", feed = "/feed-api", fetcher: typeof fetch = (...args) => globalThis.fetch(...args)) {
    this.base = base; this.feed = feed; this.fetcher = fetcher;
  }

  private async call<T>(url: string, method = "GET", body?: unknown, headers: Record<string, string> = {}): Promise<T> {
    const response = await this.fetcher(url, {
      method,
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...headers },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    return errors.parse<T>(response);
  }
  private send<T>(path: string, method = "GET", body?: unknown) { return this.call<T>(`${this.base}${path}`, method, body); }

  prompts() { return this.send<{ roles: PromptRole[] }>("/narrative-prompts"); }
  savePrompt(role: string, template: string, expected_version: number) {
    return this.send<{ version: number }>(`/narrative-prompts/${encodeURIComponent(role)}`, "PUT", { template, expected_version });
  }
  activatePrompt(role: string, version: number) {
    return this.send<{ version: number }>(`/narrative-prompts/${encodeURIComponent(role)}/versions/${version}/activate`, "POST");
  }
  templates() { return this.send<TemplateIndex>("/audience-templates"); }
  template(fixture: string) { return this.send<AudienceTemplate>(`/fixtures/${encodeURIComponent(fixture)}/audience-config`); }
  async saveTemplate(fixture: string, config: AudienceConfig, expected_revision: number): Promise<{ revision: number }> {
    const response = await this.fetcher(`${this.base}/fixtures/${encodeURIComponent(fixture)}/audience-config`, {
      method: "PUT",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config, expected_revision }),
    });
    if (response.status === 409)
      throw new ConflictError("Someone else saved this template first. Reload to see their version; your draft is kept.");
    return errors.parse(response);
  }
  pipeline() { return this.send<Pipeline>("/pipeline"); }

  /** `null` when the ETag still matches (304). */
  async profiles(etag = ""): Promise<{ document: ProfilesDocument; etag: string } | null> {
    const response = await this.fetcher(`${this.base}/profiles`, {
      cache: "no-store",
      headers: etag ? { "If-None-Match": etag } : {},
    });
    if (response.status === 304) return null;
    const document = await errors.parse<ProfilesDocument>(response);
    return { document, etag: response.headers.get("ETag") ?? "" };
  }
  async saveProfiles(profiles: DemoProfile[], expected_revision: number): Promise<ProfilesDocument> {
    const response = await this.fetcher(`${this.base}/profiles`, {
      method: "PUT",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profiles, expected_revision }),
    });
    if (response.status === 409)
      throw new ConflictError("Someone else saved the profiles first. Reload to see their version; your draft is kept.");
    return errors.parse(response);
  }

  /** `null` when the ETag still matches (304): the editor keeps what it shows. */
  async table(table: string, etag = ""): Promise<{ document: ConfigDocument; etag: string } | null> {
    const response = await this.fetcher(`${this.base}/config/${encodeURIComponent(table)}`, {
      cache: "no-store",
      headers: etag ? { "If-None-Match": etag } : {},
    });
    if (response.status === 304) return null;
    const document = await errors.parse<ConfigDocument>(response);
    return { document, etag: response.headers.get("ETag") ?? "" };
  }
  async saveTable(table: string, value: unknown, expected_revision: number, etag = ""): Promise<{ revision: number }> {
    const response = await this.fetcher(`${this.base}/config/${encodeURIComponent(table)}`, {
      method: "PUT",
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...(etag ? { "If-Match": etag } : {}) },
      body: JSON.stringify({ value, expected_revision }),
    });
    if (response.status === 409 || response.status === 412)
      throw new ConflictError("Someone else saved this table first. Reload to see their version; your draft is kept.");
    return errors.parse(response);
  }

  recordings() { return this.call<Recording[]>(`${this.feed}/recordings`); }
  runs() { return this.call<Run[]>(`${this.feed}/runs`); }
  demo() { return this.call<DemoSettings>(`${this.feed}/demo`); }
  saveDemo({ revision, ...settings }: DemoSettings) {
    return this.call<DemoSettings>(`${this.feed}/demo`, "PUT", { ...settings, expected_revision: revision });
  }
  startRun(fixture: string) {
    return this.call<Run>(`${this.feed}/runs`, "POST", { fixture, kickoff: "next-minute" });
  }
  /** Purges every owner in order and stops at the first failure; rerunning is safe (idempotent). */
  async purge(target: PurgeTarget, progress: (owner: string) => void = () => {}) {
    const results: { owner: string; result: PurgeResult }[] = [];
    for (const { owner, path } of PURGE_OWNERS) {
      progress(owner);
      try {
        results.push({ owner, result: await this.call<PurgeResult>(path, "POST", target) });
      } catch (error) {
        throw new Error(`Purge stopped at ${owner}: ${(error as Error).message} Rerun to finish; purge is idempotent.`);
      }
    }
    return results;
  }
}
