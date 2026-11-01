import { test } from "node:test";
import assert from "node:assert/strict";
import { reportsPreview } from "./service.ts";
test("reports preview fits", () => {
  const p = reportsPreview("x".repeat(25));
  assert.equal(p.length, 15);
  assert.ok(p.endsWith("…"));
  assert.equal(reportsPreview("short"), "short");
});
