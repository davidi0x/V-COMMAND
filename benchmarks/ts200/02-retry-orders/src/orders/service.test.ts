import { test } from "node:test";
import assert from "node:assert/strict";
import { fetchOrder } from "./service.ts";
test("orders retries", async () => {
  let calls = 0;
  const v = await fetchOrder(async () => { calls++; if (calls < 3) throw new Error("flaky"); return "ok"; });
  assert.equal(v, "ok");
  assert.equal(calls, 3);
});
