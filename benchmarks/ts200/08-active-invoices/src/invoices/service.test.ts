import { test } from "node:test";
import assert from "node:assert/strict";
import { activeInvoiceCount } from "./service.ts";
test("invoices active count", () => {
  assert.equal(activeInvoiceCount([{ active: true }, { active: true }, { active: true }, { active: false }]), 3);
});
