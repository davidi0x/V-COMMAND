import { test } from "node:test";
import assert from "node:assert/strict";
import { activePaymentCount } from "./service.ts";
test("payments active count", () => {
  assert.equal(activePaymentCount([{ active: true }, { active: true }, { active: true }, { active: true }, { active: true }, { active: false }]), 5);
});
