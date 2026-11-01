import { test } from "node:test";
import assert from "node:assert/strict";
import { ticketsSearch } from "./service.ts";
test("tickets search decodes", () => {
  assert.equal(ticketsSearch("/tickets?q=caf%C3%A9+2%26co"), "café 2&co");
});
