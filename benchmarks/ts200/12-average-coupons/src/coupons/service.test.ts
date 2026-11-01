import { test } from "node:test";
import assert from "node:assert/strict";
import { averageCouponValue } from "./service.ts";
test("coupons average", () => {
  assert.equal(averageCouponValue([]), 0);
  assert.equal(averageCouponValue([8, 10]), 9);
});
