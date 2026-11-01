import { test } from "node:test";
import assert from "node:assert/strict";
import { ticketsProgress } from "./service.ts";
test("tickets progress rounds to nearest", () => {
  assert.equal(ticketsProgress(2, 3), 67);
  assert.equal(ticketsProgress(1, 8), 13);
});
