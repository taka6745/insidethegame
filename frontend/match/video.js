// The shared replay clock owns aligned footage; viewers cannot scrub ahead.
export function attachDemoVideo(document, {
  reducedMotion = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches || false,
} = {}) {
  const video = document.getElementById("match-video");
  const empty = document.getElementById("video-empty");
  let aligned = false;
  let currentMatch = null;
  let lastAnchor = null;
  const describe = () => video.setAttribute("aria-label",
    video.paused ? "Play match footage" : "Pause match footage");
  const start = async () => {
    try {
      await video.play();
    } catch {
      // A click or keyboard activation can retry after blocked autoplay.
    }
    describe();
  };
  const toggle = () => aligned
    ? (currentMatch?.status === "running" ? start() : undefined)
    : video.paused ? start() : video.pause();
  video.addEventListener("loadeddata", () => {
    video.hidden = false;
    empty.hidden = true;
    describe();
  });
  video.addEventListener("play", describe);
  video.addEventListener("pause", describe);
  video.addEventListener("error", () => {
    video.hidden = true;
    empty.hidden = false;
  });
  video.addEventListener("click", toggle);
  video.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggle();
    }
  });
  video.tabIndex = 0;
  video.setAttribute("role", "button");
  video.muted = true;
  video.loop = true;
  video.autoplay = !reducedMotion;
  video.preload = "auto";
  video.src = "/media/simulator.mp4";
  if (!reducedMotion) start();
  return {
    sync(match) {
      if (!match.media?.aligned) return;
      aligned = true;
      currentMatch = match;
      video.loop = false;
      const anchor = `${match.run_id}:${match.status}:${match.media.sampled_at ?? match.media.seconds}`;
      const elapsed = match.status === "running" && Number.isFinite(match.media.sampled_at)
        ? Math.max(0, (Date.now() - match.media.sampled_at) / 1000) : 0;
      const target = Math.max(0, Number(match.media.seconds) || 0) + elapsed;
      if (anchor !== lastAnchor && (Math.abs((video.currentTime || 0) - target) > 1.5 || match.status !== "running"))
        video.currentTime = target;
      lastAnchor = anchor;
      if (match.status === "running") start();
      else video.pause();
      video.setAttribute("aria-label", "Live match footage");
    },
    disconnect() {
      if (aligned) {
        video.pause();
        lastAnchor = null;
      }
    },
  };
}
