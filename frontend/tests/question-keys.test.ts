import test from "node:test";
import assert from "node:assert/strict";
import { sendsOnEnter } from "../match/chat-view.ts";

test("Enter sends the question; Shift+Enter and IME composition do not", () => {
  assert.equal(sendsOnEnter({ key: "Enter", shiftKey: false, isComposing: false }), true);
  assert.equal(sendsOnEnter({ key: "Enter", shiftKey: true, isComposing: false }), false);
  assert.equal(sendsOnEnter({ key: "Enter", shiftKey: false, isComposing: true }), false);
  assert.equal(sendsOnEnter({ key: "a", shiftKey: false, isComposing: false }), false);
});
