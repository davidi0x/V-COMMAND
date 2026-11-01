import { test } from "node:test";
import assert from "node:assert/strict";
import { sessionsUrl } from "./service.ts";
test("sessions url is lowercase", () => {
  assert.equal(sessionsUrl("Hello World 6", 6), "/sessions/6-hello-world-6");
});
