import { clamp } from "./bounds.ts";

export function productsPriority(raw: number): number {
  return clamp(raw, 5, 15);
}
