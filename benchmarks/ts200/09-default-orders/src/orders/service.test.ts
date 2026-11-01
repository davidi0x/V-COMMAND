import { test } from "node:test";
import assert from "node:assert/strict";
import { ordersLimit } from "./service.ts";
test("orders limit keeps explicit zero", () => {
  assert.equal(ordersLimit(0), 0);
  assert.equal(ordersLimit(undefined), 50);
  assert.equal(ordersLimit(7), 7);
});
