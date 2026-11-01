import { test } from "node:test";
import assert from "node:assert/strict";
import { membersPriority } from "./service.ts";
test("members priority bounds", () => {
  assert.equal(membersPriority(12), 12);
  assert.equal(membersPriority(69), 19);
  assert.equal(membersPriority(4), 9);
});
