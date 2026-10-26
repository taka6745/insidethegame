import { MatchApi, friendly, validMatchId } from "./api.ts";
import { MatchPicker, sides } from "./picker.ts";
import { MatchView } from "./view.ts";
import { QuestionView, sendsOnEnter } from "./chat-view.ts";
import { LiveConnection } from "./live.ts";
import { MatchController } from "./controller.ts";
import { FollowController } from "./follow.ts";
import { FollowView } from "./follow-view.ts";
import { attachDemoVideo } from "./video.ts";
import { queueStill, ReplayStage, replayStill } from "./replay-view.ts";
import { cachePrices, validPrices } from "./receipt.ts";
import { DemoControls, SkipOverlay, demoMatches, mainToOpen, showLiveFrom, showSkip, withRunClocks } from "./demo.ts";
import { DemoProgress } from "./demo-progress.ts";
import { browserStorage, viewerId } from "./viewer-id.ts";

const byId = <T extends HTMLElement = HTMLElement>(id: string) =>
  document.getElementById(id) as T;

const params = new URLSearchParams(location.search);
const matchId = params.get("match");
const api = new MatchApi(undefined, undefined, validMatchId(matchId) ? matchId : "");
const COLD_START_MS = 1500;  // a picker still loading after this shows the start-up progress
const MATCHES_TIMEOUT_MS = 20_000;  // a match list slower than this is retried, never waited on forever
if (!api.match) showPicker(params.get("gone"));
else openMatch();

/** No match chosen (or it went away): list matches, refreshing while the picker is open. */
function showPicker(gone: string | null) {
  byId("match-view").hidden = true;
  byId("match-picker").hidden = false;
  byId("audience-controls").hidden = true;
  const picker = new MatchPicker(document);
  const demo = new DemoControls(document);
  demo.progress = new DemoProgress(document);
  // The demo's own notices (a refused start, "Demo cancelled.") stay until the next action; the picker only
  // clears its start-up/retry notice.
  let startup = false;
  demo.notice = (message) => { startup = false; picker.notice(message); };
  if (gone !== null) picker.notice("That match has finished or was removed. Choose another match.");
  // A live demo opens on its main game; "All matches" (?choose) keeps the picker for switching games.
  const choosing = params.has("choose") || gone !== null;
  // A cold load (apps scaled to zero) shows each stage waking instead of a bare "Loading matches…".
  let loaded = false;
  let loading = false;
  setTimeout(() => { if (!loaded) void demo.watch(); }, COLD_START_MS);
  const refresh = async () => {
    if (loading) return;  // one load at a time; the interval retries
    loading = true;
    try {
      const [, list] = await Promise.all([demo.refresh(), api.matches(MATCHES_TIMEOUT_MS)]);
      loaded = true;
      if (startup) { startup = false; picker.notice(""); }
      const matches = demoMatches(list, demo.live, demo.main, demo.runs, demo.recording);
      const main = mainToOpen(demo, matches, choosing);
      if (main) return location.assign(`/?match=${encodeURIComponent(main)}`);
      picker.render(withRunClocks(matches, demo.feedRuns));
    } catch (error) {
      startup = true;
      picker.notice(loaded ? friendly(error) : "Still starting up. Retrying…");
    } finally {
      loading = false;
    }
  };
  demo.onChange = () => void refresh();
  void refresh();
  setInterval(() => void refresh(), 5000);
}

