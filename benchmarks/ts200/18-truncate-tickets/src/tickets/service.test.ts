import { test } from "node:test";
import assert from "node:assert/strict";
import { ticketsPreview } from "./service.ts";
test("tickets preview fits", () => {
  const p = ticketsPreview("x".repeat(20));
  assert.equal(p.length, 10);
  assert.ok(p.endsWith("…"));
  assert.equal(ticketsPreview("short"), "short");
});
