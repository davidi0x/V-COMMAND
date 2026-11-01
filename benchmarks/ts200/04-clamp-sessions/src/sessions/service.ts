import { clamp } from "./bounds.ts";

export function sessionsPriority(raw: number): number {
  return clamp(raw, 6, 16);
}
