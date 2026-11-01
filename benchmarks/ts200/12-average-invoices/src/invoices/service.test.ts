import { test } from "node:test";
import assert from "node:assert/strict";
import { averageInvoiceValue } from "./service.ts";
test("invoices average", () => {
  assert.equal(averageInvoiceValue([]), 0);
  assert.equal(averageInvoiceValue([1, 3]), 2);
});
