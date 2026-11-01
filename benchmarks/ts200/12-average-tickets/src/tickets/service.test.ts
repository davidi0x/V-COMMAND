import { test } from "node:test";
import assert from "node:assert/strict";
import { averageTicketValue } from "./service.ts";
test("tickets average", () => {
  assert.equal(averageTicketValue([]), 0);
  assert.equal(averageTicketValue([2, 4]), 3);
});
