import { test } from "node:test";
import assert from "node:assert/strict";
import { activeOrderCount } from "./service.ts";
test("orders active count", () => {
  assert.equal(activeOrderCount([{ active: true }, { active: true }, { active: false }]), 2);
});
