import test from "node:test";
import assert from "node:assert/strict";
import { clubBrand } from "../match/clubs.js";

test("official crests only apply to the actual supported club identities", () => {
  assert.equal(clubBrand({ id: "chelsea", name: "Chelsea" }).asset, "chelsea");
  assert.equal(
    clubBrand({ id: "manutd", name: "Manchester United" }).asset,
    "manutd",
  );
  assert.equal(clubBrand({ id: "madrid", name: "Madrid" }), null);
  assert.equal(clubBrand({ id: "custom", name: "<script>" }), null);
});
