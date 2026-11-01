import { test } from "node:test";
import assert from "node:assert/strict";
import { membersSearch } from "./service.ts";
test("members search decodes", () => {
  assert.equal(membersSearch("/members?q=caf%C3%A9+9%26co"), "café 9&co");
});
