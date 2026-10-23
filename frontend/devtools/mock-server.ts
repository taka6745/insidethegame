// Developer mock of the multi-match contracts (local/contracts/README.md §5, §7, §8, §8b) for headless UI checks.
// Serves the built dist/ with the production CSP. Not a backend: data is synthetic and in memory.
// Usage: npm run build && node devtools/mock-server.ts [port]
import { createServer } from "node:http";
import type { IncomingMessage, ServerResponse } from "node:http";
import { createHash } from "node:crypto";
import type { Duplex } from "node:stream";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const port = Number(process.argv[2] || 18099);
// MOCK_NO_MODEL=1: the backend has no model; questions and custom stats are refused (503).
const mode = process.env.MOCK_NO_MODEL === "1" ? "unavailable" : "local";
const CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; media-src 'self' blob:; base-uri 'none'; object-src 'none'; frame-ancestors 'none'";
const types: Record<string, string> = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".json": "application/json", ".mp4": "video/mp4" };

// Only clubs with a shipped crest file name one; the rest show their monogram.
const team = (id: string, position: string, name: string, code: string, primary: string, secondary: string, crest: string | null = null) =>
  ({ id, position, name, short_name: name, code, branding: { primary_colour: primary, secondary_colour: secondary, crest_asset_id: crest } });
const started = Date.now();
const matches = new Map([
  ["riverton-forgeham-1a2b3c4d", { fixture: "riverton-forgeham", status: "live", offset: 431,
    teams: [team("riverton", "home", "Riverton Rovers", "RVR", "#001c68", "#0743b7", "riverton"), team("forgeham", "away", "Forgeham United", "FGU", "#c7142b", "#7b0015", "forgeham")] }],
  ["redcastle-whitmore-0f0f0f0f", { fixture: "redcastle-whitmore", status: "live", offset: 1290,
    teams: [team("redcastle", "home", "Redcastle Town", "RCT", "#db0007", "#9c0006"), team("whitmore", "away", "Whitmore Wanderers", "WHW", "#132257", "#0b1438")] }],
  ["portalbion-city-9e8d7c6b", { fixture: "portalbion-city", status: "scheduled", offset: 0,
    teams: [team("portalbion", "home", "Port Albion", "PAL", "#c8102e", "#8a0b20"), team("skybridge", "away", "Skybridge City", "SKC", "#6cabdd", "#1c2c5b")] }],
]);
const clockOf = (id: string) => {
  const match = matches.get(id)!;
  return match.status === "live" ? match.offset + Math.floor((Date.now() - started) / 1000) : null;
};
const summary = (id: string) => {
  const match = matches.get(id)!;
  return { match_id: id, fixture: match.fixture, status: match.status, scheduled_kickoff: new Date(started + 60000).toISOString(),
    seq: 800, period: 1, clock_seconds: clockOf(id), teams: match.teams.map((t, i) => ({ ...t, score: match.status === "live" ? i ? 0 : 1 : undefined })),
    video: { hls: `/media/hls/${id}/live.m3u8` } };
};
let version = 0;
// Audience template (config only): buckets the match enables are the viewer's choices.
const template = {
  layers: [
    { id: "team", description: "Which side the viewer supports.", options: [
      { id: "home", label: "{home}", description: "Supports the home team." },
      { id: "away", label: "{away}", description: "Supports the away team." },
      { id: "neutral", label: "Neutral", description: "No allegiance." }] },
    { id: "fan_style", description: "How to explain the match.", options: [
      { id: "simple", label: "Simple", description: "New to football." },
      { id: "analytical", label: "Analytical", description: "Wants the numbers." }] },
  ],
  buckets: [] as { id: string; selections: Record<string, string>; enabled: boolean }[],
};
for (const team of template.layers[0]!.options) for (const style of template.layers[1]!.options)
  template.buckets.push({ id: `${team.id}:${style.id}`, selections: { team: team.id, fan_style: style.id },
    enabled: ["home:analytical", "away:simple", "neutral:simple"].includes(`${team.id}:${style.id}`) });
