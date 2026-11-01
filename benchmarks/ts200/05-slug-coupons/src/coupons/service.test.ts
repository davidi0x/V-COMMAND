import { test } from "node:test";
import assert from "node:assert/strict";
import { couponsUrl } from "./service.ts";
test("coupons url is lowercase", () => {
  assert.equal(couponsUrl("Hello World 8", 8), "/coupons/8-hello-world-8");
});
