/** Viewer API and live payloads, as used by the client (see docs/live-contract.md). */
export type StatNumber = number | string | null | undefined;

export interface Team {
  id?: string;
  name?: string;
  score?: StatNumber;
}
export interface MatchMedia {
  aligned?: boolean;
  seconds?: number | null;
  sampled_at?: number | null;
  /** `/media/hls/live.m3u8` when `live`; player time equals match video seconds. */
  url?: string | null;
  live?: boolean;
}
export interface MatchState {
  run_id?: string;
  status?: string;
  position?: number;
  total?: number;
  clock_seconds?: number | null;
  teams?: Team[];
  media?: MatchMedia;
}
export interface StatCard {
  id: string | number;
  kind?: string;
  label?: string;
  value?: StatNumber;
  unit?: string;
  pinned?: boolean;
  pin_id?: string;
}
export interface MatchEvent {
  event_id?: string;
  event_type?: string;
  body_part?: string;
  period?: number;
  match_time_seconds: number;
  deleted?: boolean;
}
export interface Narrative {
  id?: string;
  text?: string;
  clock_seconds?: number | null;
  period?: number;
}
export interface Audience {
  team: string;
  fan_style: string;
}
export interface Snapshot {
  type?: string;
  projection_epoch?: string;
  version?: number;
  match: MatchState;
  bucket?: string;
  audience?: Audience;
  cards: StatCard[];
  events: MatchEvent[];
  narratives: Narrative[];
}
export interface Offer {
  id: string;
  label?: string;
  value?: StatNumber;
  unit?: string;
  calculation_id?: string | null;
}
export interface ReplayItem {
  source_id: string;
  kind?: string;
  caption?: string;
  lead_in?: string;
}
export interface ReplayClip {
  /** Match video seconds. */
  start: number;
  end: number;
  source_ids?: string[];
  captions?: string[];
  /** Match video seconds of the clip's events, marked on the progress bar. */
  marks?: number[];
  /** In/out points on the replay playlist timeline; absent without footage. */
  playlist_start?: number;
  playlist_end?: number;
}
export interface Replay {
  page: number;
  page_size: number;
  total_items: number;
  page_count?: number;
  truncated?: boolean;
  seconds: number;
  items?: ReplayItem[];
  refine_offer?: string | null;
  derived?: Record<string, unknown> | null;
  /** Published stream URL (clips are its times), legacy stitched playlist text, or null without footage. */
  playlist?: string | null;
  clips: ReplayClip[];
}
export interface Clarification {
  question: string;
  options: string[];
  allow_free_text: boolean;
}
export interface Usage {
  input_tokens: number;
  output_tokens: number;
  calls: number;
  seconds: number;
}
export interface Evidence {
  id: string;
  kind: string;
  label: string;
}
export interface Reply {
  status?: string;
  clarification?: Clarification | null;
  text: string;
  answer_kind?: string;
  refine_offer?: string | null;
  snapshot?: { clock_seconds?: number | null };
  offers?: Offer[];
  replay?: Replay | null;
  evidence?: Evidence[];
  usage?: Usage | null;
}
export interface ChatTurn {
  id?: string | number;
  request_id?: string;
  prompt?: string;
  status?: string;
  reply?: Reply | null;
}
export interface ChatSession {
  mode?: string;
  turns?: ChatTurn[];
  offers?: Offer[];
}
export interface ViewerSession extends ChatSession {
  session_token: string;
  snapshot?: unknown;
}
export interface Profile {
  id: string;
}
export interface SnapshotResult {
  snapshot?: unknown;
}
export type ConnectionState =
  | "connecting"
  | "live"
  | "reconnecting"
  | "stale"
  | "offline"
  | "replaced";

/** Errors raised by the API adapter carry the HTTP status and backend code. */
export type ServiceError = Error & { code?: unknown; status?: number };

/** Opaque timer handle: a number in browsers, an object in Node. */
export type TimerId = unknown;
export interface Timers {
  setTimeout(callback: () => void, delay: number): TimerId;
  clearTimeout(id: TimerId): void;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
