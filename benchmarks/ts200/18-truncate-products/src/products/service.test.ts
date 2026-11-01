import { test } from "node:test";
import assert from "node:assert/strict";
import { productsPreview } from "./service.ts";
test("products preview fits", () => {
  const p = productsPreview("x".repeat(23));
  assert.equal(p.length, 13);
  assert.ok(p.endsWith("…"));
  assert.equal(productsPreview("short"), "short");
});
