import { test } from "node:test";
import assert from "node:assert/strict";
import { membersGross } from "./service.ts";
test("members gross applies discount before tax", () => {
  assert.equal(membersGross(100), 116.1);
});
