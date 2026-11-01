import { test } from "node:test";
import assert from "node:assert/strict";
import { invoicesSearch } from "./service.ts";
test("invoices search decodes", () => {
  assert.equal(invoicesSearch("/invoices?q=caf%C3%A9+1%26co"), "café 1&co");
});
