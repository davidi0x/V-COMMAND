import { test } from "node:test";
import assert from "node:assert/strict";
import { reportsYears } from "./service.ts";
test("reports years inclusive", () => {
  assert.deepEqual(reportsYears(2027, 2029), [2027, 2028, 2029]);
});
