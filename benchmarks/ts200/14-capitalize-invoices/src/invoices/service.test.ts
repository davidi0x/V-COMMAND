import { test } from "node:test";
import assert from "node:assert/strict";
import { invoicesHeading } from "./service.ts";
test("invoices heading", () => {
  assert.equal(invoicesHeading("annual invoices report"), "Annual Invoices Report");
});
