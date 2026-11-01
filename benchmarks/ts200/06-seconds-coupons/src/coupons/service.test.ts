import { test } from "node:test";
import assert from "node:assert/strict";
import { couponsAgeSeconds } from "./service.ts";
test("coupons age", () => {
  assert.equal(couponsAgeSeconds(5000, 15000), 10);
});
