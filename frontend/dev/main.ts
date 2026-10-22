import { node } from "../match/dom.ts";
import { DevApi } from "./api.ts";
import { AudiencesView } from "./audiences.ts";
import { ConfigView } from "./config.ts";
import { MatchesView } from "./matches.ts";
import { ProfilesView } from "./profiles.ts";
import { PromptsView } from "./prompts.ts";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const api = new DevApi();

function notify(message: string, error = false) {
  const notice = $("notice");
  notice.textContent = message;
  notice.dataset.kind = error ? "error" : "info";
  notice.hidden = false;
}

const audiences = new AudiencesView(document, api, notify);
const prompts = new PromptsView(document, api, notify);
const config = new ConfigView(document, api, notify);
const profiles = new ProfilesView(document, api, notify);
const matches = new MatchesView(document, api, notify);
matches.onSelect = (fixture) => audiences.choose(fixture);
addEventListener("beforeunload", (event) => {
  if (audiences.dirty || prompts.dirty || config.dirty || profiles.dirty) event.preventDefault();
});

async function pipeline() {
  const [services] = await Promise.allSettled([api.pipeline()]);
  const counts = new Map<string, number>();
  for (const run of matches.runs) counts.set(run.status, (counts.get(run.status) ?? 0) + 1);
  const facts: [string, string][] = [["Runs", matches.runs.length ? [...counts].map(([status, n]) => `${n} ${status}`).join(" · ") : "none"]];
  $("replay").replaceChildren(...facts.flatMap(([k, v]) => [node(document, "dt", k), node(document, "dd", v)]));
  const gaps = services.status === "fulfilled" ? services.value.gaps ?? [] : [];
  $("gaps").replaceChildren(...(gaps.length ? gaps.map((gap) => {
    const row = node(document, "li");
    row.dataset.status = gap.state === "recovered" ? "ok" : gap.state;
    row.title = `${gap.pending} later events waiting · ${Math.round(gap.age_seconds)}s`;
    row.append(node(document, "span", `${gap.match_id} · seq ${gap.seq}`), node(document, "span", gap.state, "pill"));
    return row;
  }) : [node(document, "li", "None")]));
  const rows = services.status === "fulfilled" ? services.value.services
    : [{ name: "user-backend", status: "unavailable", detail: (services.reason as Error).message }];
  $("services").replaceChildren(...rows.map((service) => {
    const row = node(document, "li");
    row.dataset.status = service.status;
    row.title = service.detail ?? (service.http_status ? `HTTP ${service.http_status}` : "");
    row.append(node(document, "span", service.name), node(document, "span", service.status, "pill"));
    return row;
  }));
  $("pipeline-updated").textContent = `Updated ${new Date().toLocaleTimeString("en-GB")}`;
}

const failed = (what: string) => (error: Error) => notify(`${what} unavailable: ${error.message}`, true);
void audiences.load().catch(failed("Audiences"));
void prompts.load().catch(failed("Prompts"));
void config.load(true).catch(failed("Config"));
void profiles.load(true).catch(failed("Profiles"));
void matches.load().then(pipeline);
setInterval(() => {
  void matches.load().then(pipeline);
  void audiences.load().catch(() => undefined);
  void config.load().catch(() => undefined);
  void profiles.load().catch(() => undefined);
}, 4000);
