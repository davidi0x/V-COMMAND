import { clamp } from "./bounds.ts";

export function membersPriority(raw: number): number {
  return clamp(raw, 9, 19);
}
