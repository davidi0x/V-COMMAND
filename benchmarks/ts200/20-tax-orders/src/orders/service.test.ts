import { test } from "node:test";
import assert from "node:assert/strict";
import { ordersGross } from "./service.ts";
test("orders gross applies discount before tax", () => {
  assert.equal(ordersGross(100), 108.0);
});
