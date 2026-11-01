import { test } from "node:test";
import assert from "node:assert/strict";
import { couponsLimit } from "./service.ts";
test("coupons limit keeps explicit zero", () => {
  assert.equal(couponsLimit(0), 0);
  assert.equal(couponsLimit(undefined), 58);
  assert.equal(couponsLimit(7), 7);
});
