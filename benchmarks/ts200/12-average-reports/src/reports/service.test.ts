import { test } from "node:test";
import assert from "node:assert/strict";
import { averageReportValue } from "./service.ts";
test("reports average", () => {
  assert.equal(averageReportValue([]), 0);
  assert.equal(averageReportValue([7, 9]), 8);
});
