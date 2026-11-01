import { test } from "node:test";
import assert from "node:assert/strict";
import { recentCoupons } from "./service.ts";
test("coupons newest first", () => {
  assert.deepEqual(recentCoupons([{ id: 1, at: 18 }, { id: 2, at: 38 }, { id: 3, at: 28 }]), [2, 3, 1]);
});
