import { test } from "node:test";
import assert from "node:assert/strict";
import { shipmentsYears } from "./service.ts";
test("shipments years inclusive", () => {
  assert.deepEqual(shipmentsYears(2024, 2026), [2024, 2025, 2026]);
});
