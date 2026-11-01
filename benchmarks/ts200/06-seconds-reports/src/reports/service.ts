import { toSeconds } from "./time.ts";

export function reportsAgeSeconds(createdMs: number, nowMs: number): number {
  return toSeconds(nowMs - createdMs);
}
