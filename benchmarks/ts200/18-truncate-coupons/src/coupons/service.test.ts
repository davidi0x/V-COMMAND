import { test } from "node:test";
import assert from "node:assert/strict";
import { couponsPreview } from "./service.ts";
test("coupons preview fits", () => {
  const p = couponsPreview("x".repeat(26));
  assert.equal(p.length, 16);
  assert.ok(p.endsWith("…"));
  assert.equal(couponsPreview("short"), "short");
});