let templateRevision = 1;
const choices = new Map<string, string>(); // session token -> bucket id
const bucketsOf = (id: string) => {
  const names: Record<string, string> = { home: matches.get(id)!.teams[0]!.name, away: matches.get(id)!.teams[1]!.name };
  const label = (layer: number, option: string) => {
    const found = template.layers[layer]!.options.find((o) => o.id === option)!;
    return found.label.replace(/\{(home|away)\}/g, (_, side: string) => names[side]!);
  };
  return template.buckets.filter((b) => b.enabled).map((b) => ({ id: b.id, label: `${label(0, b.selections.team!)} · ${label(1, b.selections.fan_style!)}` }));
};
// Story follows (§8b): synthetic players, pivotal key moments and one follow per session token.
type Spec = { kind: string; storyline_id?: string | null; team_id?: string | null; player_id?: string | null; focus?: string; label: string };
type Option = { id: string; label: string; spec: Spec };
type Turn = { id: number; request_id: string; prompt: string; status: string; reply: Record<string, unknown> };
type Follow = { subscription_id: string; topic_id: string; spec: Spec; label: string; since_seq: number; created_at: string; ended_at: string | null; since_clock: number };
const playersOf = (id: string) => {
  const [home, away] = matches.get(id)!.teams;
  const names: Record<string, string[]> = { riverton: ["Sami Lindqvist", "Kai Ashworth"], forgeham: ["Callum Brightwell", "Theo Marchetti"] };
  return [home!, away!].flatMap((t) => (names[t.id] ?? [`${t.code} Number 9`, `${t.code} Number 10`])
    .map((name, i) => ({ id: `${t.id}-${i + 1}`, team_id: t.id, name })));
};
const storylinesOf = (id: string) => [{ id: "sl-press", label: `${matches.get(id)!.teams[0]!.name}'s high press`, status: "open", salience: 0.8 }];
const keyMoments = (id: string) => {
  const clock = clockOf(id);
  if (clock === null) return [];
  const [home, away] = matches.get(id)!.teams, players = playersOf(id);
  const team = (p: { team_id: string }) => (p.team_id === home!.id ? home! : away!).name;
  return [
    { kind: "kick_off", at: 0, label: "Kick-off", team_id: null, player_id: null },
    { kind: "goal", at: 300, label: `Goal · ${team(players[0]!)} · ${players[0]!.name}`, team_id: home!.id, player_id: players[0]!.id },
    { kind: "red_card", at: 400, label: `Red card · ${players[2]!.name}`, team_id: away!.id, player_id: players[2]!.id },
    { kind: "goal", at: 410, label: `Goal · ${team(players[3]!)} · ${players[3]!.name}`, team_id: away!.id, player_id: players[3]!.id, overturned: true },
    { kind: "var_overturn", at: 425, label: `VAR · goal ruled out · ${away!.name}`, team_id: away!.id, player_id: null },
    { kind: "half_time", at: 2700, label: `Half time · ${home!.name} 1–0 ${away!.name}`, team_id: null, player_id: null },
  ].filter((m) => m.at <= clock).map((m, i) => ({ id: `km:${id}-${i}`, kind: m.kind, label: m.label, period: 1, clock_seconds: m.at,
    minute_label: `${Math.floor(m.at / 60) + 1}'`, event_seq: 10 + i, team_id: m.team_id, player_id: m.player_id, overturned: Boolean(m.overturned) }));
};
const topicOf = (match: string, spec: Spec) => "topic:" + createHash("sha256")
  .update(JSON.stringify([match, spec.kind, spec.storyline_id ?? null, spec.team_id ?? null, spec.player_id ?? null, (spec.focus || "").toLowerCase().trim()]))
  .digest("hex").slice(0, 16);
