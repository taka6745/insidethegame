import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { check, placeholders } from "../dev/prompts.ts";
import { draftIssue, expandBuckets, MAX_BUCKETS, templateConfig } from "../dev/audiences.ts";
import { formatSelections, parseSelections, profilesIssue } from "../dev/profiles.ts";

test("prompt placeholders follow the backend rule and ignore JSON braces", () => {
  assert.deepEqual(placeholders('Use {match_events} then {user_type}, {match_events}. Reply {"summary": "x"}'),
    ["match_events", "user_type"]);
  const required = ["match_events", "user_type"];
  assert.equal(check("{match_events} {user_type}", required).issue, "");
  assert.match(check("{match_events}", required).issue, /Missing \{user_type\}/);
  assert.deepEqual(check("{match_events} {user_type} {other}", required).extra, ["other"]);
  assert.match(check("   ", required).issue, /empty/);
  assert.match(check("{match_events} {user_type}" + "x".repeat(20_000), required).issue, /under 20,000/);
});

test("buckets are every option combination in layer order and keep their enabled flags", () => {
  const layers = [
    { id: "team", description: "Side", options: [{ id: "home", label: "{home}", description: "Home fan" }, { id: "away", description: "Away fan" }] },
    { id: "fan_style", description: "Depth", options: [{ id: "simple", description: "New" }] },
  ];
  const previous = [{ id: "away:simple", selections: { team: "away", fan_style: "simple" }, enabled: true }];
  assert.deepEqual(expandBuckets(layers, previous), [
    { id: "home:simple", selections: { team: "home", fan_style: "simple" }, enabled: false },
    { id: "away:simple", selections: { team: "away", fan_style: "simple" }, enabled: true }]);
  // A new option adds disabled buckets; removing a layer keeps nothing it cannot match.
  layers[1]!.options.push({ id: "analytical", description: "Stats" });
  assert.deepEqual(expandBuckets(layers, previous).filter((b) => b.enabled).map((b) => b.id), ["away:simple"]);
  assert.deepEqual(expandBuckets([], previous), []);
  const config = { layers, buckets: expandBuckets(layers, previous) };
  assert.equal(draftIssue(config), "");
  assert.match(draftIssue({ ...config, layers: [] }), /at least one layer/);
  assert.match(draftIssue({ ...config, layers: [{ ...layers[0]!, id: "Team" }] }), /lowercase/);
  assert.match(draftIssue({ ...config, layers: [layers[0]!, layers[0]!] }), /used twice/);
  assert.match(draftIssue({ ...config, layers: [{ ...layers[0]!, description: " " }] }), /Describe the team layer/);
  assert.match(draftIssue({ ...config, layers: [{ ...layers[0]!, options: [] }] }), /Add an option/);
  assert.match(draftIssue({ ...config, buckets: Array(MAX_BUCKETS + 1).fill(config.buckets[0]) }), /at most 48/);
  assert.match(draftIssue({ ...config, layers: Array.from({ length: 9 }, (_, i) => ({ ...layers[1]!, id: `l${i}` })) }), /at most 8/);
  const many = { ...layers[1]!, options: Array.from({ length: 21 }, (_, i) => ({ id: `o${i}`, description: "x" })) };
  assert.match(draftIssue({ ...config, layers: [many] }), /at most 20/);
  assert.match(draftIssue({ ...config, buckets: [{ ...config.buckets[0]!, id: "a".repeat(101) }] }), /over 100/);
});

test("renaming a layer or option keeps its buckets' enabled flags", () => {
  const before = [
    { id: "team", description: "Side", options: [{ id: "home", description: "Home" }, { id: "away", description: "Away" }] },
    { id: "fan_style", description: "Depth", options: [{ id: "simple", description: "New" }] },
  ];
  const previous = expandBuckets(before).map((b) => ({ ...b, enabled: b.id === "away:simple" }));
  const after = [{ ...before[0]!, options: [before[0]!.options[0]!, { id: "visitors", description: "Away" }] },
    { ...before[1]!, id: "style" }];
  assert.deepEqual(expandBuckets(after, previous, before).filter((b) => b.enabled),
    [{ id: "visitors:simple", selections: { team: "visitors", style: "simple" }, enabled: true }]);
});

