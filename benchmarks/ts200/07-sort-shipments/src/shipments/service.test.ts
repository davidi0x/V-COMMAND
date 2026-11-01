import { test } from "node:test";
import assert from "node:assert/strict";
import { recentShipments } from "./service.ts";
test("shipments newest first", () => {
  assert.deepEqual(recentShipments([{ id: 1, at: 14 }, { id: 2, at: 34 }, { id: 3, at: 24 }]), [2, 3, 1]);
});
