import { ratio } from "./ratio.ts";

export function ticketsConversionRate(won: number, seen: number): number {
  return ratio(won, seen);
}