const option = (match: string, spec: Spec): Option => ({ id: topicOf(match, spec), label: spec.label, spec: { storyline_id: null, team_id: null, player_id: null, focus: "", ...spec } });
const follows = new Map<string, { active: Follow | null; all: Follow[]; turns: Turn[] }>();
const followsOf = (token: string) => follows.get(token) ?? follows.set(token, { active: null, all: [], turns: [] }).get(token)!;
const publicFollow = (f: Follow | null) => f && (({ since_clock: _, ...rest }) => rest)(f);
// Following: the topic's narratives only, one 20 s after following and then every minute of match clock.
const followNarratives = (id: string, follow: Follow, clock: number, bucket: string) => {
  const out = [];
  for (let at = follow.since_clock + 20, n = 1; at <= clock; at += 60, n++)
    out.push({ id: `${follow.topic_id}-${n}`, kind: "subscription", topic_id: follow.topic_id, storyline_ids: [], period: 1, clock_seconds: at,
      buckets: [bucket], text: `${follow.label}: update ${n} on this story, written for your perspective (${matches.get(id)!.fixture} mock).` });
  return out;
};
const words = (text: string) => new Set(text.toLowerCase().match(/[a-z0-9]+/g) ?? []);
function plan(match: string, prompt: string, active: Follow | null) {
  if (/\b(stop|unfollow)\b/i.test(prompt))
    return active ? { status: "unfollow", text: `Stop following ${active.label}?`, proposal: null, candidates: [] }
      : { status: "answer", text: "You are not following a story yet.", proposal: null, candidates: [] };
  const asked = words(prompt);
  const entities: Spec[] = [...playersOf(match).map((p) => ({ kind: "player", player_id: p.id, team_id: p.team_id, label: p.name })),
    ...matches.get(match)!.teams.map((t) => ({ kind: "team", team_id: t.id, label: t.name })),
    ...storylinesOf(match).map((l) => ({ kind: "storyline", storyline_id: l.id, label: l.label }))];
  const scored = entities.map((e) => ({ e, score: [...words(e.label)].filter((w) => w.length > 2 && asked.has(w)).length }))
    .filter((r) => r.score > 0).sort((a, b) => b.score - a.score);
  if (scored.length && (scored.length === 1 || scored[0]!.score > scored[1]!.score))
    return { status: "proposal", text: `Follow ${scored[0]!.e.label}? You'll see updates on them instead of the general insights.`, proposal: option(match, scored[0]!.e), candidates: [] };
  if (scored.length) return { status: "clarify", text: "Which one do you mean?", proposal: null, candidates: scored.slice(0, 4).map((r) => option(match, r.e)) };
  if (asked.size < 2) return { status: "clarify", text: "Who or what would you like to follow?", proposal: null, candidates: [] };
  const focus = prompt.trim().slice(0, 300);
  return { status: "proposal", text: `Follow "${focus}"? I'll post when it comes up.`, proposal: option(match, { kind: "theme", focus, label: focus.slice(0, 40) }), candidates: [] };
}
// Captured clips: the clocked goals and the red card as a playlist; no footage in the mock.
const clipsOf = (id: string) => {
  const [home, away] = matches.get(id)!.teams;
  const clips = keyMoments(id).filter((m) => ["goal", "red_card"].includes(m.kind) && !m.overturned).map((m) => {
    const team = m.team_id === home!.id ? home! : away!;
    const parts = m.label.split(" · ");
    return { start: m.clock_seconds - 8, end: m.clock_seconds + 4, source_ids: [m.id], captions: [m.label],
      marks: [m.clock_seconds], moments: [{ id: m.id, kind: m.kind, period: 1, clock_seconds: m.clock_seconds,
        minute_label: `${Math.floor(m.clock_seconds / 60) + 1}'`, label: m.label, team_id: team.id, team_name: team.name,
        player_name: parts.at(-1) === team.name ? null : parts.at(-1), score: `${home!.name} 1–0 ${away!.name}` }] };
  });
  return clips.length ? { page: 0, page_size: 12, total_items: clips.length, page_count: 1, truncated: false,
    seconds: clips.length * 12, playlist: null, clips } : null;
};
const snapshot = (id: string, token = "") => {
  const match = matches.get(id)!, clock = clockOf(id);
  const [home, away] = match.teams;
  const buckets = bucketsOf(id), chosen = buckets.find((b) => b.id === choices.get(token)) ?? buckets[0];
  const selections = chosen ? template.buckets.find((b) => b.id === chosen.id)!.selections : null;
  const follow = followsOf(token).active;
  const insights = [{ id: `${id}-n1`, period: 1, clock_seconds: Math.max(0, (clock ?? 0) - 30), text: `${home!.name} are pressing ${away!.name} high in this ${match.fixture} mock.` }];
  return { type: "snapshot", projection_epoch: "mock", version: ++version, mode,
    bucket_id: chosen?.id, audience: chosen ? { bucket_id: chosen.id, selections } : null, audience_buckets: buckets,
    match: { id, fixture: match.fixture, status: match.status, seq: 800, period: 1, clock_seconds: clock,
      teams: [{ ...home!, score: 1 }, { ...away!, score: 0 }],
      media: { url: null, seconds: clock } },
    cards: ["goals", "shots", "passes", "corners", "possession"].map((kind, i) => ({ id: `all:${kind}`, kind: "standard", label: `${home!.name} ${kind}`, value: i * 3 + (clock ?? 0) % 7, unit: kind === "possession" ? "%" : "" })),
    events: [], narratives: follow ? followNarratives(id, follow, clock ?? 0, chosen?.id ?? "") : insights,
    feed_mode: follow ? "following" : "insights", follow: publicFollow(follow), key_moments: keyMoments(id),
    follow_playlist: follow ? clipsOf(id) : null, moment_playlist: follow ? null : clipsOf(id) };
};
const runs = [...matches].map(([id, m]) => ({ run_id: `${id.slice(-8)}-0000`, match_id: id, fixture: m.fixture, kickoff: new Date(started).toISOString(), status: m.status, seq: 800, video_seconds: clockOf(id) ?? 0 }));
const demo = { fixtures: ["redcastle-portalbion", "riverton-forgeham", "skybridge-whitmore"], main_fixture: "redcastle-portalbion",
  stagger_seconds: 120, max_active_runs: 3, revision: 1,
  start_points: [["kickoff", "Kick-off", 1, 0], ["20", "20′", 1, 20], ["ht", "Second half", 2, 45], ["60", "60′", 2, 60], ["85", "85′", 2, 85]]
    .map(([id, label, period, minute]) => ({ id: String(id), label: String(label), period: Number(period), minute: Number(minute), seed: null as string | null })) };
