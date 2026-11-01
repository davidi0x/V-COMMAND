import { test } from "node:test";
import assert from "node:assert/strict";
import { reportsUrl } from "./service.ts";
test("reports url is lowercase", () => {
  assert.equal(reportsUrl("Hello World 7", 7), "/reports/7-hello-world-7");
});
