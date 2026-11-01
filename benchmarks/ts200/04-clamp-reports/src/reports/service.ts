import { clamp } from "./bounds.ts";

export function reportsPriority(raw: number): number {
  return clamp(raw, 7, 17);
}
