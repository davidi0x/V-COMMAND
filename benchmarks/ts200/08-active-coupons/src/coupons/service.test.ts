import { test } from "node:test";
import assert from "node:assert/strict";
import { activeCouponCount } from "./service.ts";
test("coupons active count", () => {
  assert.equal(activeCouponCount([{ active: true }, { active: true }, { active: false }]), 2);
});
