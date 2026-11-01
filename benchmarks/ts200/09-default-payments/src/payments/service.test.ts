import { test } from "node:test";
import assert from "node:assert/strict";
import { paymentsLimit } from "./service.ts";
test("payments limit keeps explicit zero", () => {
  assert.equal(paymentsLimit(0), 0);
  assert.equal(paymentsLimit(undefined), 53);
  assert.equal(paymentsLimit(7), 7);
});
