/** Viewer API and live payloads, as used by the client (see docs/live-contract.md). */
export type StatNumber = number | string | null | undefined;

/** Club presentation from the match's MA1 data, served by the backend. */
export interface TeamBranding {
  primary_colour?: string | null;
  secondary_colour?: string | null;
  crest_asset_id?: string | null;
}
export interface Team {
  id?: string;
  name?: string;
  short_name?: string;
  code?: string;
  position?: string;
  score?: StatNumber;
  branding?: TeamBranding | null;
}
/** Another live match of the demo that content came from (PLAN.md §10.2 D5): teams without the score. */
export interface OtherMatch {
  id: string;
  fixture?: string;
  teams: Team[];
}
/** One entry of `GET /product/matches` (live first, then scheduled, then finished). */
export interface MatchSummary {
  match_id: string;
  fixture?: string;
  status: string;
  scheduled_kickoff?: string | null;
  seq?: number;
  period?: number | null;
  clock_seconds?: number | null;
  teams: Team[];
  video?: { hls?: string | null } | null;
}
export interface MatchMedia {
  /** Match video seconds at this snapshot. */
  seconds?: number | null;
  /** The match's published live playlist (`/media/hls/<matchId>/live.m3u8`), or null without video; player time equals match video seconds. */
  url?: string | null;
}
export interface MatchState {
  /** The match id (`match_id` in listings). */
  id?: string;
  fixture?: string;
  /** Canonical event seq of this snapshot; questions are answered as of the shown seq. */
  seq?: number;
  status?: string;
  /** ISO kickoff (MA1); a `scheduled` match counts down to it. */
  scheduled_kickoff?: string | null;
  clock_seconds?: number | null;
  period?: number;
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
  /** Pinned from another live match of the demo, at that match's own position. */
  other_match?: OtherMatch | null;
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
  /** `subscription` for a followed story's narrative (with its `topic_id`), else a bucket insight. */
  kind?: string;
  topic_id?: string;
  /** A followed story in another live match of the demo. */
  other_match?: OtherMatch | null;
}
/** A pivotal fact (goal, red card, period marker…) shown to every viewer; never authored text. */
export interface KeyMoment {
  id: string;
  kind: string;
  label: string;
  period?: number | null;
  clock_seconds?: number | null;
  minute_label?: string;
  /** A goal a VAR review overturned. */
  overturned?: boolean;
}
/** What a follow is about (local/contracts.md §8b). */
export interface FollowSpec {
  kind: "storyline" | "team" | "player" | "theme";
  storyline_id?: string | null;
  team_id?: string | null;
  player_id?: string | null;
  focus?: string;
  label: string;
}
export interface Follow {
  subscription_id: string;
  /** The followed match: the viewer's own, or another live match of the demo. */
  match_id?: string;
  topic_id: string;
  spec: FollowSpec;
  label: string;
  since_seq?: number;
  /** Where the follow began on the followed match's clock (the follow view's "Following since" line). */
  since_period?: number;
  since_clock_seconds?: number;
  created_at?: string;
  ended_at?: string | null;
}
/** A ready-to-follow choice: a suggestion, a proposal or a clarification candidate. */
export interface FollowOption {
  id: string;
  label: string;
  spec: FollowSpec;
  /** Set for a story in another live match of the demo. */
  match_id?: string;
  other_match?: OtherMatch | null;
}
export interface FollowReply {
  status: "proposal" | "clarify" | "unfollow" | "answer" | "unsupported";
  text: string;
  proposal?: FollowOption | null;
  candidates?: FollowOption[];
}
export interface FollowTurn {
  id?: string | number;
  request_id?: string;
  prompt?: string;
  status?: string;
  reply?: FollowReply | null;
}
/** The viewer's chosen audience bucket and its layer selections. */
export interface Audience {
  bucket_id: string;
  selections?: Record<string, string>;
}
/** One enabled audience bucket of the match, labelled by the backend from its template. */
export interface AudienceBucket {
  id: string;
  label: string;
}
export interface Snapshot {
  type?: string;
  projection_epoch?: string;
  version?: number;
  match: MatchState;
  bucket_id?: string;
  audience?: Audience | null;
  /** The match's enabled buckets: the only choices the viewer is offered. */
  audience_buckets?: AudienceBucket[];
  cards: StatCard[];
  events: MatchEvent[];
  narratives: Narrative[];
  /** `following`: narratives are only the followed story's; `insights`: the bucket's insights. */
  feed_mode?: "following" | "insights";
  follow?: Follow | null;
  /** A follower's captured clips (PLAN.md §10.2 D3, D6): one playlist for the followed story, or null. */
  follow_playlist?: Replay | null;
  /** Everyone else: the key-event clips of their bucket's shared narratives (PLAN.md §10.2 D7), or null. */
  moment_playlist?: Replay | null;
  /** The followed story's match when it is another live match of the demo. */
  follow_match?: OtherMatch | null;
  key_moments?: KeyMoment[];
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
  /** The key moments a captured clip shows (PLAN.md §10.2 D6–D7): its preview card's facts. */
  moments?: ClipMoment[];
}
/** A key moment as a captured clip's preview card shows it (backend services/follow_clips CARD_FIELDS). */
export interface ClipMoment {
  id: string;
  kind: string;
  period?: number | null;
  clock_seconds?: number | null;
  minute_label?: string | null;
  /** The feed's configured label, e.g. "Goal · Riverton Rovers · Kai Ashworth"; its first part names the event. */
  label?: string | null;
  team_id?: string | null;
  team_name?: string | null;
  player_name?: string | null;
  /** The score after the moment, as the key-moment feed writes it. */
  score?: string | null;
}
/** Served with each replay (backend replay-timing.playback, migrations/037). */
export interface Playback {
  transitions: {
    enabled: boolean;
    hold_seconds: number;
    /** A video path, or `builtin:league` for the CSS sting drawn in the page. */
    asset: string;
    asset_start_seconds: number;
    sting_seconds: number;
    cut_seconds: number;
    fade_seconds: number;
  };
  slow_motion: {
    enabled: boolean;
    rate: number;
    ramp_seconds: number;
    before_seconds: number;
    after_seconds: number;
  };
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
  /** The match's published stream URL (clips are its times), or null without footage. */
  playlist?: string | null;
  clips: ReplayClip[];
  /** Transitions and slow motion; absent (older saved replays) means neither. */
  playback?: Playback | null;
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
  /** Answered from another live match of the demo (named in the question). */
  other_match?: OtherMatch | null;
  /** "Follow this story?": the question to set a follow up from; the viewer confirms in the follow view. */
  follow_offer?: FollowOffer | null;
  /** A request about several live matches: one answer from each, each marked with its match when it is another. */
  parts?: Reply[];
}
export interface FollowOffer {
  prompt: string;
  other_match?: OtherMatch | null;
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
  /** The follow chat's turns (questions stay in `turns`). */
  follow_turns?: FollowTurn[];
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
  | "replaced"
  /** The match's MA1 has not arrived yet: the viewer retries until it opens. */
  | "waiting"
  /** The match was purged or never existed (HTTP 404, socket close 4404). */
  | "gone";

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
