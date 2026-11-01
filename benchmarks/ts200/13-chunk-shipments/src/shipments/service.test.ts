import { test } from "node:test";
import assert from "node:assert/strict";
import { shipmentsBatches } from "./service.ts";
test("shipments batches keep the remainder", () => {
  assert.deepEqual(shipmentsBatches([1, 2, 3, 4, 5, 6, 7]), [[1, 2, 3], [4, 5, 6], [7]]);
});
