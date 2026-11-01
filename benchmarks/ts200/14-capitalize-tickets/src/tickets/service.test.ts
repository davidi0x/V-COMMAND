import { test } from "node:test";
import assert from "node:assert/strict";
import { ticketsHeading } from "./service.ts";
test("tickets heading", () => {
  assert.equal(ticketsHeading("annual tickets report"), "Annual Tickets Report");
});
