import { test } from "node:test";
import assert from "node:assert/strict";
import { membersAgeSeconds } from "./service.ts";
test("members age", () => {
  assert.equal(membersAgeSeconds(5000, 16000), 11);
});
