import { ratio } from "./ratio.ts";

export function couponsConversionRate(won: number, seen: number): number {
  return ratio(won, seen);
}
