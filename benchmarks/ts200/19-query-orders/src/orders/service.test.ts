import { test } from "node:test";
import assert from "node:assert/strict";
import { ordersSearch } from "./service.ts";
test("orders search decodes", () => {
  assert.equal(ordersSearch("/orders?q=caf%C3%A9+0%26co"), "café 0&co");
});
