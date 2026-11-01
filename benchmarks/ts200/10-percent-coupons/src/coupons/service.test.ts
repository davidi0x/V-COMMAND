import { test } from "node:test";
import assert from "node:assert/strict";
import { couponsProgress } from "./service.ts";
test("coupons progress rounds to nearest", () => {
  assert.equal(couponsProgress(2, 3), 67);
  assert.equal(couponsProgress(1, 8), 13);
});
