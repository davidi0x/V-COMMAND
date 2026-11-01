import { test } from "node:test";
import assert from "node:assert/strict";
import { reportsBatches } from "./service.ts";
test("reports batches keep the remainder", () => {
  assert.deepEqual(reportsBatches([1, 2, 3, 4, 5, 6, 7]), [[1, 2, 3], [4, 5, 6], [7]]);
});
