import { test } from "node:test";
import assert from "node:assert/strict";
import { ticketsBatches } from "./service.ts";
test("tickets batches keep the remainder", () => {
  assert.deepEqual(ticketsBatches([1, 2, 3, 4, 5, 6, 7, 8, 9]), [[1, 2, 3, 4], [5, 6, 7, 8], [9]]);
});
