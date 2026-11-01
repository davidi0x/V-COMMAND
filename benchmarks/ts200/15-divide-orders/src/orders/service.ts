import { ratio } from "./ratio.ts";

export function ordersConversionRate(won: number, seen: number): number {
  return ratio(won, seen);
}