test("a combination still selected keeps its bucket id through edits", () => {
  const layers = [
    { id: "team", description: "Side", options: [{ id: "home", description: "Home" }] },
    { id: "length", description: "How long", options: [{ id: "standard", description: "Usual", in_label: false }, { id: "brief", description: "Short" }] },
  ];
  const previous = [{ id: "home", selections: { team: "home", length: "standard" }, enabled: true },
    { id: "home:brief", selections: { team: "home", length: "brief" }, enabled: false }];
  assert.deepEqual(expandBuckets(layers, previous).map((b) => b.id), ["home", "home:brief"]);
  assert.deepEqual(expandBuckets(layers, previous, layers).map((b) => [b.id, b.enabled]), [["home", true], ["home:brief", false]]);
});

test("saving a template keeps each option's team and in_label", () => {
  const saved = templateConfig({
    layers: [{ id: "length", description: " How long. ", options: [
      { id: "standard", label: "Standard", in_label: false, description: "Usual. " },
      { id: "brief", label: " ", team: null, in_label: null, description: "Short." }] },
    { id: "team", description: "Side.", options: [{ id: "home", label: "{home}", team: "home", description: "Home." }] }],
    buckets: [],
  });
  assert.deepEqual(saved.layers.map((layer) => layer.options), [
    [{ id: "standard", label: "Standard", in_label: false, description: "Usual." }, { id: "brief", description: "Short." }],
    [{ id: "home", label: "{home}", team: "home", description: "Home." }]]);
});

test("profile drafts need unique ids, a name and option ids", () => {
  const row = { id: "riverton-analytical", display_name: "Riverton Rovers analyst", selections: "team=home, fan_style=analytical" };
  assert.equal(profilesIssue([row]), "");
  assert.match(profilesIssue([]), /at least one/);
  assert.match(profilesIssue([row, row]), /used twice/);
  assert.match(profilesIssue([{ ...row, id: "Bad id" }]), /Row 1: id/);
  assert.match(profilesIssue([{ ...row, display_name: " " }]), /name/);
  assert.match(profilesIssue([{ ...row, selections: "team" }]), /layer=option/);
  assert.match(profilesIssue([{ ...row, selections: "team=home, team=away" }]), /layer=option/);
  assert.equal(profilesIssue([{ ...row, selections: "side=blues" }]), "");  // any layer: the backend checks the template
});

test("profile selections round-trip between the map and the editor text", () => {
  const selections = { side: "blues", fan_style: "simple" };
  assert.deepEqual(parseSelections(formatSelections(selections)), selections);
  assert.deepEqual(parseSelections(" side = blues ,, "), { side: "blues" });
  assert.equal(parseSelections("Side=blues"), null);
});

test("developer API proxies to backend /dev/ only when enabled, without caching, under the same CSP", async () => {
  const nginx = await readFile(new URL("../nginx.conf", import.meta.url), "utf8");
  assert.match(nginx, /location \/dev-api\/ \{\s+if \(\$dev_admin != "1"\) \{ return 404; \}\s+proxy_pass http:\/\/match_backend\/dev\/;/);
  assert.match(nginx, /viewer-api\|api\|dev-api\|feed-api\|purge-api\|demo-api\)\/ "no-store"/);
  const html = await readFile(new URL("../dev/index.html", import.meta.url), "utf8");
  assert.doesNotMatch(html, /<script(?![^>]*src=)|style=/);
});

import { CONFIG_TABLES, ConflictError, DevApi, PURGE_OWNERS } from "../dev/api.ts";
import { parseDraft } from "../dev/config.ts";
import { purgeSummary } from "../dev/matches.ts";

function devApi(reply: (url: string, init: RequestInit) => Response) {
  const calls: [string, RequestInit][] = [];
  const api = new DevApi("/dev-api", "/feed-api", (async (url: string, init: RequestInit) => {
    calls.push([url, init]);
    return reply(url, init);
  }) as typeof fetch);
  return { api, calls };
}
const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers });

