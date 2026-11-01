import { test } from "node:test";
import assert from "node:assert/strict";
import { invoicesYears } from "./service.ts";
test("invoices years inclusive", () => {
  assert.deepEqual(invoicesYears(2021, 2023), [2021, 2022, 2023]);
});
