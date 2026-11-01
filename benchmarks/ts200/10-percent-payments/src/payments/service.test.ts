import { test } from "node:test";
import assert from "node:assert/strict";
import { paymentsProgress } from "./service.ts";
test("payments progress rounds to nearest", () => {
  assert.equal(paymentsProgress(2, 3), 67);
  assert.equal(paymentsProgress(1, 8), 13);
});
