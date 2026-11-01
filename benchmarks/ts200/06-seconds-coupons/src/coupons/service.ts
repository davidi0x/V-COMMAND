import { toSeconds } from "./time.ts";

export function couponsAgeSeconds(createdMs: number, nowMs: number): number {
  return toSeconds(nowMs - createdMs);
}
