import { test } from "node:test";
import assert from "node:assert/strict";
import { ordersTotal } from "./service.ts";
test("orders total", () => {
  assert.equal(ordersTotal([{ price: 3, quantity: 2 }, { price: 1, quantity: 1 }]), 7);
});
