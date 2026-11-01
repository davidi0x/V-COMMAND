import { clamp } from "./bounds.ts";

export function couponsPriority(raw: number): number {
  return clamp(raw, 8, 18);
}
