import { test } from "node:test";
import assert from "node:assert/strict";
import { couponsSearch } from "./service.ts";
test("coupons search decodes", () => {
  assert.equal(couponsSearch("/coupons?q=caf%C3%A9+8%26co"), "café 8&co");
});
