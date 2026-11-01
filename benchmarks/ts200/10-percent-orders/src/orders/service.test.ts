import { test } from "node:test";
import assert from "node:assert/strict";
import { ordersProgress } from "./service.ts";
test("orders progress rounds to nearest", () => {
  assert.equal(ordersProgress(2, 3), 67);
  assert.equal(ordersProgress(1, 8), 13);
});
