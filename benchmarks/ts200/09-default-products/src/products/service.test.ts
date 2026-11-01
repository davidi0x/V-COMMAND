import { test } from "node:test";
import assert from "node:assert/strict";
import { productsLimit } from "./service.ts";
test("products limit keeps explicit zero", () => {
  assert.equal(productsLimit(0), 0);
  assert.equal(productsLimit(undefined), 55);
  assert.equal(productsLimit(7), 7);
});
