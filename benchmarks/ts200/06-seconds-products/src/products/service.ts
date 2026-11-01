import { toSeconds } from "./time.ts";

export function productsAgeSeconds(createdMs: number, nowMs: number): number {
  return toSeconds(nowMs - createdMs);
}