test("purge runs feed, ETL, engine, backend in order and stops at the first failure", async () => {
  const ok = devApi(() => json({ match_ids: ["m1"], purged: { rows: 2 } }));
  const results = await ok.api.purge({ match_id: "m1" });
  assert.deepEqual(ok.calls.map(([url]) => url), PURGE_OWNERS.map((owner) => owner.path));
  assert.deepEqual(ok.calls.map(([, init]) => JSON.parse(String(init.body))), Array(4).fill({ match_id: "m1" }));
  assert.equal(purgeSummary(results), "feed 2 · etl 2 · engine 2 · backend 2");
  const failing = devApi((url) => url.includes("engine") ? json({ detail: "busy" }, 503) : json({ match_ids: [], purged: {} }));
  await assert.rejects(failing.api.purge({ all: true }), /stopped at engine: busy/);
  assert.equal(failing.calls.length, 3);
});

test("feed console starts a fixture at the next minute; nothing else goes to the feed", async () => {
  const { api, calls } = devApi(() => json({ run_id: "r", match_id: "f-1", fixture: "f", kickoff: "2026-10-20T15:00:00Z", status: "scheduled" }, 201));
  await api.startRun("riverton-forgeham");
  assert.deepEqual([calls[0]![0], JSON.parse(String(calls[0]![1].body))], ["/feed-api/runs", { fixture: "riverton-forgeham", kickoff: "next-minute" }]);
});

test("config tables use ETag polling and revision-checked saves with conflicts kept as drafts", async () => {
  const etag = '"presentation-3"';
  const { api, calls } = devApi((url, init) => {
    const headers = new Headers(init.headers);
    if (init.method === "PUT") return headers.get("If-Match") === etag ? json({ revision: 4 }) : json({ detail: "stale" }, 409);
    return headers.get("If-None-Match") === etag ? new Response(null, { status: 304 })
      : json({ table: "presentation", revision: 3, value: { slots: 5 } }, 200, { ETag: etag });
  });
  const loaded = await api.table("presentation");
  assert.equal(loaded!.etag, etag);
  assert.equal(await api.table("presentation", etag), null);
  assert.deepEqual(await api.saveTable("presentation", { slots: 4 }, 3, etag), { revision: 4 });
  assert.deepEqual(JSON.parse(String(calls[2]![1].body)), { value: { slots: 4 }, expected_revision: 3 });
  await assert.rejects(api.saveTable("presentation", {}, 2, '"old"'), ConflictError);
  assert.deepEqual(CONFIG_TABLES.map((t) => t.id), ["presentation", "replay-timing", "key-moment-ranks", "prices", "stream",
    "subscriptions", "key-moment-feed", "storyline-policy", "cross-match", "follow-offer", "models"]);
  assert.equal(parseDraft('{"a":1}').issue, "");
  assert.match(parseDraft("{").issue, /Not valid JSON/);
  assert.match(parseDraft(" ").issue, /empty/);
});