const config: Record<string, { revision: number; value: unknown }> = {
  presentation: { revision: 3, value: { card_slots: 5, default_stats: { team: ["{team}:shots"], neutral: ["all:goals"] },
    fallback_stats: { team: ["{team}:passes"], neutral: ["all:passes"] }, excluded_stats: [], protected_stat_kinds: [] } },
  "replay-timing": { revision: 1, value: { timing: { goal: [8, 4] }, default: [5, 3], lead_in: { short: 1, normal: 2, long: 3 },
    max_clips: 12, max_seconds: 300, max_move_seconds: 30, merge_gap: 4, max_items: 36 } },
  "key-moment-ranks": { revision: 2, value: { ranks: { goal: 1, dismissal: 2, penalty: 3, card: 4 } } },
  prices: { revision: 1, value: { input: 0.4, output: 1.6 } },
  stream: { revision: 1, value: { gap_timeout_seconds: 30 } },
  subscriptions: { revision: 1, value: { limits: { follow_changes_per_minute: 4, max_topics_per_match: 50 },
    suggestions: { max_items: 4, storylines: true, teams: true, players: true }, min_name_match: 0.5 } },
  "key-moment-feed": { revision: 1, value: { kinds: ["goal", "red_card", "half_time", "full_time"],
    labels: { goal: "Goal · {team} · {scorer}" } } },
  "storyline-policy": { revision: 1, value: { storylines: { max_active: 4 } } },
  "cross-match": { revision: 1, value: { enabled: true, min_name_coverage: 0.5, suggest_teams: true } },
  "follow-offer": { revision: 1, value: { enabled: true, min_probability: 0.6, max_per_minute: 3, timeout_seconds: 6 } },
  "models": { revision: 1, value: { deployments: ["writer", "questions", "gpt-6-luna", "gpt-5-mini"], engine: { summary: { deployment: "", effort: "" }, compression: { deployment: "", effort: "" }, analyst: { deployment: "", effort: "" }, author: { deployment: "", effort: "" } }, backend: { questions: { deployment: "", effort: "" }, follow_planner: { deployment: "", effort: "" }, replay: { deployment: "", effort: "" } } } },
};
const profiles = { revision: 1, profiles: [
  { id: "riverton-analytical", display_name: "Riverton Rovers analyst", selections: { team: "home", fan_style: "analytical" } },
  { id: "neutral-simple", display_name: "New viewer", selections: { team: "neutral", fan_style: "simple" } }] };
