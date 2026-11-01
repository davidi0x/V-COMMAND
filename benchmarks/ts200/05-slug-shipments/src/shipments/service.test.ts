import { test } from "node:test";
import assert from "node:assert/strict";
import { shipmentsUrl } from "./service.ts";
test("shipments url is lowercase", () => {
  assert.equal(shipmentsUrl("Hello World 4", 4), "/shipments/4-hello-world-4");
});
