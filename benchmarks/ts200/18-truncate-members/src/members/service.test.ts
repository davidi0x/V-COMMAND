import { test } from "node:test";
import assert from "node:assert/strict";
import { membersPreview } from "./service.ts";
test("members preview fits", () => {
  const p = membersPreview("x".repeat(27));
  assert.equal(p.length, 17);
  assert.ok(p.endsWith("…"));
  assert.equal(membersPreview("short"), "short");
});
