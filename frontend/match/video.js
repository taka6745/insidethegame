// Optional local footage. Its clock is independent of fixture events.
export function attachDemoVideo(document, {
  reducedMotion = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches || false,
} = {}) {
  const video = document.getElementById("match-video");
  const empty = document.getElementById("video-empty");
  const status = document.getElementById("video-status");
  const play = document.getElementById("video-play");
  const fullscreen = document.getElementById("video-fullscreen");
  const updateControl = () => {
    play.textContent = video.paused ? "Play footage" : "Pause footage";
  };
  const start = async () => {
    try {
      await video.play();
    } catch {
      // Autoplay may be blocked; the same button offers a deliberate retry.
    }
    updateControl();
  };
  video.addEventListener("loadeddata", () => {
    video.hidden = false;
    empty.hidden = true;
    play.hidden = false;
    status.textContent = "Illustrative footage · separate demo events";
    fullscreen.hidden = !video.requestFullscreen;
    updateControl();
  });
  video.addEventListener("play", updateControl);
  video.addEventListener("pause", updateControl);
  video.addEventListener("error", () => {
    video.hidden = true;
    empty.hidden = false;
    play.hidden = true;
    fullscreen.hidden = true;
    status.textContent = "Demo footage unavailable";
  });
  play.addEventListener("click", () => {
    if (video.paused) return start();
    video.pause();
  });
  fullscreen.addEventListener("click", async () => {
    try {
      await video.requestFullscreen();
    } catch {
      status.textContent = "Full screen unavailable · illustrative footage";
    }
  });
  video.muted = true;
  video.loop = true;
  video.autoplay = !reducedMotion;
  video.preload = "auto";
  video.src = "/media/simulator.mp4";
  if (!reducedMotion) start();
}
