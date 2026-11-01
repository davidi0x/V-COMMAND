import { test } from "node:test";
import assert from "node:assert/strict";
import { invoicesPreview } from "./service.ts";
test("invoices preview fits", () => {
  const p = invoicesPreview("x".repeat(19));
  assert.equal(p.length, 9);
  assert.ok(p.endsWith("…"));
  assert.equal(invoicesPreview("short"), "short");
});
