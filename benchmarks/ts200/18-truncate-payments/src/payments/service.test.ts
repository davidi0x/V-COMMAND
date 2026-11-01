import { test } from "node:test";
import assert from "node:assert/strict";
import { paymentsPreview } from "./service.ts";
test("payments preview fits", () => {
  const p = paymentsPreview("x".repeat(21));
  assert.equal(p.length, 11);
  assert.ok(p.endsWith("…"));
  assert.equal(paymentsPreview("short"), "short");
});
