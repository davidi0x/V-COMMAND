import { test } from "node:test";
import assert from "node:assert/strict";
import { invoicesTotal } from "./service.ts";
test("invoices total", () => {
  assert.equal(invoicesTotal([{ price: 4, quantity: 3 }, { price: 1, quantity: 1 }]), 13);
});
