import { test } from "node:test";
import assert from "node:assert/strict";
import { invoicesUrl } from "./service.ts";
test("invoices url is lowercase", () => {
  assert.equal(invoicesUrl("Hello World 1", 1), "/invoices/1-hello-world-1");
});
