import { test } from "node:test";
import assert from "node:assert/strict";
import { couponsTotal } from "./service.ts";
test("coupons total", () => {
  assert.equal(couponsTotal([{ price: 11, quantity: 4 }, { price: 1, quantity: 1 }]), 45);
});
