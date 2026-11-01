import { test } from "node:test";
import assert from "node:assert/strict";
import { membersUrl } from "./service.ts";
test("members url is lowercase", () => {
  assert.equal(membersUrl("Hello World 9", 9), "/members/9-hello-world-9");
});
