import { test } from "node:test";
import assert from "node:assert/strict";
import { listPayments } from "./service.ts";
test("payments paging is 1-based", () => {
  const ids = [1, 2, 3, 4, 5, 6, 7];
  assert.deepEqual(listPayments(ids, 1), [1, 2]);
  assert.deepEqual(listPayments(ids, 4), [7]);
});
