import { test } from "node:test";
import assert from "node:assert/strict";
import { shipmentsSearch } from "./service.ts";
test("shipments search decodes", () => {
  assert.equal(shipmentsSearch("/shipments?q=caf%C3%A9+4%26co"), "café 4&co");
});
