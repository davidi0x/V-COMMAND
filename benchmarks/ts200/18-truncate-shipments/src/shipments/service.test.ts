import { test } from "node:test";
import assert from "node:assert/strict";
import { shipmentsPreview } from "./service.ts";
test("shipments preview fits", () => {
  const p = shipmentsPreview("x".repeat(22));
  assert.equal(p.length, 12);
  assert.ok(p.endsWith("…"));
  assert.equal(shipmentsPreview("short"), "short");
});
