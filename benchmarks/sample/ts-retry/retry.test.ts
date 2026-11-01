import { test } from "node:test";
import assert from "node:assert/strict";
import { retry } from "./retry.ts";

test("succeeds on the last allowed attempt", async () => {
  let calls = 0;
  const value = await retry(async () => {
    calls++;
    if (calls < 3) throw new Error("flaky");
    return "ok";
  }, 3);
  assert.equal(value, "ok");
  assert.equal(calls, 3);
});
