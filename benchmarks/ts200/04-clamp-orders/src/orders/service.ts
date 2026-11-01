import { clamp } from "./bounds.ts";

export function ordersPriority(raw: number): number {
  return clamp(raw, 0, 10);
}
