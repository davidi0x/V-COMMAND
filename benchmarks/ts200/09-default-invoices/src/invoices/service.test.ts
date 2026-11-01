import { test } from "node:test";
import assert from "node:assert/strict";
import { invoicesLimit } from "./service.ts";
test("invoices limit keeps explicit zero", () => {
  assert.equal(invoicesLimit(0), 0);
  assert.equal(invoicesLimit(undefined), 51);
  assert.equal(invoicesLimit(7), 7);
});
