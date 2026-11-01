import { test } from "node:test";
import assert from "node:assert/strict";
import { sessionsSearch } from "./service.ts";
test("sessions search decodes", () => {
  assert.equal(sessionsSearch("/sessions?q=caf%C3%A9+6%26co"), "café 6&co");
});
