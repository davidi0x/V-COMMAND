import { test } from "node:test";
import assert from "node:assert/strict";
import { couponsHeading } from "./service.ts";
test("coupons heading", () => {
  assert.equal(couponsHeading("annual coupons report"), "Annual Coupons Report");
});
