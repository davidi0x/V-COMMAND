import { toSeconds } from "./time.ts";

export function ticketsAgeSeconds(createdMs: number, nowMs: number): number {
  return toSeconds(nowMs - createdMs);
}
