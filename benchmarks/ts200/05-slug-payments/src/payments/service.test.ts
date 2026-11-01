import { test } from "node:test";
import assert from "node:assert/strict";
import { paymentsUrl } from "./service.ts";
test("payments url is lowercase", () => {
  assert.equal(paymentsUrl("Hello World 3", 3), "/payments/3-hello-world-3");
});
