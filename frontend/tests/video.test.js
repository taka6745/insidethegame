import test from "node:test";
import assert from "node:assert/strict";
import { attachDemoVideo } from "../match/video.js";

function setup(options) {
  const elements = Object.fromEntries(
    ["match-video", "video-empty", "video-status", "video-play", "video-fullscreen"].map(id => [id, {
      hidden: true, listeners: {},
      addEventListener(name, fn) { this.listeners[name] = fn; },
    }]),
  );
  elements["match-video"].paused = true;
  elements["match-video"].play = async () => { elements["match-video"].paused = false; };
  elements["match-video"].pause = () => { elements["match-video"].paused = true; elements["match-video"].listeners.pause(); };
  elements["match-video"].requestFullscreen = async () => {};
  attachDemoVideo({ getElementById: id => elements[id] }, options);
  return elements;
}

test("optional footage is silent, labelled independently, and missing media preserves the empty state", async () => {
  const elements = setup(), video = elements["match-video"];
  assert.equal(video.src, "/media/simulator.mp4");
  assert.equal(video.muted, true);
  assert.equal(video.loop, true);
  video.listeners.loadeddata();
  await Promise.resolve();
  assert.equal(video.hidden, false);
  assert.equal(elements["video-empty"].hidden, true);
  assert.match(elements["video-status"].textContent, /separate demo events/);
  video.listeners.error();
  assert.equal(video.hidden, true);
  assert.equal(elements["video-empty"].hidden, false);
  assert.equal(elements["video-fullscreen"].hidden, true);
});

test("reduced motion starts paused and the footage toggle can play and pause without seeking", async () => {
  const elements = setup({ reducedMotion: true }), video = elements["match-video"];
  video.listeners.loadeddata();
  assert.equal(video.autoplay, false);
  assert.equal(video.paused, true);
  assert.equal(elements["video-play"].hidden, false);
  await elements["video-play"].listeners.click();
  assert.equal(video.paused, false);
  assert.equal(elements["video-play"].textContent, "Pause footage");
  await elements["video-play"].listeners.click();
  assert.equal(video.paused, true);
  assert.equal(elements["video-play"].textContent, "Play footage");
});

test("blocked play keeps a deliberate retry available", async () => {
  const elements = setup({ reducedMotion: true }), video = elements["match-video"];
  video.play = async () => { throw new Error("Autoplay blocked"); };
  video.listeners.loadeddata();
  await elements["video-play"].listeners.click();
  assert.equal(elements["video-play"].hidden, false);
  assert.equal(elements["video-play"].textContent, "Play footage");
});

test("full screen rejection is handled without interrupting match data", async () => {
  const elements = setup();
  elements["match-video"].requestFullscreen = async () => { throw new Error("Denied"); };
  await elements["video-fullscreen"].listeners.click();
  assert.match(elements["video-status"].textContent, /Full screen unavailable/);
});
