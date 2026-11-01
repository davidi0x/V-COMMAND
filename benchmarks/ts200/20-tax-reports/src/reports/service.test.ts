import { test } from "node:test";
import assert from "node:assert/strict";
import { reportsGross } from "./service.ts";
test("reports gross applies discount before tax", () => {
  assert.equal(reportsGross(100), 114.3);
});
