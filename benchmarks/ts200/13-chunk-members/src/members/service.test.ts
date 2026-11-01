import { test } from "node:test";
import assert from "node:assert/strict";
import { membersBatches } from "./service.ts";
test("members batches keep the remainder", () => {
  assert.deepEqual(membersBatches([1, 2, 3, 4, 5]), [[1, 2], [3, 4], [5]]);
});
