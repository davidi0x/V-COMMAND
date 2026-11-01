import { test } from "node:test";
import assert from "node:assert/strict";
import { ordersUrl } from "./service.ts";
test("orders url is lowercase", () => {
  assert.equal(ordersUrl("Hello World 0", 0), "/orders/0-hello-world-0");
});
