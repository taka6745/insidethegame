import { MatchApi } from "./api.js";
import { MatchView } from "./view.js";
import { QuestionView } from "./chat-view.js";
import { LiveConnection } from "./live.js";
import { MatchController } from "./controller.js";
import { attachDemoVideo } from "./video.js";

const view = new MatchView(document);
view.video = attachDemoVideo(document);
const questions = new QuestionView(document);
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
});
const field = document.getElementById("question-input");
controller.onRetryPrompt = (prompt) => {
  field.value = prompt;
};

const tabs = [...document.querySelectorAll("[role=tab]")];
function selectTab(selected) {
  tabs.forEach((tab) => {
    const active = tab === selected;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    document.getElementById(tab.getAttribute("aria-controls")).hidden = !active;
  });
}
tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectTab(tab));
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === "Home"
        ? tabs[0]
        : event.key === "End"
          ? tabs.at(-1)
          : tabs[
              (index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) %
                tabs.length
            ];
    selectTab(next);
    next.focus();
  });
});
for (const id of ["audience-team", "audience-style"])
  document.getElementById(id).addEventListener("change", () =>
    controller.selectAudience(view.audience.selection()),
  );
document
  .getElementById("reconnect")
  .addEventListener("click", () => controller.connect());
document.getElementById("question-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const prompt = field.value.trim();
  if (!prompt || controller.busy || !controller.token) return;
  field.value = "";
  controller.send(prompt);
});
for (const button of document.querySelectorAll("[data-prompt]"))
  button.addEventListener("click", () =>
    controller.send(button.dataset.prompt),
  );
for (const [id, reset] of [
  ["start-demo", false],
  ["reset-demo", true],
])
  document.getElementById(id).addEventListener("click", async (event) => {
    const button = event.currentTarget;
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
const restore =
  performance.getEntriesByType("navigation")[0]?.type === "reload";
controller.start({ restore }).catch((error) => {
  view.error(error.message);
  view.connection("offline");
});
