import { test } from "node:test";
import assert from "node:assert/strict";
import { firstMemberVersions } from "./service.ts";
test("members keeps first occurrence", () => {
  assert.deepEqual(firstMemberVersions([{ id: 1, v: "a9" }, { id: 2, v: "b" }, { id: 1, v: "c" }]), ["a9", "b"]);
});
