import { test } from "node:test";
import assert from "node:assert/strict";
import { shipmentsPriority } from "./service.ts";
test("shipments priority bounds", () => {
  assert.equal(shipmentsPriority(7), 7);
  assert.equal(shipmentsPriority(64), 14);
  assert.equal(shipmentsPriority(-1), 4);
});
