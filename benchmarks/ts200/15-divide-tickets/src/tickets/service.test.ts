import { test } from "node:test";
import assert from "node:assert/strict";
import { ticketsConversionRate } from "./service.ts";
test("tickets conversion", () => {
  assert.equal(ticketsConversionRate(2, 0), 0);
  assert.equal(ticketsConversionRate(1, 4), 0.25);
});
