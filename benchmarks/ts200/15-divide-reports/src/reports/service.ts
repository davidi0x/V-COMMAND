import { ratio } from "./ratio.ts";

export function reportsConversionRate(won: number, seen: number): number {
  return ratio(won, seen);
}
