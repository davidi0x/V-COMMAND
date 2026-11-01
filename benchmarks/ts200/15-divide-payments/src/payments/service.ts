import { ratio } from "./ratio.ts";

export function paymentsConversionRate(won: number, seen: number): number {
  return ratio(won, seen);
}
