import { test } from "node:test";
import assert from "node:assert/strict";
import { productsSearch } from "./service.ts";
test("products search decodes", () => {
  assert.equal(productsSearch("/products?q=caf%C3%A9+5%26co"), "café 5&co");
});
