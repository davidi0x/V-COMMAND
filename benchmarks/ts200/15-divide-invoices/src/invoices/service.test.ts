import { test } from "node:test";
import assert from "node:assert/strict";
import { invoicesConversionRate } from "./service.ts";
test("invoices conversion", () => {
  assert.equal(invoicesConversionRate(1, 0), 0);
  assert.equal(invoicesConversionRate(1, 4), 0.25);
});
