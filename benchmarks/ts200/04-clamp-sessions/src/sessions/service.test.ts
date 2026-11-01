import { test } from "node:test";
import assert from "node:assert/strict";
import { sessionsPriority } from "./service.ts";
test("sessions priority bounds", () => {
  assert.equal(sessionsPriority(9), 9);
  assert.equal(sessionsPriority(66), 16);
  assert.equal(sessionsPriority(1), 6);
});
