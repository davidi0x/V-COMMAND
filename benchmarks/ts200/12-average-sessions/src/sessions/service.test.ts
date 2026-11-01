import { test } from "node:test";
import assert from "node:assert/strict";
import { averageSessionValue } from "./service.ts";
test("sessions average", () => {
  assert.equal(averageSessionValue([]), 0);
  assert.equal(averageSessionValue([6, 8]), 7);
});
