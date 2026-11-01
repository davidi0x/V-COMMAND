import { test } from "node:test";
import assert from "node:assert/strict";
import { membersConversionRate } from "./service.ts";
test("members conversion", () => {
  assert.equal(membersConversionRate(9, 0), 0);
  assert.equal(membersConversionRate(1, 4), 0.25);
});
