import { test } from "node:test";
import assert from "node:assert/strict";
import { shipmentsTotal } from "./service.ts";
test("shipments total", () => {
  assert.equal(shipmentsTotal([{ price: 7, quantity: 3 }, { price: 1, quantity: 1 }]), 22);
});
