// Message shapes the UDFs read. Types only: erased from the generated scripts.
export type Json = Record<string, unknown>;

export interface Qualifier { qualifierId: number | string; value?: unknown }

export interface Contestant {
    id?: string; position?: string; name?: string; shortName?: string; code?: string;
    knownNames?: string[]; lineup?: LineupPlayer[];
}

export interface LineupPlayer {
    playerId?: string; name?: string; shirtNumber?: number; position?: string; starter?: boolean | number | null;
}

export interface Branding { primaryColour?: string; secondaryColour?: string; crestAssetId?: string }

export interface Ma1Message extends Json {
    matchId?: string; description?: string; contestant?: Contestant[]; branding?: Record<string, Branding>;
    scheduledKickoff?: string; synthetic?: boolean; fixture?: string; sourceMatchId?: string; runId?: string;
    capabilities?: unknown;
}

export interface MatchEvent {
    event_id?: string; revision?: number; event_type?: string; team_id?: string; player_id?: string;
    body_part?: string; period?: number; match_time_seconds?: number; outcome?: unknown;
    distance_metres?: number; deleted?: boolean; video_seconds?: number; x?: number; y?: number;
    possession_id?: string; qualifiers?: Json | null;
}

export interface MatchEventMessage { matchId?: string; seq?: number; event?: MatchEvent; timeStamp?: string }
