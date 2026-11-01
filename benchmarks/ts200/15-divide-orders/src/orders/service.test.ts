import { test } from "node:test";
import assert from "node:assert/strict";
import { ordersConversionRate } from "./service.ts";
test("orders conversion", () => {
  assert.equal(ordersConversionRate(0, 0), 0);
  assert.equal(ordersConversionRate(1, 4), 0.25);
});
