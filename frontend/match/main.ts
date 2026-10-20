import { MatchApi } from "./api.ts";
import { MatchView } from "./view.ts";
import { QuestionView } from "./chat-view.ts";
import { LiveConnection } from "./live.ts";
import { MatchController } from "./controller.ts";
import { attachDemoVideo } from "./video.ts";
import { queueStill, ReplayStage, replayStill } from "./replay-view.ts";
import { DEFAULT_PRICES, savePrices } from "./receipt.ts";
import type { Prices } from "./receipt.ts";

const byId = <T extends HTMLElement = HTMLElement>(id: string) =>
  document.getElementById(id) as T;

const view = new MatchView(document);
const video = attachDemoVideo(document);
view.video = video;
const questions = new QuestionView(document);
const stage = new ReplayStage(document);
questions.onReplayPlay = (replay, opener) => stage.open(replay, opener);
questions.onReplayFrame = (replay, canvas) => queueStill(canvas, () => replayStill(replay, canvas));
const live = new LiveConnection({
  onSnapshot: (snapshot) => controller.receive(snapshot),
  onState: (state) => controller.connection(state),
});
const controller = new MatchController({
  api: new MatchApi(),
  view,
  questions,
  live,
  storage: sessionStorage,
  playhead: () => video.playhead(),
});
// Held live states are released as the live picture advances.
byId("match-video").addEventListener("timeupdate", () => controller.release());
const field = byId<HTMLInputElement>("question-input");
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
for (const id of ["audience-team", "audience-style"])
  byId(id).addEventListener("change", () =>
    controller.selectAudience(view.audience.selection()),
  );
byId("reconnect").addEventListener("click", () => controller.connect());
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
for (const [id, reset] of [
  ["start-demo", false],
  ["reset-demo", true],
] as const)
  byId(id).addEventListener("click", async (event) => {
    const button = event.currentTarget as HTMLButtonElement;
    button.disabled = true;
    try {
      await controller.demo(reset);
    } finally {
      button.disabled = false;
    }
  });
window.addEventListener("offline", () => view.connection("offline"));
window.addEventListener("online", () => {
  if (controller.token)
    live.connect(controller.api.socketUrl(controller.token));
});
window.addEventListener("pagehide", () => controller.stop());
window.addEventListener("pageshow", (event) => {
  if (event.persisted) controller.connect({ restore: true });
});
const navigation = performance.getEntriesByType("navigation")[0] as
  | PerformanceNavigationTiming
  | undefined;
const restore = navigation?.type === "reload";
controller.start({ restore }).catch((error: Error) => {
  view.error(error.message);
  view.connection("offline");
});

// Answer cost estimates use fixed prices the viewer sets; they never come from a provider.
const priceDialog = byId<HTMLDialogElement>("price-dialog");
const priceInput = byId<HTMLInputElement>("price-input");
const priceOutput = byId<HTMLInputElement>("price-output");
const showPrices = (prices: Prices) => {
  priceInput.value = String(prices.input);
  priceOutput.value = String(prices.output);
};
byId("price-settings").addEventListener("click", () => {
  showPrices(questions.prices);
  priceDialog.showModal();
});
byId("price-reset").addEventListener("click", () => showPrices(DEFAULT_PRICES));
byId("price-cancel").addEventListener("click", () => priceDialog.close());
byId("price-form").addEventListener("submit", () => {
  const prices = { input: Number(priceInput.value), output: Number(priceOutput.value) };
  if (![prices.input, prices.output].every((n) => Number.isFinite(n) && n >= 0)) return;
  savePrices(prices);
  questions.setPrices(prices);
});
