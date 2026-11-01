import { test } from "node:test";
import assert from "node:assert/strict";
import { averageOrderValue } from "./service.ts";
test("orders average", () => {
  assert.equal(averageOrderValue([]), 0);
  assert.equal(averageOrderValue([0, 2]), 1);
});
