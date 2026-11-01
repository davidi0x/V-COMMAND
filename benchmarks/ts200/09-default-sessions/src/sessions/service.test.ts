import { test } from "node:test";
import assert from "node:assert/strict";
import { sessionsLimit } from "./service.ts";
test("sessions limit keeps explicit zero", () => {
  assert.equal(sessionsLimit(0), 0);
  assert.equal(sessionsLimit(undefined), 56);
  assert.equal(sessionsLimit(7), 7);
});
