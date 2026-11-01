import { test } from "node:test";
import assert from "node:assert/strict";
import { ticketsPerCategory } from "./service.ts";
test("tickets per category", () => {
  assert.deepEqual(ticketsPerCategory([{ id: "a", category: "x2" }, { id: "b", category: "x2" }, { id: "c", category: "y" }]), { x2: 2, y: 1 });
});
