import { test } from "node:test";
import assert from "node:assert/strict";
import { firstOrderVersions } from "./service.ts";
test("orders keeps first occurrence", () => {
  assert.deepEqual(firstOrderVersions([{ id: 1, v: "a0" }, { id: 2, v: "b" }, { id: 1, v: "c" }]), ["a0", "b"]);
});
