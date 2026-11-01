import { ratio } from "./ratio.ts";

export function productsConversionRate(won: number, seen: number): number {
  return ratio(won, seen);
}
