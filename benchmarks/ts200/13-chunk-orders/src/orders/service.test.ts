import { test } from "node:test";
import assert from "node:assert/strict";
import { ordersBatches } from "./service.ts";
test("orders batches keep the remainder", () => {
  assert.deepEqual(ordersBatches([1, 2, 3, 4, 5]), [[1, 2], [3, 4], [5]]);
});
