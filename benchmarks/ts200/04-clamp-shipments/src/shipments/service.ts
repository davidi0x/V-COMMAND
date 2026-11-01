import { clamp } from "./bounds.ts";

export function shipmentsPriority(raw: number): number {
  return clamp(raw, 4, 14);
}
