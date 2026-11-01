import { test } from "node:test";
import assert from "node:assert/strict";
import { activeProductCount } from "./service.ts";
test("products active count", () => {
  assert.equal(activeProductCount([{ active: true }, { active: true }, { active: true }, { active: false }]), 3);
});
