import { test } from "node:test";
import assert from "node:assert/strict";
import { ticketsYears } from "./service.ts";
test("tickets years inclusive", () => {
  assert.deepEqual(ticketsYears(2022, 2024), [2022, 2023, 2024]);
});
