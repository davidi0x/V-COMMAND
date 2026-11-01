import { test } from "node:test";
import assert from "node:assert/strict";
import { membersLimit } from "./service.ts";
test("members limit keeps explicit zero", () => {
  assert.equal(membersLimit(0), 0);
  assert.equal(membersLimit(undefined), 59);
  assert.equal(membersLimit(7), 7);
});
