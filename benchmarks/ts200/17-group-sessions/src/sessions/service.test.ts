import { test } from "node:test";
import assert from "node:assert/strict";
import { sessionsPerCategory } from "./service.ts";
test("sessions per category", () => {
  assert.deepEqual(sessionsPerCategory([{ id: "a", category: "x6" }, { id: "b", category: "x6" }, { id: "c", category: "y" }]), { x6: 2, y: 1 });
});
