import { test } from "node:test";
import assert from "node:assert/strict";
import { productsUrl } from "./service.ts";
test("products url is lowercase", () => {
  assert.equal(productsUrl("Hello World 5", 5), "/products/5-hello-world-5");
});
