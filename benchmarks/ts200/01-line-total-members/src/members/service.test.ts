import { test } from "node:test";
import assert from "node:assert/strict";
import { membersTotal } from "./service.ts";
test("members total", () => {
  assert.equal(membersTotal([{ price: 12, quantity: 2 }, { price: 1, quantity: 1 }]), 25);
});
