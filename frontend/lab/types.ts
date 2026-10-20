/** Filter-lab API payloads, as used by this developer client. */
export type Rule = Record<string, unknown>;

export interface LabTeam {
  id?: string;
  name?: string;
  label?: string;
}
export type LabTeams = (string | LabTeam)[] | Partial<Record<string, string | LabTeam>> | null | undefined;
export interface Preset {
  id: string;
  label: string;
  rule: Rule;
}
export interface RecordingInfo {
  filename?: string;
  title?: string;
  format?: string;
  synthetic?: boolean;
  delivery_count?: number;
  event_count?: number;
}
export interface Scenario {
  teams?: LabTeams;
  presets?: Preset[];
  recording?: RecordingInfo;
  recording_editable?: boolean;
}
export interface LabEvent {
  id?: string;
  event_id?: string;
  eventId?: string;
  delivery_index?: number;
  event_type?: string;
  type?: string;
  typeName?: string;
  match_time_seconds?: number;
  elapsed_seconds?: number;
  minute?: number;
  second?: number;
  timeMin?: number;
  timeSec?: number;
  deleted?: boolean;
  revision?: number;
  player_name?: string;
  player?: string;
  player_id?: string;
  playerId?: string;
  team_name?: string;
  team_id?: string;
  team?: string;
  teamId?: string;
  body_part?: string;
  key_moment?: boolean;
}
export interface Calculation {
  id?: string;
  label?: string;
  value?: number | string | null;
  rule?: Rule & { label?: string };
}
export interface LabState {
  run_id?: string;
  status?: string;
  error?: string;
  events?: LabEvent[];
  match_time_seconds?: number | null;
  position?: number | null;
  total?: number | null;
  metrics?: { total_rules?: number; candidate_count?: number; changed_count?: number };
  calculations?: Calculation[];
  llm?: { configured?: boolean };
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
  delivery_index?: number;
  raw?: unknown;
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
  run_id?: string;
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
export type ServiceError = Error & { code?: unknown; status?: number };

declare global {
  interface Window {
    labState?: LabState;
  }
  interface WindowEventMap {
    "lab-state": CustomEvent<LabState>;
  }
}
