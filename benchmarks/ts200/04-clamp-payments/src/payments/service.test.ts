import { test } from "node:test";
import assert from "node:assert/strict";
import { paymentsPriority } from "./service.ts";
test("payments priority bounds", () => {
  assert.equal(paymentsPriority(6), 6);
  assert.equal(paymentsPriority(63), 13);
  assert.equal(paymentsPriority(-2), 3);
});
