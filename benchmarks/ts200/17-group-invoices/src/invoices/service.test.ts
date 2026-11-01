import { test } from "node:test";
import assert from "node:assert/strict";
import { invoicesPerCategory } from "./service.ts";
test("invoices per category", () => {
  assert.deepEqual(invoicesPerCategory([{ id: "a", category: "x1" }, { id: "b", category: "x1" }, { id: "c", category: "y" }]), { x1: 2, y: 1 });
});
