import { test } from "node:test";
import assert from "node:assert/strict";
import { paymentsBatches } from "./service.ts";
test("payments batches keep the remainder", () => {
  assert.deepEqual(paymentsBatches([1, 2, 3, 4, 5]), [[1, 2], [3, 4], [5]]);
});
