import { test } from "node:test";
import assert from "node:assert/strict";
import { listOrders } from "./service.ts";
test("orders paging is 1-based", () => {
  const ids = [1, 2, 3, 4, 5, 6, 7];
  assert.deepEqual(listOrders(ids, 1), [1, 2]);
  assert.deepEqual(listOrders(ids, 4), [7]);
});