const sockets = new Map<Duplex, string>();
const socketTokens = new Map<Duplex, string>();

function send(res: ServerResponse, status: number, body?: unknown, headers: Record<string, string> = {}) {
  res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store", "Content-Security-Policy": CSP, ...headers });
  res.end(body === undefined ? undefined : JSON.stringify(body));
}
async function body(req: IncomingMessage): Promise<Record<string, unknown>> {
  let text = "";
  for await (const chunk of req) text += chunk;
  return text ? JSON.parse(text) : {};
}
function purge(target: Record<string, unknown>) {
  const ids = target.all ? [...matches.keys()] : [String(target.match_id)];
  for (const id of ids) {
    matches.delete(id);
    runs.splice(0, runs.length, ...runs.filter((run) => run.match_id !== id));
    for (const [socket, match] of sockets) if (match === id) close(socket, 4404);
  }
  return { match_ids: ids, purged: { rows: ids.length } };
}
function frame(socket: Duplex, opcode: number, payload: Buffer) {
  const header = payload.length < 126 ? Buffer.from([0x80 | opcode, payload.length])
    : Buffer.from([0x80 | opcode, 126, payload.length >> 8, payload.length & 255]);
  socket.write(Buffer.concat([header, payload]));
}
function close(socket: Duplex, code: number) {
  const payload = Buffer.alloc(2);
  payload.writeUInt16BE(code);
  frame(socket, 8, payload);
  sockets.delete(socket);
  socketTokens.delete(socket);
  socket.end();
}

