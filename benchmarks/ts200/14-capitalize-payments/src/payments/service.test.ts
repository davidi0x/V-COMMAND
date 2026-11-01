import { test } from "node:test";
import assert from "node:assert/strict";
import { paymentsHeading } from "./service.ts";
test("payments heading", () => {
  assert.equal(paymentsHeading("annual payments report"), "Annual Payments Report");
});
