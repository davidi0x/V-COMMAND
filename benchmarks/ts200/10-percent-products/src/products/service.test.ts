import { test } from "node:test";
import assert from "node:assert/strict";
import { productsProgress } from "./service.ts";
test("products progress rounds to nearest", () => {
  assert.equal(productsProgress(2, 3), 67);
  assert.equal(productsProgress(1, 8), 13);
});
