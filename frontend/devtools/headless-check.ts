// Headless Chrome check: each page at 1440/390/360 px for horizontal overflow, console errors and
// CSP violations. Start tools/mock-server.ts (or a real stack) first.
// Usage: node tools/headless-check.ts http://127.0.0.1:18099 [path…] [--shots DIR] [--flow follow|unavailable|sting|capture]
// --flow drives the Insights follow chat on match pages (against tools/mock-server.ts; `unavailable` with MOCK_NO_MODEL=1),
// or `sting`: the league's built-in between-clip sting fades in over the stage, drawn in CSS, and out again;
// or `capture`: captured clips show as preview cards in Insights and in the followed story (PLAN.md §10.2 D6–D7).
import { spawn } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const args = process.argv.slice(2);
const shotsAt = args.indexOf("--shots");
const shots = shotsAt >= 0 ? args.splice(shotsAt, 2)[1] : "";
const flowAt = args.indexOf("--flow");
const flow = flowAt >= 0 ? args.splice(flowAt, 2)[1] ?? "" : "";
const [origin = "http://127.0.0.1:18099", ...paths] = args;
// Each step runs in the page and returns "" or a problem; the page settles before the next.
const helpers = `const $ = (s) => document.querySelector(s), $$ = (s) => [...document.querySelectorAll(s)];
  const shown = (s) => { const el = $(s); return Boolean(el && !el.closest("[hidden]") && el.getClientRects().length); };
  const submit = (text) => { $("#follow-input").value = text; $("#follow-form").requestSubmit(); };
  const expect = (ok, problem) => ok ? "" : problem;`;
const insights = `expect(shown("#follow-open") && !shown("#follow-chat") && !shown("#follow-banner"), "Customise missing in insights mode")
  || expect($$(".key-moment").length >= 2, "key moments missing in insights mode")
  || expect(!$$(".narrative").length || $$(".narrative").at(-1).classList.contains("latest"), "newest insight not last")
  || expect($(".key-moment.overturned"), "overturned goal not marked")
  || expect($$(".narrative").length && !$(".narrative-tag"), "insights missing or tagged")`;
// Customise opens the follow chat in place of Insights: its chips wrap (no sideways scroll), Cancel is there.
const opened = `expect(shown("#follow-chat") && shown("#follow-cancel") && !shown("#narratives"), "Customise did not open the chat")
  || expect($$("#follow-suggestions button").length >= 3, "no suggestion chips")
  || expect($("#follow-suggestions").scrollWidth <= $("#follow-suggestions").clientWidth + 1, "chips scroll sideways")`;
const open = `$("#follow-open").click(); return ""`;
const following = (label: string) => `expect(shown("#follow-banner") && !shown("#follow-chat"), "banner not shown while following")
  || expect($("#follow-label").textContent.includes(${JSON.stringify(label)}), "wrong follow label: " + $("#follow-label").textContent)
  || expect($(".story-empty") || $(".narrative-tag"), "no following empty state or tagged narratives")
  || expect($$(".narrative").every((n) => n.querySelector(".narrative-tag")), "untagged narrative while following")
  || expect($$(".key-moment").length >= 2, "key moments missing while following")`;
const stop = [`$("#follow-stop").click(); return ""`, insights];
// The stage's sting as ReplayStage drives it (match/replay-view.ts sting()): the mock has no footage for a reel.
// The league's built-in sting (`builtin:league`): CSS only, no video asset.
const sting = (state: string) => `const layer = $("#replay-sting");
  $("#match-stage").dataset.mode = "replay"; layer.hidden = false; layer.dataset.kind = "builtin";
  layer.style.setProperty("--sting-fade", "0.3s"); layer.style.setProperty("--sting-length", "2.4s");
  void layer.offsetWidth; layer.dataset.state = "${state}"; return ""`;
const covers = `(() => { const a = $("#replay-sting").getBoundingClientRect(), b = $("#match-stage").getBoundingClientRect();
  return Math.abs(a.width - b.width) <= 2 && Math.abs(a.height - b.height) <= 2; })()`;  // inside the 1px border
