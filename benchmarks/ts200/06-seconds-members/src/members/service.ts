import { toSeconds } from "./time.ts";

export function membersAgeSeconds(createdMs: number, nowMs: number): number {
  return toSeconds(nowMs - createdMs);
}
