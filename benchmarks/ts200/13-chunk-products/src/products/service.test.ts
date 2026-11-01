import { test } from "node:test";
import assert from "node:assert/strict";
import { productsBatches } from "./service.ts";
test("products batches keep the remainder", () => {
  assert.deepEqual(productsBatches([1, 2, 3, 4, 5, 6, 7, 8, 9]), [[1, 2, 3, 4], [5, 6, 7, 8], [9]]);
});
