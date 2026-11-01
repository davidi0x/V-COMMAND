import { toSeconds } from "./time.ts";

export function sessionsAgeSeconds(createdMs: number, nowMs: number): number {
  return toSeconds(nowMs - createdMs);
}
