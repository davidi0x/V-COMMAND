import { test } from "node:test";
import assert from "node:assert/strict";
import { fetchInvoice } from "./service.ts";
test("invoices retries", async () => {
  let calls = 0;
  const v = await fetchInvoice(async () => { calls++; if (calls < 4) throw new Error("flaky"); return "ok"; });
  assert.equal(v, "ok");
  assert.equal(calls, 4);
});
