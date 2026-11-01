import { test } from "node:test";
import assert from "node:assert/strict";
import { activeTicketCount } from "./service.ts";
test("tickets active count", () => {
  assert.equal(activeTicketCount([{ active: true }, { active: true }, { active: true }, { active: true }, { active: false }]), 4);
});
