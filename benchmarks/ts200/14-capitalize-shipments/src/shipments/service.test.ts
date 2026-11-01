import { test } from "node:test";
import assert from "node:assert/strict";
import { shipmentsHeading } from "./service.ts";
test("shipments heading", () => {
  assert.equal(shipmentsHeading("annual shipments report"), "Annual Shipments Report");
});