const previews = (where: string) => `expect($$(".capture .clip-preview").length >= 2, "no clip preview cards ${where}")
  || expect($$(".capture").every((c) => c.querySelector(".clip-preview-minute").textContent
    && c.querySelector(".clip-preview-event").textContent), "a preview card lacks its minute or event ${where}")
  || expect($$(".clip-preview").every((c) => c.getBoundingClientRect().width > 120), "a preview card is collapsed ${where}")`;
const flows: Record<string, [string, string][]> = {
  capture: [
    ["insights-clips", previews("in Insights")],
    ["open", `$("#follow-open")?.click(); return ""`],
    ["chip", `$("#follow-suggestions button").click(); return ""`],
    ["following-clips", previews("in the followed story")],
    ["stop", stop[0]!],
  ],
  sting: [
    ["sting-in", sting("in")],
    ["sting-shown", `expect(getComputedStyle($("#replay-sting")).opacity === "1", "sting not faded in")
      || expect(getComputedStyle($(".league-sting")).display === "block", "built-in sting not drawn")
      || expect(${covers}, "sting does not cover the stage")`],
    ["sting-out", sting("out")],
    ["sting-gone", `expect(getComputedStyle($("#replay-sting")).opacity === "0", "sting not faded out")`],
  ],
  follow: [
    ["insights", insights],
    ["open", open], ["opened", opened],
    ["chip", `$$("#follow-suggestions button").find((b) => b.textContent.includes("Sami Lindqvist")).click(); return ""`],
    ["following", following("Sami Lindqvist")],
    ["stop", stop[0]!], ["restored", stop[1]!], ["open-2", open],
    ["chat", `submit("Follow Kai Ashworth please"); return ""`],
    ["proposal", `expect($(".follow-proposal"), "no proposal card") || ($$(".follow-proposal .follow-action").at(-1).click(), "")`],
    ["following-chat", following("Kai Ashworth")],
    ["stop-2", stop[0]!], ["restored-2", stop[1]!], ["open-3", open],
    ["ask-ambiguous", `submit("Cole or Kobbie"); return ""`],
    ["clarify", `expect($$(".clarification-option").length === 2, "no clarification candidates") || ($$(".clarification-option")[1].click(), "")`],
    ["following-clarified", following("Callum Brightwell")],
    ["stop-3", stop[0]!], ["restored-3", stop[1]!],
  ],
  unavailable: [
    ["chat", `submit("Follow Kai Ashworth"); return ""`],
    ["refused", `expect(/unavailable/i.test($("#follow-status").textContent), "no unavailable status") || expect($("#follow-input").disabled, "composer still enabled") || expect(!$("#follow-suggestions button").disabled, "chips disabled")`],
    ["chip", `$("#follow-suggestions button").click(); return ""`],
    ["following", following("")],
    ["stop", stop[0]!],
  ],
};
const pages = paths.length ? paths : ["/", "/?match=riverton-forgeham-1a2b3c4d", "/lab/", "/dev/"];
const chrome = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const port = 9300 + Math.floor(Math.random() * 500);
const profile = await mkdtemp(join(tmpdir(), "itg-headless-"));
const browser = spawn(chrome, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
  "--no-first-run", "--autoplay-policy=no-user-gesture-required", "about:blank"], { stdio: "ignore" });
const sleep = (ms: number) => new Promise((done) => setTimeout(done, ms));

let endpoint = "";
for (let attempt = 0; attempt < 50 && !endpoint; attempt++) {
  await sleep(200);
  endpoint = await fetch(`http://127.0.0.1:${port}/json/version`).then((r) => r.json()).then((v) => v.webSocketDebuggerUrl).catch(() => "");
}
if (!endpoint) {
  browser.kill();
  await rm(profile, { recursive: true, force: true });
  console.error(`Chrome did not start (${chrome}); set CHROME`);
  process.exit(1);
}
const socket = new WebSocket(endpoint);
await new Promise((done) => socket.addEventListener("open", done, { once: true }));
let id = 0;
// A protocol error rejects the call, so one failing page is reported instead of crashing the run.
const pending = new Map<number, { done: (value: any) => void; fail: (error: Error) => void }>();
const listeners: ((message: any) => void)[] = [];
socket.addEventListener("message", (event) => {
  const message = JSON.parse(String(event.data));
  const waiting = message.id ? pending.get(message.id) : undefined;
  if (waiting) {
    pending.delete(message.id);
    if (message.error) waiting.fail(new Error(`${message.error.message} (${message.error.code})`));
    else waiting.done(message);
  } else listeners.forEach((listener) => listener(message));
});
const call = (method: string, params: object = {}, sessionId?: string): Promise<any> => new Promise((done, fail) => {
  pending.set(++id, { done, fail: (error) => fail(new Error(`${method}: ${error.message}`)) });
  socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
});

