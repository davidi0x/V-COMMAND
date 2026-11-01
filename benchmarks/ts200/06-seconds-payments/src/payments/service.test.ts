import { test } from "node:test";
import assert from "node:assert/strict";
import { paymentsAgeSeconds } from "./service.ts";
test("payments age", () => {
  assert.equal(paymentsAgeSeconds(5000, 10000), 5);
});