async function api(req: IncomingMessage, res: ServerResponse, path: string) {
  const method = req.method || "GET";
  let m: RegExpMatchArray | null;
  if (path === "/viewer-api/matches") return send(res, 200, [...matches.keys()].map(summary));
  if (path === "/viewer-api/profiles") return send(res, 200, { profiles: [{ id: "demo-1" }] });
  if (path === "/viewer-api/prices") return send(res, 200, { ...(config.prices!.value as object), revision: config.prices!.revision });
  if ((m = path.match(/^\/viewer-api\/matches\/([^/]+)\/sessions(?:\/([^/]+))?(\/.*)?$/))) {
    if (!matches.has(m[1]!)) return send(res, 404, { detail: "Match not found", code: "match_not_found" });
    const token = m[2] ?? `tok-${m[1]}`, match = m[1]!, state = followsOf(token);
    if (!m[3]) return send(res, 200, { session_token: token, mode, turns: [], offers: [], follow: publicFollow(state.active),
      follow_turns: state.turns, snapshot: snapshot(match, token) });
    if (m[3] === "/follows" && method === "GET")
      return send(res, 200, { follow: publicFollow(state.active), follows: state.all.map(publicFollow), turns: state.turns });
    if (m[3] === "/follows" && method === "POST") {
      const input = await body(req) as { spec: Spec; seq?: number };
      const chosen = option(match, input.spec);
      if (state.active?.topic_id === chosen.id) return send(res, 200, { follow: publicFollow(state.active), created: false, snapshot: snapshot(match, token) });
      if (state.active) return send(res, 409, { code: "follow_limit", detail: "You already follow a story. Stop following it to choose another." });
      state.active = { subscription_id: crypto.randomUUID(), topic_id: chosen.id, spec: chosen.spec, label: chosen.label, since_seq: input.seq ?? 800,
        created_at: new Date().toISOString(), ended_at: null, since_clock: clockOf(match) ?? 0 };
      state.all.unshift(state.active);
      return send(res, 200, { follow: publicFollow(state.active), created: true, snapshot: snapshot(match, token) });
    }
    const ending = m[3].match(/^\/follows\/([^/]+)$/);
    if (ending && method === "DELETE") {
      const active = state.active;
      if (!active || active.subscription_id !== ending[1]) return send(res, 404, { code: "follow_not_found", detail: "You are not following that story." });
      const ended: Follow = { ...active, ended_at: new Date().toISOString() };
      state.all.splice(0, 1, ended);
      state.active = null;
      return send(res, 200, { follow: null, ended: publicFollow(ended), snapshot: snapshot(match, token) });
    }
    if (m[3] === "/follow/suggestions") {
      const players = playersOf(match), seen = new Set([state.active?.topic_id]);
      const items = [...storylinesOf(match).map((l) => option(match, { kind: "storyline", storyline_id: l.id, label: l.label })),
        ...keyMoments(match).reverse().flatMap((k) => players.filter((p) => p.id === k.player_id)
          .map((p) => option(match, { kind: "player", player_id: p.id, team_id: p.team_id, label: p.name }))),
        ...matches.get(match)!.teams.map((t) => option(match, { kind: "team", team_id: t.id, label: t.name }))]
        .filter((o) => !seen.has(o.id) && seen.add(o.id));
      return send(res, 200, { snapshot_id: `${match}:800`, items: items.slice(0, 6) });
    }
    if (m[3] === "/follow/messages") {
      if (mode === "unavailable")
        return send(res, 503, { code: "model_unavailable", detail: "The follow chat is unavailable: no model is configured for this service. Use a suggestion instead." });
      const { prompt, request_id } = await body(req) as { prompt: string; request_id: string };
      const existing = state.turns.find((t) => t.request_id === request_id);
      if (existing) return send(res, 200, existing.reply);
      const reply = { ...plan(match, String(prompt), state.active), snapshot: { id: `${match}:800`, seq: 800 },
        usage: { input_tokens: 900, output_tokens: 60, calls: 1, seconds: 0.4 } };
      state.turns.push({ id: state.turns.length + 1, request_id, prompt: String(prompt), status: "done", reply });
      return send(res, 200, reply);
    }
    if (m[3] === "/messages" && mode === "unavailable")
      return send(res, 503, { detail: "Questions are unavailable: no model is configured for this service.", code: "model_unavailable" });
    if (m[3] === "/audience") {
      const { bucket_id } = await body(req);
      if (!bucketsOf(m[1]!).some((b) => b.id === bucket_id))
        return send(res, 422, { detail: "This audience is not configured for the match.", code: "audience_unavailable" });
      choices.set(m[2]!, String(bucket_id));
      return send(res, 200, { snapshot: snapshot(m[1]!, m[2]) });
    }
    return send(res, 200, {});
  }
  if ((m = path.match(/^\/api\/matches\/([^/]+)\/(state|events\/\d+)$/))) {
    const match = matches.get(m[1]!);
    if (!match) return send(res, 404, { detail: "This match is no longer available.", code: "match_not_found" });
    const teams = match.teams.map((t) => ({ id: t.id, name: t.name }));
    if (m[2]!.startsWith("events/")) return send(res, 200, { seq: Number(m[2]!.slice(7)), canonical: { event_type: "pass", team_id: teams[0]?.id, sequence: Number(m[2]!.slice(7)) } });
    return send(res, 200, { synthetic: true, match_id: m[1], fixture: match.fixture, seq: 800, events: [
      { id: `${m[1]}-800`, seq: 800, type: "pass", team: teams[0]?.name, player: "Player 10", match_time_seconds: (clockOf(m[1]!) ?? 0) - 4, period: 1, revision: 1, deleted: false }],
      calculations: [], metrics: { total_rules: 0, candidate_count: 0, changed_count: 0 }, llm: { configured: mode !== "unavailable" },
      score: teams.map((t, i) => ({ ...t, score: i ? 0 : 1 })) });
  }
  if (path === "/api/chat/profiles") return send(res, 200, { profiles: [{ id: "demo-1", display_name: "Demo viewer" }], mode });
  if (path === "/dev-api/narrative-prompts") return send(res, 200, { roles: [{ role: "summary", active_version: 1, placeholders: ["match_events"],
    versions: [{ version: 1, template: "Summarise {match_events}.", placeholders: ["match_events"], source: "seed", created_at: new Date(started).toISOString() }] }] });
  if (path === "/dev-api/audience-templates") return send(res, 200, {
    templates: [{ fixture: "default", revision: templateRevision }],
    matches: [...matches].map(([id, match]) => ({ match_id: id, fixture: match.fixture, revision: templateRevision,
      enabled: template.buckets.filter((b) => b.enabled).map((b) => b.id) })) });
  if ((m = path.match(/^\/dev-api\/fixtures\/([a-z0-9-]+)\/audience-config$/))) {
    if (method === "PUT") {
      const input = await body(req);
      if (input.expected_revision !== templateRevision) return send(res, 409, { detail: "Reload the catalogue before editing", code: "audience_revision_conflict" });
      Object.assign(template, input.config);
      return send(res, 200, { revision: ++templateRevision });
    }
    return send(res, 200, { fixture: m[1], inherited: m[1] !== "default", revision: templateRevision, config: template });
  }
  if (path === "/dev-api/profiles") {
    const etag = `"profiles-${profiles.revision}"`;
    if (method === "PUT") {
      const input = await body(req);
      if (input.expected_revision !== profiles.revision) return send(res, 409, { detail: "Reload the profiles before saving", code: "profiles_revision_conflict" });
      profiles.revision += 1;
      profiles.profiles = input.profiles as typeof profiles.profiles;
      return send(res, 200, profiles);
    }
    if (req.headers["if-none-match"] === etag) return send(res, 304, undefined, { ETag: etag });
    return send(res, 200, profiles, { ETag: etag });
  }
  if (path === "/dev-api/pipeline") return send(res, 200, {
    services: [{ name: "user-backend", status: "degraded", detail: "1 open stream gap" }, { name: "etl", status: "ok" }, { name: "narrative", status: "ok" }],
    gaps: [{ match_id: "riverton-forgeham-1a2b3c4d", seq: 412, age_seconds: 12.4, pending: 18, state: "open" }] });
  if ((m = path.match(/^\/dev-api\/config\/([a-z-]+)$/)) && config[m[1]!]) {
    const table = config[m[1]!]!, etag = `"${m[1]}-${table.revision}"`;
    if (method === "PUT") {
      const input = await body(req);
      if (input.expected_revision !== table.revision) return send(res, 409, { detail: "Revision conflict" });
      table.revision += 1;
      table.value = input.value;
      return send(res, 200, { table: m[1], ...table });
    }
    if (req.headers["if-none-match"] === etag) return send(res, 304, undefined, { ETag: etag });
    return send(res, 200, { table: m[1], ...table }, { ETag: etag });
  }
  if (path === "/feed-api/recordings") return send(res, 200, [{ fixture: "riverton-forgeham", description: "Riverton Rovers v Forgeham United", duration_seconds: 5515.48, synthetic: true, teams: [] },
    { fixture: "redcastle-whitmore", description: "Redcastle Town v Whitmore Wanderers", duration_seconds: 5600, synthetic: true }]);
  if (path === "/feed-api/runs" && method === "GET") return send(res, 200, runs.map((run) => ({ ...run, video_seconds: clockOf(run.match_id) ?? 0 })));
  if (path === "/feed-api/runs" && method === "POST") {
    const { fixture } = await body(req);
    const id = `${fixture}-${Math.random().toString(16).slice(2, 10).padEnd(8, "0")}`;
    const source = [...matches.values()].find((match) => match.fixture === fixture);
    matches.set(id, { fixture: String(fixture), status: "scheduled", offset: 0, teams: source?.teams ?? [] });
    const run = { run_id: id.slice(-8), match_id: id, fixture: String(fixture), kickoff: new Date(Date.now() + 90000).toISOString(), status: "scheduled", seq: 0, video_seconds: 0 };
    runs.push(run);
    return send(res, 201, run);
  }
  if (path === "/demo-api/state") return send(res, 200, { points: demo.start_points.map(({ id, label }) => ({ id, label, ready: true })), live: false, runs: [], pending: [], last: null, skips: [] });
  if (path === "/feed-api/demo" && method === "GET") return send(res, 200, demo);
  if (path === "/feed-api/demo" && method === "PUT") {
    const { expected_revision, ...input } = await body(req);
    if (expected_revision !== demo.revision) return send(res, 409, { detail: "Revision conflict" });
    Object.assign(demo, input, { revision: demo.revision + 1 });
    return send(res, 200, demo);
  }
  if (path === "/feed-api/admin/matches/purge" || /^\/purge-api\/(etl|engine|backend)$/.test(path)) return send(res, 200, purge(await body(req)));
  return send(res, 404, { detail: "Not found" });
}

