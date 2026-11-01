import { test } from "node:test";
import assert from "node:assert/strict";
import { productsPerCategory } from "./service.ts";
test("products per category", () => {
  assert.deepEqual(productsPerCategory([{ id: "a", category: "x5" }, { id: "b", category: "x5" }, { id: "c", category: "y" }]), { x5: 2, y: 1 });
});
