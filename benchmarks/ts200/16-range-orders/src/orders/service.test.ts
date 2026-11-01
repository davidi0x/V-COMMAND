import { test } from "node:test";
import assert from "node:assert/strict";
import { ordersYears } from "./service.ts";
test("orders years inclusive", () => {
  assert.deepEqual(ordersYears(2020, 2022), [2020, 2021, 2022]);
});
