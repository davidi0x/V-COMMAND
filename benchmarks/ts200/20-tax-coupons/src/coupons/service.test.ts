import { test } from "node:test";
import assert from "node:assert/strict";
import { couponsGross } from "./service.ts";
test("coupons gross applies discount before tax", () => {
  assert.equal(couponsGross(100), 115.2);
});
