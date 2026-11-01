import { test } from "node:test";
import assert from "node:assert/strict";
import { recentProducts } from "./service.ts";
test("products newest first", () => {
  assert.deepEqual(recentProducts([{ id: 1, at: 15 }, { id: 2, at: 35 }, { id: 3, at: 25 }]), [2, 3, 1]);
});
