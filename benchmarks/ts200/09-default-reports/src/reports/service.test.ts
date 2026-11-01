import { test } from "node:test";
import assert from "node:assert/strict";
import { reportsLimit } from "./service.ts";
test("reports limit keeps explicit zero", () => {
  assert.equal(reportsLimit(0), 0);
  assert.equal(reportsLimit(undefined), 57);
  assert.equal(reportsLimit(7), 7);
});
