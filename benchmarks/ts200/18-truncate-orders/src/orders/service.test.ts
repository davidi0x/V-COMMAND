import { test } from "node:test";
import assert from "node:assert/strict";
import { ordersPreview } from "./service.ts";
test("orders preview fits", () => {
  const p = ordersPreview("x".repeat(18));
  assert.equal(p.length, 8);
  assert.ok(p.endsWith("…"));
  assert.equal(ordersPreview("short"), "short");
});
