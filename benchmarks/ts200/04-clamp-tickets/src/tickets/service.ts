import { clamp } from "./bounds.ts";

export function ticketsPriority(raw: number): number {
  return clamp(raw, 2, 12);
}
