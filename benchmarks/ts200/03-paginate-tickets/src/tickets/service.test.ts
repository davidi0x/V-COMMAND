import { test } from "node:test";
import assert from "node:assert/strict";
import { listTickets } from "./service.ts";
test("tickets paging is 1-based", () => {
  const ids = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13];
  assert.deepEqual(listTickets(ids, 1), [1, 2, 3, 4]);
  assert.deepEqual(listTickets(ids, 4), [13]);
});
