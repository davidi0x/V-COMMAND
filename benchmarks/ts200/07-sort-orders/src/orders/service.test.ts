import { test } from "node:test";
import assert from "node:assert/strict";
import { recentOrders } from "./service.ts";
test("orders newest first", () => {
  assert.deepEqual(recentOrders([{ id: 1, at: 10 }, { id: 2, at: 30 }, { id: 3, at: 20 }]), [2, 3, 1]);
});