async function file(req: IncomingMessage, res: ServerResponse, path: string) {
  const mapped = path === "/" ? "dist/match/index.html" : path.endsWith("/") ? `dist${path}index.html`
    : path.startsWith("/assets/") ? path.slice(1) : `dist${path}`;
  const full = normalize(join(root, mapped));
  if (!full.startsWith(root)) return send(res, 404);
  try {
    const data = await readFile(full);
    const headers = { "Content-Type": types[extname(full)] || "application/octet-stream", "Content-Security-Policy": CSP, "Cache-Control": "no-cache", "Accept-Ranges": "bytes" };
    // Byte ranges, as nginx serves them: browsers can only seek media that supports them.
    const range = /^bytes=(\d*)-(\d*)$/.exec(String(req.headers.range || ""));
    if (range && (range[1] || range[2])) {
      const start = range[1] ? Number(range[1]) : data.length - Number(range[2]);
      const end = range[1] && range[2] ? Math.min(Number(range[2]), data.length - 1) : data.length - 1;
      res.writeHead(206, { ...headers, "Content-Range": `bytes ${start}-${end}/${data.length}` });
      return res.end(data.subarray(start, end + 1));
    }
    res.writeHead(200, headers);
    res.end(data);
  } catch {
    send(res, 404, { detail: "Not found" });
  }
}

