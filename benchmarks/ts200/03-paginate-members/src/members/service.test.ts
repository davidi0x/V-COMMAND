import { test } from "node:test";
import assert from "node:assert/strict";
import { listMembers } from "./service.ts";
test("members paging is 1-based", () => {
  const ids = [1, 2, 3, 4, 5, 6, 7];
  assert.deepEqual(listMembers(ids, 1), [1, 2]);
  assert.deepEqual(listMembers(ids, 4), [7]);
});
