import { test } from "node:test";
import assert from "node:assert/strict";
import { invoicesAgeSeconds } from "./service.ts";
test("invoices age", () => {
  assert.equal(invoicesAgeSeconds(5000, 8000), 3);
});
