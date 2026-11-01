import { test } from "node:test";
import assert from "node:assert/strict";
import { firstPaymentVersions } from "./service.ts";
test("payments keeps first occurrence", () => {
  assert.deepEqual(firstPaymentVersions([{ id: 1, v: "a3" }, { id: 2, v: "b" }, { id: 1, v: "c" }]), ["a3", "b"]);
});
