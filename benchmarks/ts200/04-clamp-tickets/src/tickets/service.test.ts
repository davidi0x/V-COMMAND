import { test } from "node:test";
import assert from "node:assert/strict";
import { ticketsPriority } from "./service.ts";
test("tickets priority bounds", () => {
  assert.equal(ticketsPriority(5), 5);
  assert.equal(ticketsPriority(62), 12);
  assert.equal(ticketsPriority(-3), 2);
});
