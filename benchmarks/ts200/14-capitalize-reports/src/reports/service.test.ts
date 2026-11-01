import { test } from "node:test";
import assert from "node:assert/strict";
import { reportsHeading } from "./service.ts";
test("reports heading", () => {
  assert.equal(reportsHeading("annual reports report"), "Annual Reports Report");
});
