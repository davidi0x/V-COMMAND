import { test } from "node:test";
import assert from "node:assert/strict";
import { averagePaymentValue } from "./service.ts";
test("payments average", () => {
  assert.equal(averagePaymentValue([]), 0);
  assert.equal(averagePaymentValue([3, 5]), 4);
});
