import { test } from "node:test";
import assert from "node:assert/strict";
import { shipmentsPerCategory } from "./service.ts";
test("shipments per category", () => {
  assert.deepEqual(shipmentsPerCategory([{ id: "a", category: "x4" }, { id: "b", category: "x4" }, { id: "c", category: "y" }]), { x4: 2, y: 1 });
});
