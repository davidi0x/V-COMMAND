import { test } from "node:test";
import assert from "node:assert/strict";
import { sessionsConversionRate } from "./service.ts";
test("sessions conversion", () => {
  assert.equal(sessionsConversionRate(6, 0), 0);
  assert.equal(sessionsConversionRate(1, 4), 0.25);
});
