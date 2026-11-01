import { test } from "node:test";
import assert from "node:assert/strict";
import { fetchMember } from "./service.ts";
test("members retries", async () => {
  let calls = 0;
  const v = await fetchMember(async () => { calls++; if (calls < 3) throw new Error("flaky"); return "ok"; });
  assert.equal(v, "ok");
  assert.equal(calls, 3);
});
