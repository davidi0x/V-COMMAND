import { test } from "node:test";
import assert from "node:assert/strict";
import { averageShipmentValue } from "./service.ts";
test("shipments average", () => {
  assert.equal(averageShipmentValue([]), 0);
  assert.equal(averageShipmentValue([4, 6]), 5);
});
