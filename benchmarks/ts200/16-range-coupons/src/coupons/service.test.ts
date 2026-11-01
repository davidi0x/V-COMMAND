import { test } from "node:test";
import assert from "node:assert/strict";
import { couponsYears } from "./service.ts";
test("coupons years inclusive", () => {
  assert.deepEqual(couponsYears(2028, 2030), [2028, 2029, 2030]);
});
