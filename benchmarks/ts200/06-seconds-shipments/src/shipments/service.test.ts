import { test } from "node:test";
import assert from "node:assert/strict";
import { shipmentsAgeSeconds } from "./service.ts";
test("shipments age", () => {
  assert.equal(shipmentsAgeSeconds(5000, 11000), 6);
});
