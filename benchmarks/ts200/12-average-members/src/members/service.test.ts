import { test } from "node:test";
import assert from "node:assert/strict";
import { averageMemberValue } from "./service.ts";
test("members average", () => {
  assert.equal(averageMemberValue([]), 0);
  assert.equal(averageMemberValue([9, 11]), 10);
});
