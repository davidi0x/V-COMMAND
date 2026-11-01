import { test } from "node:test";
import assert from "node:assert/strict";
import { firstShipmentVersions } from "./service.ts";
test("shipments keeps first occurrence", () => {
  assert.deepEqual(firstShipmentVersions([{ id: 1, v: "a4" }, { id: 2, v: "b" }, { id: 1, v: "c" }]), ["a4", "b"]);
});
