import { test } from "node:test";
import assert from "node:assert/strict";
import { invoicesGross } from "./service.ts";
test("invoices gross applies discount before tax", () => {
  assert.equal(invoicesGross(100), 108.9);
});
