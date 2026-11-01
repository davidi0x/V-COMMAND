import { test } from "node:test";
import assert from "node:assert/strict";
import { firstSessionVersions } from "./service.ts";
test("sessions keeps first occurrence", () => {
  assert.deepEqual(firstSessionVersions([{ id: 1, v: "a6" }, { id: 2, v: "b" }, { id: 1, v: "c" }]), ["a6", "b"]);
});
