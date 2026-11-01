import { test } from "node:test";
import assert from "node:assert/strict";
import { ordersPerCategory } from "./service.ts";
test("orders per category", () => {
  assert.deepEqual(ordersPerCategory([{ id: "a", category: "x0" }, { id: "b", category: "x0" }, { id: "c", category: "y" }]), { x0: 2, y: 1 });
});
