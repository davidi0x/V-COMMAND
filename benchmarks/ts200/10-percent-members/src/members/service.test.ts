import { test } from "node:test";
import assert from "node:assert/strict";
import { membersProgress } from "./service.ts";
test("members progress rounds to nearest", () => {
  assert.equal(membersProgress(2, 3), 67);
  assert.equal(membersProgress(1, 8), 13);
});
