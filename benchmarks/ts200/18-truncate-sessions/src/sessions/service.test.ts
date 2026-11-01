import { test } from "node:test";
import assert from "node:assert/strict";
import { sessionsPreview } from "./service.ts";
test("sessions preview fits", () => {
  const p = sessionsPreview("x".repeat(24));
  assert.equal(p.length, 14);
  assert.ok(p.endsWith("…"));
  assert.equal(sessionsPreview("short"), "short");
});
