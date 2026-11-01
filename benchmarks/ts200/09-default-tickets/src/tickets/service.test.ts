import { test } from "node:test";
import assert from "node:assert/strict";
import { ticketsLimit } from "./service.ts";
test("tickets limit keeps explicit zero", () => {
  assert.equal(ticketsLimit(0), 0);
  assert.equal(ticketsLimit(undefined), 52);
  assert.equal(ticketsLimit(7), 7);
});
