import { clamp } from "./bounds.ts";

export function paymentsPriority(raw: number): number {
  return clamp(raw, 3, 13);
}
