import { test } from "node:test";
import assert from "node:assert/strict";
import { shipmentsGross } from "./service.ts";
test("shipments gross applies discount before tax", () => {
  assert.equal(shipmentsGross(100), 111.6);
});
