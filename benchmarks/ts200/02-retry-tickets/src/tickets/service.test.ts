import { test } from "node:test";
import assert from "node:assert/strict";
import { fetchTicket } from "./service.ts";
test("tickets retries", async () => {
  let calls = 0;
  const v = await fetchTicket(async () => { calls++; if (calls < 5) throw new Error("flaky"); return "ok"; });
  assert.equal(v, "ok");
  assert.equal(calls, 5);
});
