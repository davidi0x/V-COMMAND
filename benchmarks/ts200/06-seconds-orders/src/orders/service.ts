import { toSeconds } from "./time.ts";

export function ordersAgeSeconds(createdMs: number, nowMs: number): number {
  return toSeconds(nowMs - createdMs);
}
