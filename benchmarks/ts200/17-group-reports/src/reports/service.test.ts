import { test } from "node:test";
import assert from "node:assert/strict";
import { reportsPerCategory } from "./service.ts";
test("reports per category", () => {
  assert.deepEqual(reportsPerCategory([{ id: "a", category: "x7" }, { id: "b", category: "x7" }, { id: "c", category: "y" }]), { x7: 2, y: 1 });
});
