import { test } from "node:test";
import assert from "node:assert/strict";
import { total, count } from "./cart.ts";

test("total multiplies by quantity", () => {
  assert.equal(total([{ sku: "a", price: 2, quantity: 3 }, { sku: "b", price: 5, quantity: 1 }]), 11);
});

test("count", () => {
  assert.equal(count([{ sku: "a", price: 2, quantity: 3 }]), 3);
});
