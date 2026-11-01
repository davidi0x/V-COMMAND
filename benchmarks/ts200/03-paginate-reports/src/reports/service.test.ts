import { test } from "node:test";
import assert from "node:assert/strict";
import { listReports } from "./service.ts";
test("reports paging is 1-based", () => {
  const ids = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  assert.deepEqual(listReports(ids, 1), [1, 2, 3]);
  assert.deepEqual(listReports(ids, 4), [10]);
});
