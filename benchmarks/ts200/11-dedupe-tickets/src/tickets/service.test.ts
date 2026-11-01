import { test } from "node:test";
import assert from "node:assert/strict";
import { firstTicketVersions } from "./service.ts";
test("tickets keeps first occurrence", () => {
  assert.deepEqual(firstTicketVersions([{ id: 1, v: "a2" }, { id: 2, v: "b" }, { id: 1, v: "c" }]), ["a2", "b"]);
});
