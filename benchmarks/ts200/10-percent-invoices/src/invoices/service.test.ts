import { test } from "node:test";
import assert from "node:assert/strict";
import { invoicesProgress } from "./service.ts";
test("invoices progress rounds to nearest", () => {
  assert.equal(invoicesProgress(2, 3), 67);
  assert.equal(invoicesProgress(1, 8), 13);
});
