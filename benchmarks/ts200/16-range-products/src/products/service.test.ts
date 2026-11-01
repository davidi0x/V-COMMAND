import { test } from "node:test";
import assert from "node:assert/strict";
import { productsYears } from "./service.ts";
test("products years inclusive", () => {
  assert.deepEqual(productsYears(2025, 2027), [2025, 2026, 2027]);
});
