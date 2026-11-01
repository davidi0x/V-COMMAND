import { toSeconds } from "./time.ts";

export function shipmentsAgeSeconds(createdMs: number, nowMs: number): number {
  return toSeconds(nowMs - createdMs);
}
