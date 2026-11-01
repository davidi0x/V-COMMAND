import { test } from "node:test";
import assert from "node:assert/strict";
import { productsAgeSeconds } from "./service.ts";
test("products age", () => {
  assert.equal(productsAgeSeconds(5000, 12000), 7);
});
