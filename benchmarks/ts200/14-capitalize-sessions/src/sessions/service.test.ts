import { test } from "node:test";
import assert from "node:assert/strict";
import { sessionsHeading } from "./service.ts";
test("sessions heading", () => {
  assert.equal(sessionsHeading("annual sessions report"), "Annual Sessions Report");
});
