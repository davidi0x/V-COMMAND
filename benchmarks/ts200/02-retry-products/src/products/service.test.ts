import { test } from "node:test";
import assert from "node:assert/strict";
import { fetchProduct } from "./service.ts";
test("products retries", async () => {
  let calls = 0;
  const v = await fetchProduct(async () => { calls++; if (calls < 5) throw new Error("flaky"); return "ok"; });
  assert.equal(v, "ok");
  assert.equal(calls, 5);
});
