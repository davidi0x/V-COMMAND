import { test } from "node:test";
import assert from "node:assert/strict";
import { membersYears } from "./service.ts";
test("members years inclusive", () => {
  assert.deepEqual(membersYears(2029, 2031), [2029, 2030, 2031]);
});
