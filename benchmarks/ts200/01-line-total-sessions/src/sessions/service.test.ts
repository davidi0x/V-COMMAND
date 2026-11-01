import { test } from "node:test";
import assert from "node:assert/strict";
import { sessionsTotal } from "./service.ts";
test("sessions total", () => {
  assert.equal(sessionsTotal([{ price: 9, quantity: 2 }, { price: 1, quantity: 1 }]), 19);
});
