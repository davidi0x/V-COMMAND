import { test } from "node:test";
import assert from "node:assert/strict";
import { firstCouponVersions } from "./service.ts";
test("coupons keeps first occurrence", () => {
  assert.deepEqual(firstCouponVersions([{ id: 1, v: "a8" }, { id: 2, v: "b" }, { id: 1, v: "c" }]), ["a8", "b"]);
});
