import { ratio } from "./ratio.ts";

export function invoicesConversionRate(won: number, seen: number): number {
  return ratio(won, seen);
}
