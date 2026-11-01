import { test } from "node:test";
import assert from "node:assert/strict";
import { invoicesBatches } from "./service.ts";
test("invoices batches keep the remainder", () => {
  assert.deepEqual(invoicesBatches([1, 2, 3, 4, 5, 6, 7]), [[1, 2, 3], [4, 5, 6], [7]]);
});
