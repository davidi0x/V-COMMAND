import { test } from "node:test";
import assert from "node:assert/strict";
import { reportsConversionRate } from "./service.ts";
test("reports conversion", () => {
  assert.equal(reportsConversionRate(7, 0), 0);
  assert.equal(reportsConversionRate(1, 4), 0.25);
});