test("developer consoles are gated in nginx; media proxies only per-match playlists and segments", async () => {
  const nginx = await readFile(new URL("../nginx.conf", import.meta.url), "utf8");
  for (const location of ["location /feed-api/", "location ^~ /lab/", "location ^~ /dev/", "location = /purge-api/etl", "location = /purge-api/engine", "location = /purge-api/backend"])
    assert.match(nginx, new RegExp(`${location.replace(/[/.^]/g, "\\$&")} \\{\\s+if \\(\\$dev_admin != "1"\\) \\{ return 404; \\}`));
  assert.match(nginx, /map "\$\{ENABLE_DEV_ADMIN\}" \$dev_admin \{\s+default 0;/);
  assert.match(nginx, /location ~ "\^\/media\/hls\/\(\[a-z0-9\]\[a-z0-9-\]\{0,63\}\)\/\(\[A-Za-z0-9_-\]\{1,64\}\\\.\(\?:m3u8\|ts\)\)\$" \{\s+proxy_pass http:\/\/media_origin\/hls\/\$1\/\$2;/);
  assert.match(nginx, /location \/media\/ \{\s+return 404;/);
  assert.doesNotMatch(nginx, /try_files \$uri =404;\s+\}\s+# No other media/);
  // The public demo API: only these five routes (start, cancel, skip; state, status), method- and rate-limited.
  assert.deepEqual([...nginx.matchAll(/location[^{]*demo-api[^{]*\{/g)].map(([found]) => found),
    ['location ~ "^/demo-api/(?<demo_write_op>start|cancel|skip)$" {', 'location ~ "^/demo-api/(?<demo_read_op>state|status)$" {']);
  assert.match(nginx, /start\|cancel\|skip\)\$" \{\s+limit_except POST \{ deny all; \}\s+limit_req zone=demo_write /);
  assert.match(nginx, /state\|status\)\$" \{\s+limit_except GET \{ deny all; \}\s+limit_req zone=demo_read /);
  // limit_req evaluates the key map's regex, which resets numbered captures: rate-limited routes use named ones.
  for (const [, block] of nginx.matchAll(/location[^{]*demo-api[^{]*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}/g))
    assert.doesNotMatch(block!, /\$\d/);
  // The per-client key is the last X-Forwarded-For hop (appended by the ingress), never a client-sent value.
  const key = /"(~[^"]+)" \$last_hop;/.exec(nginx)?.[1]?.slice(1).replace("(?<last_hop>", "(");
  assert.ok(key);
  const lastHop = (xff: string) => new RegExp(key!).exec(xff)?.[1];
  assert.equal(lastHop("6.6.6.6, 203.0.113.9"), "203.0.113.9");
  assert.equal(lastHop("203.0.113.9"), "203.0.113.9");
  for (const page of ["../match/main.ts", "../lab/api.ts", "../lab/controller.ts", "../match/api.ts"])
    assert.doesNotMatch(await readFile(new URL(page, import.meta.url), "utf8"), /feed-api|purge-api/);
});

test("audience templates are listed, read and saved per fixture with revision conflicts kept", async () => {
  const { api, calls } = devApi((url, init) => init.method === "PUT" && url.includes("stale")
    ? json({ code: "audience_revision_conflict", detail: "Reload" }, 409) : json({ revision: 5, templates: [], matches: [] }));
  await api.templates();
  await api.template("riverton-forgeham");
  const config = { layers: [], buckets: [{ id: "home", selections: { team: "home" }, enabled: true }] };
  await api.saveTemplate("riverton-forgeham", config, 4);
  await assert.rejects(api.saveTemplate("stale", config, 1), ConflictError);
  assert.deepEqual(calls.map(([url, init]) => `${init.method ?? "GET"} ${url}`), [
    "GET /dev-api/audience-templates",
    "GET /dev-api/fixtures/riverton-forgeham/audience-config",
    "PUT /dev-api/fixtures/riverton-forgeham/audience-config",
    "PUT /dev-api/fixtures/stale/audience-config"]);
  assert.deepEqual(JSON.parse(String(calls[2]![1].body)), { config, expected_revision: 4 });
  assert.match(parseDraft("[1]").issue, /JSON object/);
});

test("profiles poll with If-None-Match and save with the revision; conflicts are ConflictError", async () => {
  const etag = '"profiles-2"';
  const document = { revision: 2, profiles: [{ id: "p", display_name: "P", selections: { team: "home", fan_style: "simple" } }] };
  const { api, calls } = devApi((url, init) => {
    const headers = new Headers(init.headers);
    if (init.method === "PUT") return JSON.parse(String(init.body)).expected_revision === 2
      ? json({ ...document, revision: 3 }) : json({ code: "profiles_revision_conflict", detail: "stale" }, 409);
    return headers.get("If-None-Match") === etag ? new Response(null, { status: 304 }) : json(document, 200, { ETag: etag });
  });
  assert.deepEqual(await api.profiles(), { document, etag });
  assert.equal(await api.profiles(etag), null);
  assert.equal((await api.saveProfiles(document.profiles, 2)).revision, 3);
  assert.deepEqual(JSON.parse(String(calls[2]![1].body)), { profiles: document.profiles, expected_revision: 2 });
  await assert.rejects(api.saveProfiles(document.profiles, 1), ConflictError);
});
