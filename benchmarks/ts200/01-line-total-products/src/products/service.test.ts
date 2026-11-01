import { test } from "node:test";
import assert from "node:assert/strict";
import { productsTotal } from "./service.ts";
test("products total", () => {
  assert.equal(productsTotal([{ price: 8, quantity: 4 }, { price: 1, quantity: 1 }]), 33);
});