const server = createServer((req, res) => {
  const path = new URL(req.url || "/", "http://mock").pathname;
  const handled = /^\/(viewer-api|api|dev-api|feed-api|purge-api|demo-api)\//.test(path) ? api(req, res, path)
    : path.startsWith("/media/") ? Promise.resolve(send(res, 404, { detail: "No footage in the mock" })) : file(req, res, path);
  handled.catch((error: Error) => send(res, 500, { detail: error.message }));
});
server.on("upgrade", (req, socket) => {
  const match = new URL(req.url || "/", "http://mock").pathname.match(/^\/viewer-api\/matches\/([^/]+)\/sessions\/([^/]+)\/live$/);
  const accept = createHash("sha1").update(`${req.headers["sec-websocket-key"]}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`).digest("base64");
  socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
  socket.on("error", () => sockets.delete(socket));
  socket.on("close", () => { sockets.delete(socket); socketTokens.delete(socket); });
  if (!match || !matches.has(match[1]!)) return close(socket, 4404);
  sockets.set(socket, match[1]!);
  socketTokens.set(socket, match[2]!);
  frame(socket, 1, Buffer.from(JSON.stringify(snapshot(match[1]!, match[2]))));
});
setInterval(() => {
  for (const [socket, id] of sockets) if (matches.has(id)) frame(socket, 1, Buffer.from(JSON.stringify(snapshot(id, socketTokens.get(socket)))));
}, 2000);
server.listen(port, "127.0.0.1", () => console.log(`Mock at http://127.0.0.1:${port}/`));
