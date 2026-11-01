import { test } from "node:test";
import assert from "node:assert/strict";
import { productsHeading } from "./service.ts";
test("products heading", () => {
  assert.equal(productsHeading("annual products report"), "Annual Products Report");
});
