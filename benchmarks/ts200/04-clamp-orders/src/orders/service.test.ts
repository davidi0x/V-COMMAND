import { test } from "node:test";
import assert from "node:assert/strict";
import { ordersPriority } from "./service.ts";
test("orders priority bounds", () => {
  assert.equal(ordersPriority(3), 3);
  assert.equal(ordersPriority(60), 10);
  assert.equal(ordersPriority(-5), 0);
});
