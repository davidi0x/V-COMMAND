import { test } from "node:test";
import assert from "node:assert/strict";
import { shipmentsConversionRate } from "./service.ts";
test("shipments conversion", () => {
  assert.equal(shipmentsConversionRate(4, 0), 0);
  assert.equal(shipmentsConversionRate(1, 4), 0.25);
});
