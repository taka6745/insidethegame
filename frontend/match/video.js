// Optional local footage. Its clock is independent of fixture events.
export function attachDemoVideo(document, {
  reducedMotion = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches || false,
} = {}) {
  const video = document.getElementById("match-video");
  const empty = document.getElementById("video-empty");
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
  const toggle = () => video.paused ? start() : video.pause();
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
}
