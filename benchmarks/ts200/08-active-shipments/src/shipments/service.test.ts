import { test } from "node:test";
import assert from "node:assert/strict";
import { activeShipmentCount } from "./service.ts";
test("shipments active count", () => {
  assert.equal(activeShipmentCount([{ active: true }, { active: true }, { active: false }]), 2);
});