function openMatch() {
void showLiveFrom(document, api.match);

const view = new MatchView(document);
const video = attachDemoVideo(document);
view.video = video;
const questions = new QuestionView(document);
const stage = new ReplayStage(document);
questions.onReplayPlay = (replay, opener) => stage.open(replay, opener);
questions.onReplayFrame = (replay, canvas) => queueStill(canvas, () => replayStill(replay, canvas));
view.onPlaylistPlay = (replay, opener) => stage.open(replay, opener);
const live = new LiveConnection({
  onSnapshot: (snapshot) => controller.receive(snapshot),
  onState: (state) => controller.connection(state),
});
const controller = new MatchController({
  api,
  view,
  questions,
  live,
  storage: sessionStorage,
  viewer: viewerId(browserStorage()),
  playhead: () => video.playhead(),
  onGone: () => location.replace(`/?gone=${encodeURIComponent(api.match)}`),
});
// Skip ahead blocks the whole page (nav, picker links, questions) while the clock runs to the target.
const overlay = new SkipOverlay(document);
overlay.onFreeze = (on) => {
  const footage = byId<HTMLVideoElement>("match-video");
  if (on) footage.pause();
  else void footage.play().catch(() => undefined);
  for (const region of document.querySelectorAll<HTMLElement>(".masthead, #match-main, footer")) region.inert = on;
};
controller.onShown = (snapshot) => overlay.clock(snapshot.match.clock_seconds);
void showSkip(document, api.match, undefined, { overlay, clock: () => controller.shown?.match.clock_seconds });
const followView = new FollowView(document);
const follows = new FollowController({ api, view: followView, host: controller });
controller.follows = follows;
const followInput = byId<HTMLInputElement>("follow-input");
/** The follow view: its chat replaces Insights while a follow is set up; Cancel returns to Insights. */
function followSetup(open: boolean) {
  view.followSetup = open;
  if (controller.shown) view.feed(controller.shown);
  else {
    byId("follow-chat").hidden = !open;
    byId("follow-open").hidden = open;
    byId("narratives").hidden = open;
  }
  if (open) {
    void follows.suggest();
    followInput.focus();
  }
}
byId("follow-open").addEventListener("click", () => followSetup(true));
byId("follow-cancel").addEventListener("click", () => followSetup(false));
followView.onFollow = async (option) => {
  await follows.follow(option);
  if (controller.shown?.follow) followSetup(false);
};
followView.onUnfollow = () => follows.unfollow();
followView.onWrite = () => followInput.focus();
follows.onRetryPrompt = (prompt) => {
  followInput.value = prompt;
};
byId("follow-stop").addEventListener("click", () => follows.unfollow());
byId("follow-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const prompt = followInput.value.trim();
  if (!prompt || follows.busy) return;
  followInput.value = "";
  void follows.send(prompt);
});
// New storylines and key moments change what is worth following.
setInterval(() => {
  if (!controller.shown?.follow) void follows.suggest();
}, 30_000);
// Branding and the page title come from the listing (once the match has opened); the snapshot
// may carry branding too. The session decides whether the match is gone or not open yet.
let branded = false;
controller.onOpened = () => {
  if (branded) return;
  api.matches().then((matches) => {
    const match = matches.find((entry) => entry.match_id === api.match);
    if (!match || branded) return;
    branded = true;
    view.teams = match.teams;
    const [home, away] = sides(match.teams);
    document.title = `${home?.name || "Home"} v ${away?.name || "Away"} · Inside the Game`;
    if (controller.shown) view.render(controller.shown);
  }).catch(() => undefined);
};
// The pre-match countdown ticks between snapshots.
setInterval(() => view.tick(), 1000);
// Held live states are released as the live picture advances.
byId("match-video").addEventListener("timeupdate", () => controller.release());
const field = byId<HTMLTextAreaElement>("question-input");
controller.onRetryPrompt = (prompt) => {
  field.value = prompt;
};

const tabs = [...document.querySelectorAll<HTMLElement>("[role=tab]")];
function selectTab(selected: HTMLElement) {
  tabs.forEach((tab) => {
    const active = tab === selected;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    byId(String(tab.getAttribute("aria-controls"))).hidden = !active;
  });
  // The chat renders while hidden, so it cannot tell it was at the bottom: open on the newest turn.
  const chat = byId("chat-messages");
  if (!chat.closest("[hidden]")) chat.scrollTop = chat.scrollHeight;
}
tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectTab(tab));
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = (
      event.key === "Home"
        ? tabs[0]
        : event.key === "End"
          ? tabs.at(-1)
          : tabs[
              (index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) %
                tabs.length
            ]
    ) as HTMLElement;
    selectTab(next);
    next.focus();
  });
});
// "Follow this story?" on an answer: the follow view opens with the question sent to its chat, which proposes the
// story (this match or another live one); the viewer still confirms the follow.
questions.onFollowOffer = (offer) => {
  selectTab(byId("stories-tab"));
  if (controller.shown?.follow) return;  // already following: the tab shows it, with Stop following
  followSetup(true);
  void follows.send(offer.prompt);
};
byId("audience-bucket").addEventListener("change", () =>
  controller.selectAudience(view.audience.selection()),
);
byId("reconnect").addEventListener("click", () => controller.connect());
field.addEventListener("keydown", (event) => {
  if (!sendsOnEnter(event)) return;
  event.preventDefault();
  byId<HTMLFormElement>("question-form").requestSubmit();
});
byId("question-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const prompt = field.value.trim();
  if (!prompt || controller.busy || !controller.token) return;
  field.value = "";
  controller.send(prompt);
});
for (const button of document.querySelectorAll<HTMLElement>("[data-prompt]"))
  button.addEventListener("click", () =>
    controller.send(String(button.dataset.prompt)),
  );
window.addEventListener("offline", () => view.connection("offline"));
window.addEventListener("online", () => {
  if (controller.token)
    live.connect(controller.api.socketUrl(controller.token));
});
window.addEventListener("pagehide", () => controller.stop());
window.addEventListener("pageshow", (event) => {
  if (event.persisted) controller.connect({ restore: true });
});
// The token lives in this tab's sessionStorage, so any load in this tab (reload, picker, Start demo) resumes its own
// session; only Reconnect takes over from another tab. Starting fresh here failed this tab's own pending question.
controller.start().catch((error: Error) => {
  view.error(friendly(error));
  view.connection("offline");
});

// Receipts cost answers at the backend's configured prices; the last ones seen are cached offline.
const refreshPrices = () => api.prices().then((prices) => {
  if (!validPrices(prices)) return;
  cachePrices(prices);
  questions.setPrices({ input: prices.input, output: prices.output });
}).catch(() => undefined);
void refreshPrices();
setInterval(() => void refreshPrices(), 60_000);
}
