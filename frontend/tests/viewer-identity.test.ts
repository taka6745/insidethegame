import test from "node:test";
import assert from "node:assert/strict";
import { browserStorage, randomUuid, viewerId } from "../match/viewer-id.ts";
import { MatchApi, friendly } from "../match/api.ts";

function memory() {
  const items = new Map<string, string>();
  return { getItem: (k: string) => items.get(k) ?? null, setItem: (k: string, v: string) => void items.set(k, v) };
}

const ID_1 = "6f1c2a3b-4d5e-4f60-8a7b-9c0d1e2f3a4b", ID_2 = "0a1b2c3d-4e5f-4a6b-9c7d-8e9f0a1b2c3d";

test("each browser is its own viewer: its id persists across loads, another browser gets another id", () => {
  const ids = [ID_1, ID_2];
  const uuid = () => ids.shift()!;
  const one = memory(), two = memory();
  assert.equal(viewerId(one, uuid), ID_1);
  assert.equal(viewerId(one, uuid), ID_1);  // the same browser again
  assert.equal(viewerId(two, uuid), ID_2);  // another browser
});

test("the default id is a random v4 UUID, also where crypto.randomUUID is missing (plain-HTTP origins)", () => {
  const shape = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  assert.match(randomUuid(), shape);
  const original = crypto.randomUUID;
  try {
    Object.defineProperty(crypto, "randomUUID", { value: undefined, configurable: true });
    const a = randomUuid(), b = randomUuid();
    assert.match(a, shape);
    assert.notEqual(a, b);
  } finally {
    Object.defineProperty(crypto, "randomUUID", { value: original, configurable: true });
  }
});

test("blocked storage still gives a viewer id for this page", () => {
  const blocked = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("denied"); } };
  assert.equal(viewerId(blocked, () => "page-only"), "page-only");
  assert.equal(viewerId(null, () => "no-storage"), "no-storage");
  assert.equal(typeof browserStorage, "function");
});

test("a stored id that is not a random UUID (tampered, guessable) is replaced", () => {
  for (const bad of ["<script>", "viewer-1", "a"]) {
    const store = memory();
    store.setItem("itg-viewer", bad);
    assert.equal(viewerId(store, () => ID_1), ID_1);
  }
});

test("sessions send the browser's viewer id", async () => {
  const calls: [string, RequestInit][] = [];
  const api = new MatchApi(async (url, init) => { calls.push([url, init]); return { ok: true, status: 200, json: async () => ({}) }; },
    "/viewer-api", "m");
  await api.session("profile", "viewer-1");
  assert.deepEqual(JSON.parse(String(calls[0]![1].body)), { profile_id: "profile", viewer_id: "viewer-1" });
});

test("a viewer never sees raw exception text", async () => {
  const api = new MatchApi(async () => { throw new TypeError("NetworkError when attempting to fetch resource."); }, "/viewer-api", "m");
  await assert.rejects(api.matches(), (error: Error & { status?: number }) =>
    error.status === 0 && !/NetworkError/.test(error.message) && /Can't reach the match service/.test(error.message));
  assert.equal(friendly(new TypeError("Cannot read properties of undefined (reading 'x')")), "Something went wrong. Please try again.");
  const service = Object.assign(new Error("Choose a demo profile."), { status: 404 });
  assert.equal(friendly(service), "Choose a demo profile.");
});
