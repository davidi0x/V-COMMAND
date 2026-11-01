import { test } from "node:test";
import assert from "node:assert/strict";
import { averageProductValue } from "./service.ts";
test("products average", () => {
  assert.equal(averageProductValue([]), 0);
  assert.equal(averageProductValue([5, 7]), 6);
});
