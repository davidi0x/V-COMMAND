import { test } from "node:test";
import assert from "node:assert/strict";
import { shipmentsLimit } from "./service.ts";
test("shipments limit keeps explicit zero", () => {
  assert.equal(shipmentsLimit(0), 0);
  assert.equal(shipmentsLimit(undefined), 54);
  assert.equal(shipmentsLimit(7), 7);
});
