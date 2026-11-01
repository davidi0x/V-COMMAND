import { test } from "node:test";
import assert from "node:assert/strict";
import { paymentsPerCategory } from "./service.ts";
test("payments per category", () => {
  assert.deepEqual(paymentsPerCategory([{ id: "a", category: "x3" }, { id: "b", category: "x3" }, { id: "c", category: "y" }]), { x3: 2, y: 1 });
});
