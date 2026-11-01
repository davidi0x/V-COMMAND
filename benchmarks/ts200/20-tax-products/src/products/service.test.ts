import { test } from "node:test";
import assert from "node:assert/strict";
import { productsGross } from "./service.ts";
test("products gross applies discount before tax", () => {
  assert.equal(productsGross(100), 112.5);
});
