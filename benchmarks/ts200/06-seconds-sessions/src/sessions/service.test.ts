import { test } from "node:test";
import assert from "node:assert/strict";
import { sessionsAgeSeconds } from "./service.ts";
test("sessions age", () => {
  assert.equal(sessionsAgeSeconds(5000, 13000), 8);
});
