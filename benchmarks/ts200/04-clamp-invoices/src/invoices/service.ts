import { clamp } from "./bounds.ts";

export function invoicesPriority(raw: number): number {
  return clamp(raw, 1, 11);
}
