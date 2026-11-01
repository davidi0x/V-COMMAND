import { test } from "node:test";
import assert from "node:assert/strict";
import { sessionsBatches } from "./service.ts";
test("sessions batches keep the remainder", () => {
  assert.deepEqual(sessionsBatches([1, 2, 3, 4, 5]), [[1, 2], [3, 4], [5]]);
});
