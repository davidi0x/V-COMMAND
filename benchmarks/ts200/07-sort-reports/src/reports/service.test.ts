import { test } from "node:test";
import assert from "node:assert/strict";
import { recentReports } from "./service.ts";
test("reports newest first", () => {
  assert.deepEqual(recentReports([{ id: 1, at: 17 }, { id: 2, at: 37 }, { id: 3, at: 27 }]), [2, 3, 1]);
});
