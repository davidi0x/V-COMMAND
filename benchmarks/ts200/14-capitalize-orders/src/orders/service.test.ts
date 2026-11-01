import { test } from "node:test";
import assert from "node:assert/strict";
import { ordersHeading } from "./service.ts";
test("orders heading", () => {
  assert.equal(ordersHeading("annual orders report"), "Annual Orders Report");
});
