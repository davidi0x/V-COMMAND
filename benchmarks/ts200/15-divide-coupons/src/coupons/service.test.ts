import { test } from "node:test";
import assert from "node:assert/strict";
import { couponsConversionRate } from "./service.ts";
test("coupons conversion", () => {
  assert.equal(couponsConversionRate(8, 0), 0);
  assert.equal(couponsConversionRate(1, 4), 0.25);
});
