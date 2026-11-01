import { test } from "node:test";
import assert from "node:assert/strict";
import { ticketsAgeSeconds } from "./service.ts";
test("tickets age", () => {
  assert.equal(ticketsAgeSeconds(5000, 9000), 4);
});
