import { ratio } from "./ratio.ts";

export function shipmentsConversionRate(won: number, seen: number): number {
  return ratio(won, seen);
}
