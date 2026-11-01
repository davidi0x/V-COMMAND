import { test } from "node:test";
import assert from "node:assert/strict";
import { couponsPerCategory } from "./service.ts";
test("coupons per category", () => {
  assert.deepEqual(couponsPerCategory([{ id: "a", category: "x8" }, { id: "b", category: "x8" }, { id: "c", category: "y" }]), { x8: 2, y: 1 });
});
