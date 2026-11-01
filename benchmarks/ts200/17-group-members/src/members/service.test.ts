import { test } from "node:test";
import assert from "node:assert/strict";
import { membersPerCategory } from "./service.ts";
test("members per category", () => {
  assert.deepEqual(membersPerCategory([{ id: "a", category: "x9" }, { id: "b", category: "x9" }, { id: "c", category: "y" }]), { x9: 2, y: 1 });
});
