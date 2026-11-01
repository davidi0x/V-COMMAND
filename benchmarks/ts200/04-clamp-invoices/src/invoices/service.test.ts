import { test } from "node:test";
import assert from "node:assert/strict";
import { invoicesPriority } from "./service.ts";
test("invoices priority bounds", () => {
  assert.equal(invoicesPriority(4), 4);
  assert.equal(invoicesPriority(61), 11);
  assert.equal(invoicesPriority(-4), 1);
});
