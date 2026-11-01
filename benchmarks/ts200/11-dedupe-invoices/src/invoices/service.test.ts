import { test } from "node:test";
import assert from "node:assert/strict";
import { firstInvoiceVersions } from "./service.ts";
test("invoices keeps first occurrence", () => {
  assert.deepEqual(firstInvoiceVersions([{ id: 1, v: "a1" }, { id: 2, v: "b" }, { id: 1, v: "c" }]), ["a1", "b"]);
});
