import { test } from "node:test";
import assert from "node:assert/strict";
import { recentInvoices } from "./service.ts";
test("invoices newest first", () => {
  assert.deepEqual(recentInvoices([{ id: 1, at: 11 }, { id: 2, at: 31 }, { id: 3, at: 21 }]), [2, 3, 1]);
});
