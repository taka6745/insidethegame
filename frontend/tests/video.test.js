import test from "node:test";
import assert from "node:assert/strict";
import { attachDemoVideo } from "../match/video.js";

function setup(options) {
  const elements = Object.fromEntries(
    ["match-video", "video-empty"].map(id => [id, {
      hidden: true, listeners: {},
      setAttribute(name, value) { this[name] = value; },
      addEventListener(name, fn) { this.listeners[name] = fn; },
    }]),
  );
  elements["match-video"].paused = true;
  elements["match-video"].play = async () => { elements["match-video"].paused = false; };
  elements["match-video"].pause = () => { elements["match-video"].paused = true; elements["match-video"].listeners.pause(); };
  attachDemoVideo({ getElementById: id => elements[id] }, options);
  return elements;
}

test("optional footage is silent, and missing media preserves the empty state", async () => {
  const elements = setup(), video = elements["match-video"];
  assert.equal(video.src, "/media/simulator.mp4");
  assert.equal(video.muted, true);
  assert.equal(video.loop, true);
  video.listeners.loadeddata();
  await Promise.resolve();
  assert.equal(video.hidden, false);
  assert.equal(elements["video-empty"].hidden, true);
  video.listeners.error();
  assert.equal(video.hidden, true);
  assert.equal(elements["video-empty"].hidden, false);
});

test("reduced motion starts paused and the footage toggle can play and pause without seeking", async () => {
  const elements = setup({ reducedMotion: true }), video = elements["match-video"];
  video.listeners.loadeddata();
  assert.equal(video.autoplay, false);
  assert.equal(video.paused, true);
  assert.equal(video.tabIndex, 0);
  await video.listeners.click();
  assert.equal(video.paused, false);
  assert.equal(video["aria-label"], "Pause match footage");
  await video.listeners.click();
  assert.equal(video.paused, true);
  assert.equal(video["aria-label"], "Play match footage");
});

test("blocked play keeps a deliberate retry available", async () => {
  const elements = setup({ reducedMotion: true }), video = elements["match-video"];
  video.play = async () => { throw new Error("Autoplay blocked"); };
  video.listeners.loadeddata();
  await video.listeners.click();
  assert.equal(video.tabIndex, 0);
  assert.equal(video["aria-label"], "Play match footage");
});

test("keyboard activation toggles footage and prevents page scrolling", async () => {
  const elements = setup({ reducedMotion: true }), video = elements["match-video"];
  let prevented = false;
  video.listeners.keydown({ key: " ", preventDefault() { prevented = true; } });
  await Promise.resolve();
  assert.equal(prevented, true);
  assert.equal(video.paused, false);
});
