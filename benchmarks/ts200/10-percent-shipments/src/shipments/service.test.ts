import { test } from "node:test";
import assert from "node:assert/strict";
import { shipmentsProgress } from "./service.ts";
test("shipments progress rounds to nearest", () => {
  assert.equal(shipmentsProgress(2, 3), 67);
  assert.equal(shipmentsProgress(1, 8), 13);
});
