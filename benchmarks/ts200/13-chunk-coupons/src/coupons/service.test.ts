import { test } from "node:test";
import assert from "node:assert/strict";
import { couponsBatches } from "./service.ts";
test("coupons batches keep the remainder", () => {
  assert.deepEqual(couponsBatches([1, 2, 3, 4, 5, 6, 7, 8, 9]), [[1, 2, 3, 4], [5, 6, 7, 8], [9]]);
});
