import { test } from "node:test";
import assert from "node:assert/strict";
import { recentMembers } from "./service.ts";
test("members newest first", () => {
  assert.deepEqual(recentMembers([{ id: 1, at: 19 }, { id: 2, at: 39 }, { id: 3, at: 29 }]), [2, 3, 1]);
});
