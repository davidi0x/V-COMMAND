import { test } from "node:test";
import assert from "node:assert/strict";
import { ticketsTotal } from "./service.ts";
test("tickets total", () => {
  assert.equal(ticketsTotal([{ price: 5, quantity: 4 }, { price: 1, quantity: 1 }]), 21);
});