let failures = 0;
for (const path of pages) for (const width of [1440, 390, 360]) {
  const { result: { targetId } } = await call("Target.createTarget", { url: "about:blank" });
  const { result: { sessionId } } = await call("Target.attachToTarget", { targetId, flatten: true });
  const problems: string[] = [];
  const listener = (message: any) => {
    if (message.sessionId !== sessionId) return;
    if (message.method === "Runtime.exceptionThrown") problems.push(`exception: ${message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text}`);
    if (message.method === "Runtime.consoleAPICalled" && ["error", "warning", "assert"].includes(message.params.type))
      problems.push(`console.${message.params.type}: ${message.params.args.map((a: any) => a.value ?? a.description).join(" ")}`);
    if (message.method === "Log.entryAdded" && ["error", "warning"].includes(message.params.entry.level))
      problems.push(`log.${message.params.entry.level}: ${message.params.entry.text} ${message.params.entry.url ?? ""}`);
  };
  listeners.push(listener);
  let value: any = { url: path, title: "" };
  try {
    await call("Runtime.enable", {}, sessionId);
    await call("Log.enable", {}, sessionId);
    await call("Page.enable", {}, sessionId);
    await call("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: width < 600 }, sessionId);
    await call("Page.navigate", { url: origin + path }, sessionId);
    await sleep(3500);
    ({ result: { result: { value } } } = await call("Runtime.evaluate", { returnByValue: true, expression: `(() => {
      const width = document.documentElement.clientWidth;
      const wide = [...document.querySelectorAll("body *")].filter((el) => {
        const box = el.getBoundingClientRect();
        return box.width && getComputedStyle(el).visibility !== "hidden" && !el.closest("[hidden]") && box.right > width + 1;
      }).slice(0, 5).map((el) => el.tagName.toLowerCase() + (el.id ? "#" + el.id : "") + "." + [...el.classList].join("."));
      return { scroll: document.documentElement.scrollWidth, width, wide, title: document.title, url: location.pathname + location.search };
    })()` }, sessionId));
    if (value.scroll > value.width) problems.push(`overflow: scrollWidth ${value.scroll} > ${value.width} (${value.wide.join(", ")})`);
    const shoot = async (suffix: string) => {
      if (!shots) return;
      const { result: { data } } = await call("Page.captureScreenshot", { format: "png", captureBeyondViewport: false }, sessionId);
      await writeFile(join(shots, `${path.replace(/[^a-z0-9]+/gi, "_")}-${width}${suffix}.png`), Buffer.from(data, "base64"));
    };
    await shoot("");
    for (const [step, body] of path.includes("match=") ? flows[flow] ?? [] : []) {
      const { result: { result } } = await call("Runtime.evaluate", { returnByValue: true,
        expression: `(() => { ${helpers}\n${body.startsWith("expect") ? `return ${body};` : body} })()` }, sessionId);
      if (result.value) problems.push(`flow ${step}: ${result.value}`);
      else if (result.subtype === "error") problems.push(`flow ${step}: ${result.description}`);
      await sleep(1200);
      const { result: { result: { value: scroll } } } = await call("Runtime.evaluate", { returnByValue: true,
        expression: "document.documentElement.scrollWidth - document.documentElement.clientWidth" }, sessionId);
      if (scroll > 0) problems.push(`flow ${step}: overflow ${scroll}px`);
      await shoot(`-${step}`);
    }
  } catch (error) {
    problems.push(`protocol: ${(error as Error).message}`);
  }
  listeners.splice(listeners.indexOf(listener), 1);
  await call("Target.closeTarget", { targetId }).catch(() => undefined);
  failures += problems.length;
  console.log(`${problems.length ? "FAIL" : "ok  "} ${width}px ${path} → ${value.url} "${value.title}"`);
  for (const problem of problems) console.log(`     ${problem}`);
}
socket.close();
browser.kill();
await sleep(500);
await rm(profile, { recursive: true, force: true });
process.exit(failures ? 1 : 0);
