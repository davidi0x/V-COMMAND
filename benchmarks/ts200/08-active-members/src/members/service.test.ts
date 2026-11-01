import { test } from "node:test";
import assert from "node:assert/strict";
import { activeMemberCount } from "./service.ts";
test("members active count", () => {
  assert.equal(activeMemberCount([{ active: true }, { active: true }, { active: true }, { active: false }]), 3);
});
