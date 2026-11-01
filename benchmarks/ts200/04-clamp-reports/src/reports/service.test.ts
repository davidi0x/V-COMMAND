import { test } from "node:test";
import assert from "node:assert/strict";
import { reportsPriority } from "./service.ts";
test("reports priority bounds", () => {
  assert.equal(reportsPriority(10), 10);
  assert.equal(reportsPriority(67), 17);
  assert.equal(reportsPriority(2), 7);
});
