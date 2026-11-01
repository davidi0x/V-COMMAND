import { test } from "node:test";
import assert from "node:assert/strict";
import { firstReportVersions } from "./service.ts";
test("reports keeps first occurrence", () => {
  assert.deepEqual(firstReportVersions([{ id: 1, v: "a7" }, { id: 2, v: "b" }, { id: 1, v: "c" }]), ["a7", "b"]);
});
