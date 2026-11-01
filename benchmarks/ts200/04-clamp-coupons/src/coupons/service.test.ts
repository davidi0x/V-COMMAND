import { test } from "node:test";
import assert from "node:assert/strict";
import { couponsPriority } from "./service.ts";
test("coupons priority bounds", () => {
  assert.equal(couponsPriority(11), 11);
  assert.equal(couponsPriority(68), 18);
  assert.equal(couponsPriority(3), 8);
});
