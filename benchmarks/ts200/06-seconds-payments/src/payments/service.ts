import { toSeconds } from "./time.ts";

export function paymentsAgeSeconds(createdMs: number, nowMs: number): number {
  return toSeconds(nowMs - createdMs);
}
