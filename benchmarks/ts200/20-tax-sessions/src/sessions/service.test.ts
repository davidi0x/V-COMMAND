import { test } from "node:test";
import assert from "node:assert/strict";
import { sessionsGross } from "./service.ts";
test("sessions gross applies discount before tax", () => {
  assert.equal(sessionsGross(100), 113.4);
});
