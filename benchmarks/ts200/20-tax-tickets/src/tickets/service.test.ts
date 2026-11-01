import { test } from "node:test";
import assert from "node:assert/strict";
import { ticketsGross } from "./service.ts";
test("tickets gross applies discount before tax", () => {
  assert.equal(ticketsGross(100), 109.8);
});
