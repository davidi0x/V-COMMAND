import { test } from "node:test";
import assert from "node:assert/strict";
import { paymentsGross } from "./service.ts";
test("payments gross applies discount before tax", () => {
  assert.equal(paymentsGross(100), 110.7);
});
