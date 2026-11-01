import { test } from "node:test";
import assert from "node:assert/strict";
import { reportsSearch } from "./service.ts";
test("reports search decodes", () => {
  assert.equal(reportsSearch("/reports?q=caf%C3%A9+7%26co"), "café 7&co");
});
