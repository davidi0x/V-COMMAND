import { test } from "node:test";
import assert from "node:assert/strict";
import { reportsTotal } from "./service.ts";
test("reports total", () => {
  assert.equal(reportsTotal([{ price: 10, quantity: 3 }, { price: 1, quantity: 1 }]), 31);
});
