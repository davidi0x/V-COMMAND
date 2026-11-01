import { test } from "node:test";
import assert from "node:assert/strict";
import { sessionsProgress } from "./service.ts";
test("sessions progress rounds to nearest", () => {
  assert.equal(sessionsProgress(2, 3), 67);
  assert.equal(sessionsProgress(1, 8), 13);
});
