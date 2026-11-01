import { test } from "node:test";
import assert from "node:assert/strict";
import { reportsProgress } from "./service.ts";
test("reports progress rounds to nearest", () => {
  assert.equal(reportsProgress(2, 3), 67);
  assert.equal(reportsProgress(1, 8), 13);
});
