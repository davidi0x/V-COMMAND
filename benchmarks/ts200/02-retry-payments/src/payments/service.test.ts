import { test } from "node:test";
import assert from "node:assert/strict";
import { fetchPayment } from "./service.ts";
test("payments retries", async () => {
  let calls = 0;
  const v = await fetchPayment(async () => { calls++; if (calls < 3) throw new Error("flaky"); return "ok"; });
  assert.equal(v, "ok");
  assert.equal(calls, 3);
});
