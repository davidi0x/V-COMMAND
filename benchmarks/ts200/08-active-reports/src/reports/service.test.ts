import { test } from "node:test";
import assert from "node:assert/strict";
import { activeReportCount } from "./service.ts";
test("reports active count", () => {
  assert.equal(activeReportCount([{ active: true }, { active: true }, { active: true }, { active: true }, { active: true }, { active: false }]), 5);
});
