import { test } from "node:test";
import assert from "node:assert/strict";
import { recentPayments } from "./service.ts";
test("payments newest first", () => {
  assert.deepEqual(recentPayments([{ id: 1, at: 13 }, { id: 2, at: 33 }, { id: 3, at: 23 }]), [2, 3, 1]);
});
