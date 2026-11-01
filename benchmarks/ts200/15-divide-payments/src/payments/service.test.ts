import { test } from "node:test";
import assert from "node:assert/strict";
import { paymentsConversionRate } from "./service.ts";
test("payments conversion", () => {
  assert.equal(paymentsConversionRate(3, 0), 0);
  assert.equal(paymentsConversionRate(1, 4), 0.25);
});
