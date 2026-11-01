import { test } from "node:test";
import assert from "node:assert/strict";
import { recentSessions } from "./service.ts";
test("sessions newest first", () => {
  assert.deepEqual(recentSessions([{ id: 1, at: 16 }, { id: 2, at: 36 }, { id: 3, at: 26 }]), [2, 3, 1]);
});
