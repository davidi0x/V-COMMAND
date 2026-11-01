import { test } from "node:test";
import assert from "node:assert/strict";
import { ordersAgeSeconds } from "./service.ts";
test("orders age", () => {
  assert.equal(ordersAgeSeconds(5000, 7000), 2);
});
