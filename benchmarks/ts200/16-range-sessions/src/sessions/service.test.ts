import { test } from "node:test";
import assert from "node:assert/strict";
import { sessionsYears } from "./service.ts";
test("sessions years inclusive", () => {
  assert.deepEqual(sessionsYears(2026, 2028), [2026, 2027, 2028]);
});
