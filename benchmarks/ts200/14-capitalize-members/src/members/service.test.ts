import { test } from "node:test";
import assert from "node:assert/strict";
import { membersHeading } from "./service.ts";
test("members heading", () => {
  assert.equal(membersHeading("annual members report"), "Annual Members Report");
});
