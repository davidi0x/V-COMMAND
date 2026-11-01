import { test } from "node:test";
import assert from "node:assert/strict";
import { listSessions } from "./service.ts";
test("sessions paging is 1-based", () => {
  const ids = [1, 2, 3, 4, 5, 6, 7];
  assert.deepEqual(listSessions(ids, 1), [1, 2]);
  assert.deepEqual(listSessions(ids, 4), [7]);
});
