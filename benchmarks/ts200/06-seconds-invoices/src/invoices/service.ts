import { toSeconds } from "./time.ts";

export function invoicesAgeSeconds(createdMs: number, nowMs: number): number {
  return toSeconds(nowMs - createdMs);
}
