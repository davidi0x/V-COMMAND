import { test } from "node:test";
import assert from "node:assert/strict";
import { firstProductVersions } from "./service.ts";
test("products keeps first occurrence", () => {
  assert.deepEqual(firstProductVersions([{ id: 1, v: "a5" }, { id: 2, v: "b" }, { id: 1, v: "c" }]), ["a5", "b"]);
});
