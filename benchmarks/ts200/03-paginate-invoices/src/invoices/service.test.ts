import { test } from "node:test";
import assert from "node:assert/strict";
import { listInvoices } from "./service.ts";
test("invoices paging is 1-based", () => {
  const ids = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  assert.deepEqual(listInvoices(ids, 1), [1, 2, 3]);
  assert.deepEqual(listInvoices(ids, 4), [10]);
});
