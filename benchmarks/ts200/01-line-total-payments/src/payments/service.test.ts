import { test } from "node:test";
import assert from "node:assert/strict";
import { paymentsTotal } from "./service.ts";
test("payments total", () => {
  assert.equal(paymentsTotal([{ price: 6, quantity: 2 }, { price: 1, quantity: 1 }]), 13);
});
