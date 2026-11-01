import { test } from "node:test";
import assert from "node:assert/strict";
import { paymentsYears } from "./service.ts";
test("payments years inclusive", () => {
  assert.deepEqual(paymentsYears(2023, 2025), [2023, 2024, 2025]);
});
