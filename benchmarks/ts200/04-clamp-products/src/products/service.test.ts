import { test } from "node:test";
import assert from "node:assert/strict";
import { productsPriority } from "./service.ts";
test("products priority bounds", () => {
  assert.equal(productsPriority(8), 8);
  assert.equal(productsPriority(65), 15);
  assert.equal(productsPriority(0), 5);
});
