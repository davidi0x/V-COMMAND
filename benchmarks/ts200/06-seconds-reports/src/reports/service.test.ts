import { test } from "node:test";
import assert from "node:assert/strict";
import { reportsAgeSeconds } from "./service.ts";
test("reports age", () => {
  assert.equal(reportsAgeSeconds(5000, 14000), 9);
});
