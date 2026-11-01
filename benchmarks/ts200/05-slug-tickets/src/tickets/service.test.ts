import { test } from "node:test";
import assert from "node:assert/strict";
import { ticketsUrl } from "./service.ts";
test("tickets url is lowercase", () => {
  assert.equal(ticketsUrl("Hello World 2", 2), "/tickets/2-hello-world-2");
});
