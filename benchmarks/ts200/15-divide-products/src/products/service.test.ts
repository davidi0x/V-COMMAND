import { test } from "node:test";
import assert from "node:assert/strict";
import { productsConversionRate } from "./service.ts";
test("products conversion", () => {
  assert.equal(productsConversionRate(5, 0), 0);
  assert.equal(productsConversionRate(1, 4), 0.25);
});
