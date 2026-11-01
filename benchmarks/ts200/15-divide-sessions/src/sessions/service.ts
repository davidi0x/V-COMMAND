import { ratio } from "./ratio.ts";

export function sessionsConversionRate(won: number, seen: number): number {
  return ratio(won, seen);
}
