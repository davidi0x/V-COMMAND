import { test } from "node:test";
import assert from "node:assert/strict";
import { paymentsSearch } from "./service.ts";
test("payments search decodes", () => {
  assert.equal(paymentsSearch("/payments?q=caf%C3%A9+3%26co"), "café 3&co");
});
