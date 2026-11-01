import { test } from "node:test";
import assert from "node:assert/strict";
import { activeSessionCount } from "./service.ts";
test("sessions active count", () => {
  assert.equal(activeSessionCount([{ active: true }, { active: true }, { active: true }, { active: true }, { active: false }]), 4);
});
