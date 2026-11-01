import { test } from "node:test";
import assert from "node:assert/strict";
import { recentTickets } from "./service.ts";
test("tickets newest first", () => {
  assert.deepEqual(recentTickets([{ id: 1, at: 12 }, { id: 2, at: 32 }, { id: 3, at: 22 }]), [2, 3, 1]);
});
