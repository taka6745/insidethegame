/** Filter-lab API payloads, as used by this developer client. */
export type Rule = Record<string, unknown>;

export interface LabTeam {
  id?: string;
  name?: string;
  label?: string;
}
export type LabTeams = (string | LabTeam)[] | Partial<Record<string, string | LabTeam>> | null | undefined;
/** The fields of a `GET /product/matches` entry the lab shows. */
export interface LabMatch {
  match_id: string;
  fixture?: string;
  status: string;
  clock_seconds?: number | null;
  teams?: LabTeam[];
}
/** One received event as the lab state route displays it (names resolved from the match's teams and players). */
export interface LabEvent {
  id?: string;
  seq?: number;
  type?: string;
  player?: string | null;
  team?: string | null;
  minute?: number;
  match_time_seconds?: number;
  period?: number;
  body_part?: string | null;
  outcome?: string | null;
  revision?: number;
  deleted?: boolean;
}
export interface Calculation {
  id?: string;
  label?: string;
  value?: number | string | null;
  rule?: Rule & { label?: string };
}
export interface LabState {
  match_id?: string;
  fixture?: string;
  /** Canonical events received for this match. */
  seq?: number;
  error?: string;
  events?: LabEvent[];
  match_time_seconds?: number | null;
  metrics?: { total_rules?: number; candidate_count?: number; changed_count?: number };
  calculations?: Calculation[];
  llm?: { configured?: boolean };
  /** The backend's published ETL goals for this run; null before the first snapshot. */
  score?: { id: string; name: string; score: number | null }[] | null;
}
export interface PlanResult {
  status?: string;
  message?: string;
  conversation_id?: string | null;
  goal?: { description?: string } | string;
  rule?: Rule | null;
  clarification?: { question?: string; options?: string[] };
}
export interface EventPayload {
  seq?: number;
  canonical?: unknown;
}
export interface Offer {
  id: string;
  label?: string;
  value?: unknown;
  calculation_id?: string | null;
}
export interface ChatTurn {
  prompt?: string;
  status?: string;
  reply?: {
    text?: string;
    snapshot?: { clock_seconds?: number | null; period?: number };
    evidence?: { label?: string }[];
    offers?: Offer[];
  } | null;
}
export interface ChatSession {
  session_token?: string;
  mode?: string;
  turns: ChatTurn[];
  offers?: Offer[];
}
export interface ChatProfile {
  id: string;
  display_name?: string;
}

/** Errors raised by the API adapter carry the HTTP status and backend code. */
export type { ServiceError } from '../shared/http.ts';

declare global {
  interface Window {
    labState?: LabState;
  }
  interface WindowEventMap {
    "lab-state": CustomEvent<LabState>;
  }
}
